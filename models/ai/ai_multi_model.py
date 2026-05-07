"""Multi-model AI feedback — run the same query against multiple models simultaneously.

This module adds support for:
- Saving multiple AI models against a resource (via ai_model_ids on aps.resources).
- Running all selected models concurrently using threads and collecting results.
- Merging results either by AI-driven consolidation (ai_merge_responses=True)
  or by simple concatenation.
- For targeted feedback: merging chunks with identical labels
  (ai_merge_response_chunks=True) or simply combining all chunks.

Usage:
    self.env['aps.ai.model'].generate_multi_model_feedback(record, ai_run=ai_run)

When fewer than two models are configured the call falls back to the
single-model ``generate_feedback`` path transparently.
"""
import concurrent.futures
import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System / user prompts for the AI-driven merge step
# ---------------------------------------------------------------------------

_MERGE_SYSTEM_PROMPT = (
    'You are an expert editor. You will be given feedback on a student answer '
    'from multiple AI models. Keep each model response as a separate HTML block '
    'in the same order received. Do not remove contradictions. '
    'Do not anonymize model provenance. '
    'At the end of EACH model block, include exactly: '
    '<p style="font-size:10px;opacity:0.65;">Model: MODEL_NAME</p><hr/> '
    '(replace MODEL_NAME with that block\'s model name). '
    'Return ONLY an HTML fragment using tags such as '
    '<h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.'
)

_MERGE_USER_PROMPT_TEMPLATE = (
    'Here are the feedback responses from multiple AI models. '
    'Return one section per model (same order), with the required attribution '
    'line and horizontal rule at the end of each section:\n\n%s'
)


# ---------------------------------------------------------------------------
# Thread worker — executed outside the main Odoo cursor
# ---------------------------------------------------------------------------

def _run_single_model_in_thread(db_name, model_id, record_model, record_id, user_id, context):
    """Run one AI model in its own database cursor and return (result, error_text)."""
    try:
        db_registry = Registry(db_name)
        with db_registry.cursor() as cr:
            env = api.Environment(cr, user_id, context or {})
            ai_model = env['aps.ai.model'].sudo().browse(model_id)
            if not ai_model.exists():
                return None, 'Model %s no longer exists.' % model_id
            record = env[record_model].sudo().browse(record_id)
            if not record.exists():
                return None, 'Record %s/%s no longer exists.' % (record_model, record_id)
            # Do not stream from parallel worker threads: concurrent writes to the
            # same aps.ai.run record can trigger serialization failures.
            result = ai_model._run_feedback(record, ai_run=None)
            cr.commit()
            return result, None
    except Exception as exc:
        _logger.exception(
            'Parallel AI run failed for model_id=%s record=%s/%s',
            model_id, record_model, record_id,
        )
        return None, str(exc)


# ---------------------------------------------------------------------------
# Model mixin
# ---------------------------------------------------------------------------

class APSAIMultiModelFeedback(models.Model):
    _inherit = 'aps.ai.model'

    # =========================================================================
    # Public entry point
    # =========================================================================

    @api.model
    def generate_multi_model_feedback(self, record, ai_run=None):
        """Run all models from resource.ai_model_ids concurrently and merge results.

        When fewer than two models are configured the call delegates to the
        normal single-model ``generate_feedback`` path.
        """
        record.ensure_one()
        resource = self._get_resource_for_record(record)
        model_ids_to_run = (
            resource.ai_model_ids.ids if resource and resource.ai_model_ids else []
        )

        if len(model_ids_to_run) <= 1:
            return self.generate_feedback(record, ai_run=ai_run)

        if ai_run:
            ai_run._write_progress({
                'status_message': _(
                    'Running %d AI models simultaneously — this may take a moment...'
                ) % len(model_ids_to_run),
            })

        db_name = self.env.cr.dbname
        user_id = self.env.user.id
        context = dict(self.env.context or {})
        record_model = record._name
        record_id = record.id

        results, errors = self._run_models_parallel(
            model_ids_to_run,
            db_name,
            record_model,
            record_id,
            user_id,
            context,
        )

        if not results:
            if errors:
                raise UserError(_('All AI models failed:\n%s') % '\n'.join(errors[:5]))
            raise UserError(_('No AI models returned results.'))

        if errors:
            _logger.warning(
                'Multi-model run: %d succeeded, %d failed. Errors: %s',
                len(results), len(errors), '; '.join(errors),
            )

        if ai_run:
            ai_run._write_progress({'status_message': _('Merging AI model responses...')})

        # Re-read merge settings from the resource in the current env.
        resource = self._get_resource_for_record(record)
        merge_responses = bool(resource.ai_merge_responses) if resource else False
        merge_response_chunks = bool(resource.ai_merge_response_chunks) if resource else False

        is_targeted = any(r.get('targeted_feedback') for r in results)
        if is_targeted:
            return self._merge_targeted_results(results, merge_response_chunks)
        return self._merge_generic_results(results, merge_responses)

    # =========================================================================
    # Parallel execution
    # =========================================================================

    @api.model
    def _run_models_parallel(self, model_ids, db_name, record_model, record_id, user_id, context):
        """Run each model_id in its own thread; return (results_list, errors_list)."""
        results = []
        errors = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(model_ids), 10),
            thread_name_prefix='aps_ai_multi',
        ) as executor:
            future_to_mid = {
                executor.submit(
                    _run_single_model_in_thread,
                    db_name, mid, record_model, record_id, user_id, context,
                ): mid
                for mid in model_ids
            }
            for future in concurrent.futures.as_completed(future_to_mid):
                result, error = future.result()
                if error:
                    errors.append(error)
                elif result:
                    results.append(result)

        return results, errors

    # =========================================================================
    # Generic (non-targeted) result merging
    # =========================================================================

    @api.model
    def _merge_generic_results(self, results, merge_via_ai):
        """Combine or AI-merge non-targeted feedback from multiple models.

        Parameters
        ----------
        results : list[dict]
            Each dict is the return value of ``_run_feedback_generic``.
        merge_via_ai : bool
            If True, ask one AI model to merge all feedback_html parts.
            If False, concatenate them separated by horizontal rules.
        """
        if len(results) == 1:
            return results[0]

        response_parts = [
            {
                'html': r.get('feedback_html') or '',
                'model_name': r.get('model_name') or _('Unknown Model'),
            }
            for r in results
            if r.get('feedback_html')
        ]
        total_prompt_tokens = sum(r.get('prompt_tokens') or 0 for r in results)
        total_completion_tokens = sum(r.get('completion_tokens') or 0 for r in results)
        total_cost = sum(r.get('estimated_cost') or 0.0 for r in results)

        merged_html = None
        if merge_via_ai:
            merged_html = self._call_ai_merge(response_parts, results)

        if not merged_html:
            # Always include model attribution for multi-model output so users
            # can clearly see provenance for each response block.
            merged_html = self._concatenate_feedback_html(
                response_parts,
                include_attribution=True,
            )

        score = next((r.get('score') for r in results if r.get('score') is not None), None)
        score_comment = next((r.get('score_comment') for r in results if r.get('score_comment')), None)

        return {
            'feedback_html': merged_html,
            'score': score,
            'score_comment': score_comment,
            'answer_chunks': False,
            'answer_chunked_html': False,
            'feedback_items': False,
            'feedback_links': False,
            'targeted_feedback': False,
            'prompt_tokens': total_prompt_tokens,
            'completion_tokens': total_completion_tokens,
            'estimated_cost': total_cost,
            'model_id': False,
            'model_name': _('Multiple AI Models'),
            'raw_content': '\n---\n'.join(r.get('raw_content') or '' for r in results),
        }

    @api.model
    def _concatenate_feedback_html(self, html_parts, include_attribution=False):
        """Join multiple feedback HTML parts with horizontal rule separators."""
        if not html_parts:
            return '<p>No feedback was returned.</p>'

        parts = []
        for i, part in enumerate(html_parts, start=1):
            if isinstance(part, dict):
                html = part.get('html') or ''
                model_name = part.get('model_name') or _('Unknown Model')
                if include_attribution:
                    parts.append(
                        '%s<p style="font-size:10px;opacity:0.65;">Model: %s</p><hr/>'
                        % (html, model_name)
                    )
                else:
                    parts.append(html)
                    if i < len(html_parts):
                        parts.append('<hr/>')
            else:
                # Backward-compatibility: plain html string list.
                plain_html = part or ''
                parts.append(plain_html)
                if i < len(html_parts):
                    parts.append('<hr/>')
        return ''.join(parts)

    @api.model
    def _call_ai_merge(self, html_parts, results):
        """Ask one AI model to merge all feedback_html parts into a single response.

        Uses the first model from *results* that has a model_id.  Returns None
        on any failure so callers can fall back to simple concatenation.
        """
        merge_model_id = next(
            (r.get('model_id') for r in results if r.get('model_id')),
            None,
        )
        if not merge_model_id:
            return None

        merge_model = self.env['aps.ai.model'].sudo().browse(merge_model_id)
        if not merge_model.exists():
            return None

        numbered_parts = '\n\n---\n\n'.join(
            'Feedback %d (Model: %s):\n%s'
            % (
                i,
                (part.get('model_name') if isinstance(part, dict) else _('Unknown Model')),
                (part.get('html') if isinstance(part, dict) else (part or '')),
            )
            for i, part in enumerate(html_parts, start=1)
        )
        payload = {
            'model': merge_model.model_key,
            'messages': [
                {'role': 'system', 'content': _MERGE_SYSTEM_PROMPT},
                {'role': 'user', 'content': _MERGE_USER_PROMPT_TEMPLATE % numbered_parts},
            ],
            'temperature': merge_model.temperature,
            'max_completion_tokens': merge_model.max_completion_tokens,
        }
        if merge_model.disable_reasoning:
            payload['reasoning'] = {'enabled': False, 'exclude': True}

        try:
            result = merge_model._execute_logged_router_call(
                payload,
                request_type='multi_model_merge',
            )
            raw_content = merge_model._extract_message_content(result['response_json'])
            return merge_model._normalize_feedback_html(raw_content)
        except Exception:
            _logger.exception('AI merge call failed; falling back to concatenation.')
            return None

    # =========================================================================
    # Targeted feedback result merging
    # =========================================================================

    @api.model
    def _merge_targeted_results(self, results, merge_chunks):
        """Combine or merge targeted feedback from multiple models.

        Parameters
        ----------
        results : list[dict]
            Each dict is the return value of ``_run_feedback_targeted``.
        merge_chunks : bool
            If True, feedback items with identical text labels are merged into
            a single item and their chunk links are combined.
            If False, all items are simply concatenated (with de-duplication
            of identical label+type pairs).
        """
        if len(results) == 1:
            return results[0]

        # Reuse the answer chunks from the first result with chunks (all models
        # received the same answer so the chunking should be identical).
        first_with_chunks = next((r for r in results if r.get('answer_chunks')), results[0])
        answer_chunks = first_with_chunks.get('answer_chunks') or False
        answer_chunked_html = first_with_chunks.get('answer_chunked_html') or False

        total_prompt_tokens = sum(r.get('prompt_tokens') or 0 for r in results)
        total_completion_tokens = sum(r.get('completion_tokens') or 0 for r in results)
        total_cost = sum(r.get('estimated_cost') or 0.0 for r in results)

        all_items = []
        all_links = []
        for idx, result in enumerate(results, start=1):
            # IDs returned by each model often restart at f1/f2/..., so namespace
            # them per model result to avoid cross-model collisions.
            result_prefix = 'm%s__' % idx

            for item in (result.get('feedback_items') or []):
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get('id') or '').strip()
                if not item_id:
                    continue
                all_items.append({
                    'id': '%s%s' % (result_prefix, item_id),
                    'text': item.get('text') or '',
                    'type': item.get('type') or False,
                    'justification': item.get('justification') or '',
                })

            for link in (result.get('feedback_links') or []):
                if not isinstance(link, dict):
                    continue
                feedback_id = str(link.get('feedback_id') or '').strip()
                if not feedback_id:
                    continue
                all_links.append({
                    'feedback_id': '%s%s' % (result_prefix, feedback_id),
                    'chunk_ids': link.get('chunk_ids') or [],
                })

        if merge_chunks:
            feedback_items, feedback_links = self._merge_feedback_items_by_label(all_items, all_links)
        else:
            feedback_items, feedback_links = self._combine_feedback_items(all_items, all_links)

        html_parts = [r.get('feedback_html') or '' for r in results if r.get('feedback_html')]
        merged_html = self._concatenate_feedback_html(html_parts)

        score = next((r.get('score') for r in results if r.get('score') is not None), None)
        score_comment = next((r.get('score_comment') for r in results if r.get('score_comment')), None)

        return {
            'feedback_html': merged_html,
            'score': score,
            'score_comment': score_comment,
            'answer_chunks': answer_chunks,
            'answer_chunked_html': answer_chunked_html,
            'feedback_items': feedback_items or False,
            'feedback_links': feedback_links or False,
            'targeted_feedback': bool(feedback_items),
            'prompt_tokens': total_prompt_tokens,
            'completion_tokens': total_completion_tokens,
            'estimated_cost': total_cost,
            'model_id': False,
            'model_name': _('Multiple AI Models'),
            'raw_content': '\n---\n'.join(r.get('raw_content') or '' for r in results),
        }

    @api.model
    def _combine_feedback_items(self, all_items, all_links):
        """Combine feedback items from multiple models, assigning fresh unique IDs.

        Exact duplicates (same text label + type) are de-duplicated.
        """
        seen_keys = set()
        id_remap = {}  # original_id -> new_id
        combined_items = []

        for item in all_items:
            old_id = item.get('id') or ''
            dedup_key = (
                (item.get('text') or '').strip().casefold(),
                item.get('type') or '',
            )
            if dedup_key in seen_keys:
                # Map this ID to the already-accepted item's ID.
                for existing in combined_items:
                    if (existing.get('text') or '').strip().casefold() == dedup_key[0]:
                        id_remap[old_id] = existing['id']
                        break
                continue
            seen_keys.add(dedup_key)
            new_id = 'f%d' % (len(combined_items) + 1)
            id_remap[old_id] = new_id
            combined_items.append({
                'id': new_id,
                'text': item.get('text') or '',
                'type': item.get('type') or False,
                'justification': item.get('justification') or '',
            })

        combined_links = []
        for link in all_links:
            old_fid = link.get('feedback_id') or ''
            new_fid = id_remap.get(old_fid)
            if not new_fid:
                continue
            combined_links.append({
                'feedback_id': new_fid,
                'chunk_ids': link.get('chunk_ids') or [],
            })

        return combined_items, combined_links

    @api.model
    def _merge_feedback_items_by_label(self, all_items, all_links):
        """Merge feedback items that share the same text label (case-insensitive).

        Items with identical labels have their justifications combined.
        Their chunk links are merged so that all affected chunks are included.
        """
        label_to_id = {}     # normalised_label -> new_id
        merged_items = {}    # new_id -> item dict
        id_remap = {}        # original_id -> new_id

        for item in all_items:
            old_id = item.get('id') or ''
            label = (item.get('text') or '').strip()
            norm_label = label.casefold()

            if norm_label in label_to_id:
                new_id = label_to_id[norm_label]
                existing = merged_items[new_id]
                # Append justification if it adds new information.
                existing_just = (existing.get('justification') or '').strip()
                new_just = (item.get('justification') or '').strip()
                if new_just and new_just.casefold() not in existing_just.casefold():
                    sep = ' ' if not existing_just or existing_just.endswith('.') else '. '
                    existing['justification'] = (existing_just + sep + new_just).strip()
                id_remap[old_id] = new_id
            else:
                new_id = 'f%d' % (len(merged_items) + 1)
                label_to_id[norm_label] = new_id
                merged_items[new_id] = {
                    'id': new_id,
                    'text': label,
                    'type': item.get('type') or False,
                    'justification': item.get('justification') or '',
                }
                id_remap[old_id] = new_id

        # Rebuild links with merged chunk sets.
        merged_chunks_by_fid = {}   # new_feedback_id -> set of chunk_ids
        for link in all_links:
            old_fid = link.get('feedback_id') or ''
            new_fid = id_remap.get(old_fid)
            if not new_fid:
                continue
            chunk_set = merged_chunks_by_fid.setdefault(new_fid, set())
            for chunk_id in link.get('chunk_ids') or []:
                chunk_set.add(chunk_id)

        merged_links = [
            {'feedback_id': fid, 'chunk_ids': sorted(chunks)}
            for fid, chunks in merged_chunks_by_fid.items()
            if chunks
        ]

        return list(merged_items.values()), merged_links

    # =========================================================================
    # Helper
    # =========================================================================

    @api.model
    def _get_resource_for_record(self, record):
        """Return the aps.resources record that controls AI settings for *record*.

        For aps.resources the record itself is returned.
        For aps.resource.submission the linked resource_id is returned.
        """
        if record._name == 'aps.resources':
            return record
        if hasattr(record, 'resource_id') and record.resource_id:
            return record.resource_id
        return None
