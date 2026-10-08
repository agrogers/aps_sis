from difflib import SequenceMatcher
from html import escape
from itertools import combinations
import json
import math
import re

from markupsafe import Markup
from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

NO_DETAILED_FEEDBACK_HTML = '<p><em>No detailed feedback was returned by the AI model.</em></p>'
SAMPLE_SCALING_PROMPT_NAME = 'use sample scaling'
SAMPLE_COMPARISON_PROMPT_NAME = 'use sample comparison'
SAMPLE_COMPARISON_RESOURCE_TAG = 'sample answer'
SAMPLE_COMPARISON_SAME_TOLERANCE = 1.0
SAMPLE_RUBRIC_SIMILARITY_THRESHOLD = 0.8
_SKIP_CHANNEL_FORWARD_CTX = 'aui_skip_channel_forward'


class APSAIFeedbackStorageMixin(models.AbstractModel):
    _name = 'aps.ai.feedback.storage.mixin'
    _description = 'Shared AI Feedback Storage'

    ai_answer_chunks = fields.Json(string='AI Answer Chunks', readonly=True, copy=False)
    ai_answer_chunked_html = fields.Text(string='AI Chunked Answer HTML', readonly=True, copy=False)
    ai_feedback_items = fields.Json(string='AI Feedback Items', readonly=True, copy=False)
    ai_feedback_links = fields.Json(string='AI Feedback Links', readonly=True, copy=False)

    def _get_ai_feedback_storage_field_name(self):
        self.ensure_one()
        return 'feedback'

    def _get_ai_feedback_resource(self):
        self.ensure_one()
        return self if self._name == 'aps.resources' else self.resource_id

    def _get_sample_scaling_prompt(self):
        self.ensure_one()
        resource = self._get_ai_feedback_resource()
        prompts = resource.ai_prompt_ids.filtered(
            lambda prompt: (prompt.prompt_name or '').strip().casefold() == SAMPLE_SCALING_PROMPT_NAME
        )
        return prompts[:1]

    def _uses_sample_scaling(self):
        return bool(self._get_sample_scaling_prompt())

    def _get_sample_comparison_prompt(self):
        self.ensure_one()
        resource = self._get_ai_feedback_resource()
        return resource.ai_prompt_ids.filtered(
            lambda prompt: (prompt.prompt_name or '').strip().casefold() == SAMPLE_COMPARISON_PROMPT_NAME
        )[:1]

    def _uses_sample_comparison(self):
        return bool(self._get_sample_comparison_prompt())

    def _get_sample_comparison_benchmarks(self, resource=None):
        self.ensure_one()
        resource = resource or self._get_ai_feedback_resource()
        linked_resources = resource.supporting_resource_ids | resource.child_ids
        return linked_resources.filtered(
            lambda sample: any(
                (tag.name or '').strip().casefold() == SAMPLE_COMPARISON_RESOURCE_TAG
                for tag in sample.tag_ids
            )
        ).sorted(key=lambda sample: (sample.weight, sample.id))

    @staticmethod
    def calculate_score_range(comparisons, target_maximum, same_tolerance=SAMPLE_COMPARISON_SAME_TOLERANCE):
        """Return an explainable score interval and monotonic-fit diagnostics.

        Evidence is sorted by benchmark score. All monotonic BETTER* / SAME* /
        WORSE* patterns are tested; the pattern with the fewest disagreements
        is selected, with score-distance severity as the tie-break. Comparisons
        are never removed from the returned diagnostics.
        """
        maximum = max(0.0, float(target_maximum or 0.0))
        tolerance = max(0.0, float(same_tolerance or 0.0))
        valid = sorted(
            [dict(item) for item in (comparisons or []) if item.get('result') in ('BETTER', 'SAME', 'WORSE')],
            key=lambda item: (float(item.get('benchmark_score') or 0.0), item.get('benchmark_id') or 0),
        )
        if not valid or maximum <= 0:
            return {
                'score_lower': 0,
                'score_upper': int(math.floor(maximum)),
                'score_estimate': int(round(maximum / 2.0)),
                'confidence': 'LOW',
                'anomaly_count': 0,
                'anomaly_severity': 0.0,
                'comparisons': valid,
                'fit_results': [],
            }

        n = len(valid)
        patterns = []
        # A monotonic pattern consists of zero or more BETTER, then SAME,
        # then WORSE results. Enumerating the two boundaries is transparent
        # and inexpensive for the expected 3-4 benchmarks.
        for better_end in range(n + 1):
            for same_end in range(better_end, n + 1):
                predicted = [
                    'BETTER' if index < better_end else
                    'SAME' if index < same_end else 'WORSE'
                    for index in range(n)
                ]
                mismatches = [
                    index for index, item in enumerate(valid)
                    if item['result'] != predicted[index]
                ]
                distance_cost = sum(
                    min(
                        abs(float(valid[index]['benchmark_score']) - float(valid[other]['benchmark_score']))
                        for other in range(n) if other != index and valid[other]['result'] == predicted[index]
                    ) if any(other != index and valid[other]['result'] == predicted[index] for other in range(n))
                    else maximum
                    for index in mismatches
                )
                patterns.append((len(mismatches), distance_cost, better_end, same_end, predicted))

        _mismatch_count, _distance_cost, _better_end, _same_end, predicted = min(
            patterns,
            key=lambda item: (item[0], item[1], item[2], item[3]),
        )
        for index, item in enumerate(valid):
            item['predicted_result'] = predicted[index]
            item['anomaly'] = item['result'] != predicted[index]
            item['anomaly_severity'] = 0.0

        if all(item['result'] == 'SAME' for item in valid):
            same_center = sorted(float(item['benchmark_score']) for item in valid)[len(valid) // 2]
            for item in valid:
                gap = abs(float(item['benchmark_score']) - same_center)
                if gap > tolerance and len(valid) > 1:
                    item['anomaly'] = True
                    item['anomaly_severity'] = min(1.0, gap / maximum) if maximum else 0.0

        for index, item in enumerate(valid):
            if not item['anomaly']:
                continue
            conflicting_scores = [
                float(other['benchmark_score']) for other in valid
                if other['result'] == item['predicted_result'] and other is not item
            ]
            if conflicting_scores:
                gap = min(abs(float(item['benchmark_score']) - score) for score in conflicting_scores)
            else:
                gap = maximum
            item['anomaly_severity'] = min(1.0, gap / maximum) if maximum else 0.0

        same_items = [item for item in valid if item['result'] == 'SAME']
        if len(same_items) > 1:
            same_center = sorted(float(item['benchmark_score']) for item in same_items)[len(same_items) // 2]
            farthest_same = max(same_items, key=lambda item: abs(float(item['benchmark_score']) - same_center))
            same_gap = abs(float(farthest_same['benchmark_score']) - same_center)
            if same_gap > tolerance and not farthest_same['anomaly']:
                farthest_same['anomaly'] = True
                farthest_same['anomaly_severity'] = min(1.0, (same_gap - tolerance) / maximum) if maximum else 0.0

        anomaly_count = sum(bool(item['anomaly']) for item in valid)
        anomaly_severity = min(1.0, sum(item['anomaly_severity'] for item in valid))
        has_severe_conflict = anomaly_count > 1 or anomaly_severity >= 0.35

        consistent = [item for item in valid if not item['anomaly']]
        if not consistent:
            consistent = valid
        better_scores = [float(item['benchmark_score']) for item in consistent if item['result'] == 'BETTER']
        worse_scores = [float(item['benchmark_score']) for item in consistent if item['result'] == 'WORSE']
        same_scores = [float(item['benchmark_score']) for item in consistent if item['result'] == 'SAME']
        lower = math.ceil(max(better_scores)) if better_scores else 0
        upper = math.floor(min(worse_scores)) if worse_scores else int(math.floor(maximum))

        if better_scores and worse_scores and max(better_scores) > min(worse_scores):
            if has_severe_conflict:
                lower = math.floor(min(float(item['benchmark_score']) for item in valid))
                upper = math.ceil(max(float(item['benchmark_score']) for item in valid))
            else:
                lower, upper = sorted((max(better_scores), min(worse_scores)))

        # SAME is a tolerance band, not equality. When the band intersects the
        # BETTER/WORSE bracket, use the intersection as the more local evidence.
        if same_scores:
            center = float(sorted(same_scores)[len(same_scores) // 2])
            same_lower = max(0, math.ceil(center - tolerance))
            same_upper = min(int(math.floor(maximum)), math.floor(center + tolerance))
            if len(same_scores) == len(valid):
                lower, upper = same_lower, same_upper
            elif max(lower, same_lower) <= min(upper, same_upper):
                lower, upper = max(lower, same_lower), min(upper, same_upper)
            elif anomaly_count:
                lower, upper = min(lower, same_lower), max(upper, same_upper)

        # Grossly contradictory evidence must not create false precision. Keep
        # the bracket broad over the benchmark span and use its midpoint.
        if has_severe_conflict:
            lower = min(lower, int(math.floor(min(float(item['benchmark_score']) for item in valid))))
            upper = max(upper, int(math.ceil(max(float(item['benchmark_score']) for item in valid))))

        lower = max(0, min(int(math.floor(maximum)), int(lower)))
        upper = max(lower, min(int(math.floor(maximum)), int(upper)))
        if same_scores:
            estimate_source = sorted(same_scores)[len(same_scores) // 2]
        elif lower <= upper:
            estimate_source = (lower + upper) / 2.0
        else:
            estimate_source = maximum / 2.0
        estimate = max(lower, min(upper, int(math.floor(estimate_source + 0.5))))

        if anomaly_count or len(valid) < 3 or not better_scores or not worse_scores:
            confidence = 'LOW' if has_severe_conflict or anomaly_count >= 2 else 'MEDIUM'
        else:
            confidence = 'HIGH'
        return {
            'score_lower': lower,
            'score_upper': upper,
            'score_estimate': estimate,
            'confidence': confidence,
            'anomaly_count': anomaly_count,
            'anomaly_severity': anomaly_severity,
            'comparisons': valid,
            'fit_results': [
                {'benchmark_id': item.get('benchmark_id'), 'predicted_result': predicted[index]}
                for index, item in enumerate(valid)
            ],
        }

    def _get_sample_comparison_model(self, ai_model_service, resource, contexts, ai_run):
        vision_required = any(
            ai_model_service._feedback_context_requires_vision(context) for context in contexts
        )
        override = ai_run.override_model_id if ai_run and ai_run.override_model_id else False
        if override:
            if not override.enabled or not override.provider_id.enabled:
                raise UserError(_('The selected AI override model is not enabled.'))
            if vision_required and not override.supports_vision:
                raise UserError(_('The selected AI override model does not support the required images.'))
            return override
        candidates = ai_model_service._get_generation_candidates(
            resource=resource,
            require_vision=vision_required,
        )
        if not candidates:
            raise UserError(_('No enabled AI model can process this sample-comparison request.'))
        return candidates[:1]

    def _get_sample_comparison_prompts(self, resource, strategy_prompt):
        image_prompt_names = {
            'include images',
            'include question images',
            'include specific instructions images',
            'include model answer images',
            'include notes images',
        }
        image_prompts = resource.ai_active_prompts.filtered(
            lambda prompt: (prompt.prompt_name or '').strip().casefold() in image_prompt_names
        )
        return strategy_prompt | image_prompts

    def _build_sample_comparison_context(self, target_context, strategy_prompt, benchmark_answer, benchmark_name):
        resource = self._get_ai_feedback_resource()
        prompts = self._get_sample_comparison_prompts(resource, strategy_prompt)
        rubric = target_context.get('model_answer') or ''
        comparison_instructions = _(
            'Compare the Answer 1 in <answer_1> with the Answer 2 in <answer_2>. '
            'These labels are authoritative. Never swap them, refer to them as Answer A or Answer B, or infer either '
            'answer from the order in which text appears. Use the supplied marking rubric to judge '
            'both answers against the same task. Focus only on the criteria stated '
            'in the supplied rubric. Do not introduce, assume, or substitute a topic or criteria not stated in the '
            'rubric. \n'
            'Do not evaluate the topic or subject matter. Do not consider whether either answer stays on topic or is relevant to a particular subject '
            'unless the supplied rubric explicitly includes that criterion.'
            'Additional information about either answer is intentionally withheld. '
            'Do not assign or infer a numerical mark. Return exactly one valid JSON object '
            'with keys "result" and "reason". \n'
            'Classify Answer 1 relative to Answer 2 (not the other way around): '
            '"BETTER" means Answer 1 is clearly stronger than Answer 2; '
            '"SAME" means they are essentially equivalent; '
            '"WORSE" means Answer 1 is clearly weaker than Answer 2. Differences of about '
            '%(tolerance)s marks should normally be treated as SAME. '
            'In "reason", explain which answer is stronger using the exact labels "Answer 1" and "Answer 2".'
            'Before returning, verify that the result '
            'agrees with the reason: if the reason says Answer 2 is stronger or Answer 1 is weaker, the result '
            'must be "WORSE"; if it says Answer 1 is stronger, the result must be "BETTER"; if neither is '
            'clearly stronger, use "SAME". Explain the comparison only against the supplied question and rubric.'
        ) % {'tolerance': self._format_sample_scaling_score(SAMPLE_COMPARISON_SAME_TOLERANCE)}
        return {
            **target_context,
            'instructions': '%s\n\n%s' % (
                target_context.get('instructions') or '',
                comparison_instructions,
            ),
            'out_of_marks': False,
            'output_schema_override': (
                'Return ONLY valid JSON with exactly these keys: '
                '{"result":"BETTER|SAME|WORSE","reason":"brief explanation"}. '
                'The result describes Answer 1 relative to Answer 2. Check that its direction agrees with the '
                'reason: Answer 2 stronger means WORSE; Answer 1 stronger means BETTER. '
                'Do not return a score or any additional keys.'
            ),
            'use_model_answer': bool(rubric),
            'model_answer': rubric,
            'use_note': True,
            'note_section_key': 'answer_2',
            'comparison_pair': True,
            'notes': benchmark_answer or '',
            'answer_2_resource_name': benchmark_name,
            'ai_targeted_feedback': False,
            'prompt_ids': prompts,
            'image_prompt_names': prompts.mapped('prompt_name'),
            'image_sources': {
                **(target_context.get('image_sources') or {}),
                'student_answer': target_context.get('student_answer_html') or '',
                'question': target_context.get('question') or '',
                'model_answer': rubric,
                'instructions': target_context.get('instructions') or '',
                'notes': benchmark_answer or '',
            },
        }

    def _build_sample_comparison_final_context(self, target_context, strategy_prompt, scored_samples, calibration):
        resource = self._get_ai_feedback_resource()
        marking_prompts = resource.ai_active_prompts.filtered(
            lambda prompt: (prompt.prompt_name or '').strip().casefold() not in (
                SAMPLE_SCALING_PROMPT_NAME,
                SAMPLE_COMPARISON_PROMPT_NAME,
            )
        )
        score_guidance = _(
            'Use the calibrated comparison evidence; do not independently rescore from scratch. '
            'Choose the final mark within the range %(lower)s-%(upper)s out of %(maximum)s, normally.'
        ) % {
            'lower': calibration['score_lower'],
            'upper': calibration['score_upper'],
            'maximum': self._format_sample_scaling_score(target_context.get('out_of_marks') or 0),
        }
        return {
            **target_context,
            'score_guidance': score_guidance,
            'prompt_ids': marking_prompts,
            'image_prompt_names': marking_prompts.mapped('prompt_name'),
        }

    def _build_sample_comparison_audit_html(self, audit):
        parts = ['<p><strong>%s</strong></p>' % escape(_('AI MARKING COMPARISON'))]
        if audit.get('prompt_conflict'):
            parts.append('<p><strong>%s</strong></p>' % escape(_(
                'Both sample comparison and sample scaling were selected; comparison took precedence.'
            )))
        parts.append('<p>%s</p>' % escape(audit.get('summary') or ''))
        parts.append('<ul>')
        for item in audit.get('comparisons') or []:
            benchmark_name = item.get('benchmark_name') or _('Sample')
            official_score = self._format_sample_scaling_score(item.get('official_score') or 0)
            maximum = self._format_sample_scaling_score(item.get('maximum') or 0)
            score_label = '(%s/%s)' % (official_score, maximum)
            if score_label in benchmark_name:
                label = '%s: %s' % (
                    benchmark_name,
                    item.get('result') or item.get('status') or _('Unavailable'),
                )
            else:
                label = '%s %s: %s' % (
                    benchmark_name,
                    score_label,
                    item.get('result') or item.get('status') or _('Unavailable'),
                )
            if item.get('anomaly'):
                label += ' [ANOMALY; severity %s]' % self._format_sample_scaling_score(
                    item.get('anomaly_severity') or 0
                )
            parts.append('<li><strong>%s</strong>' % escape(label))
            if item.get('reason'):
                parts.append('<br/>%s' % escape(item['reason']))
            if item.get('model_name'):
                parts.append('<br/>%s %s' % (escape(_('Model:')), escape(item['model_name'])))
            parts.append('</li>')
        parts.append('</ul>')
        if audit.get('score_lower') is not None:
            parts.append('<p>%s</p>' % escape(_(
                'Estimated score: %(estimate)s/%(maximum)s; range: %(lower)s-%(upper)s/%(maximum)s; '
                'confidence: %(confidence)s; anomalies: %(anomalies)s (severity %(severity)s).'
            ) % {
                'estimate': audit['score_estimate'],
                'lower': audit['score_lower'],
                'upper': audit['score_upper'],
                'maximum': self._format_sample_scaling_score(audit['target_maximum']),
                'confidence': audit['confidence'],
                'anomalies': audit['anomaly_count'],
                'severity': self._format_sample_scaling_score(audit['anomaly_severity']),
            }))
        if audit.get('review_required'):
            parts.append('<p><strong>%s</strong></p>' % escape(_(
                'The final AI score was invalid after one correction attempt. The allocated estimate was used; human review is required.'
            )))
        if audit.get('fallback_reason'):
            parts.append('<p><strong>%s</strong> %s</p>' % (
                escape(_('Sample comparison fallback:')),
                escape(audit['fallback_reason']),
            ))
        final_mark = self._build_sample_comparison_final_note_html({
            'score': audit.get('final_score'),
            'sample_comparison_audit': audit,
            'score_comment': audit.get('final_reason'),
            'feedback_html': audit.get('final_feedback'),
        })
        if final_mark:
            parts.append(str(final_mark))
        return Markup(''.join(parts))

    def _post_sample_comparison_audit_note(self, result):
        self.ensure_one()
        body = result.get('sample_comparison_audit_html')
        if body:
            self.with_context(**{_SKIP_CHANNEL_FORWARD_CTX: True}).message_post(
                body=body,
                subtype_xmlid='mail.mt_note',
            )
        if result.get('sample_comparison_audit', {}).get('review_required'):
            self._schedule_sample_comparison_review_activity()

    def _schedule_sample_comparison_review_activity(self):
        self.ensure_one()
        users = self.env['res.users']
        if self._name == 'aps.resource.submission':
            for teacher in self.review_requested_by:
                if teacher.partner_id:
                    users |= self.env['res.users'].search([('partner_id', '=', teacher.partner_id.id)], limit=1)
            if not users and self.assigned_by and self.assigned_by.partner_id:
                users |= self.env['res.users'].search([('partner_id', '=', self.assigned_by.partner_id.id)], limit=1)
        if not users:
            manager_group = self.env.ref('aps_sis.group_aps_manager', raise_if_not_found=False)
            users = manager_group.users if manager_group else users
        for user in users:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=_('Review AI sample-comparison mark'),
                note=_('The final AI score remained outside its comparison range after a correction attempt. Review the score and comparison evidence in chatter.'),
                date_deadline=fields.Date.today(),
            )

    def _persist_sample_comparison_evidence(self, evidence, ai_run=None):
        self.ensure_one()
        resource = self._get_ai_feedback_resource()
        model_field = 'submission_id' if self._name == 'aps.resource.submission' else 'resource_id'
        link_vals = {model_field: self.id}
        for item in evidence:
            vals = {
                **link_vals,
                'run_id': ai_run.id if ai_run else False,
                'benchmark_resource_id': item.get('benchmark_resource_id') or False,
                'benchmark_name': item.get('benchmark_name') or False,
                'model_name': item.get('model_name') or False,
                'official_score': item.get('official_score') or 0.0,
                'benchmark_maximum': item.get('maximum') or 0.0,
                'result': (item.get('result') or '').casefold() if item.get('result') else False,
                'fitted_result': (item.get('predicted_result') or '').casefold() if item.get('predicted_result') else False,
                'status': item.get('status') or 'invalid',
                'reason': item.get('reason') or False,
                'raw_response': item.get('raw_response') or False,
                'model_id': item.get('model_id') or False,
                'prompt_tokens': item.get('prompt_tokens') or 0,
                'completion_tokens': item.get('completion_tokens') or 0,
                'estimated_cost': item.get('estimated_cost') or 0.0,
                'anomaly': bool(item.get('anomaly')),
                'anomaly_severity': float(item.get('anomaly_severity') or 0.0),
                'prompt_name': SAMPLE_COMPARISON_PROMPT_NAME,
                'compared_at': item.get('compared_at') or fields.Datetime.now(),
            }
            record = self.env['aps.ai.sample.comparison'].sudo().create(vals)
            item['record_id'] = record.id

    def _generate_sample_comparison_feedback(self, ai_run=None):
        self.ensure_one()
        resource = self._get_ai_feedback_resource()
        strategy_prompt = self._get_sample_comparison_prompt()
        if not strategy_prompt:
            return False

        target_context = self._build_ai_feedback_ctx(include_reasoning=bool(ai_run))
        target_maximum = float(target_context.get('out_of_marks') or 0.0)
        special_prompts = self.env['ai_prompts'].browse()
        if self._get_sample_scaling_prompt():
            special_prompts |= self._get_sample_scaling_prompt()
        prompt_conflict = bool(special_prompts)
        sample_specs = []
        evidence = []
        for sample in self._get_sample_comparison_benchmarks(resource):
            maximum = float(sample.marks or 0.0)
            official_score = float(sample.weight or 0.0)
            answer_text = sample.notes or ''
            sample_entry = {
                'benchmark_resource_id': sample.id,
                'benchmark_name': sample.display_name or sample.name or _('Sample'),
                'official_score': official_score,
                'maximum': maximum,
                'result': False,
                'status': 'invalid',
                'anomaly': False,
                'anomaly_severity': 0.0,
                'compared_at': fields.Datetime.now(),
            }
            if not html2plaintext(answer_text).strip():
                sample_entry['reason'] = _('The sample Notes field is empty.')
            elif maximum <= 0 or official_score < 0 or official_score > maximum or target_maximum <= 0:
                sample_entry['reason'] = _('The official sample mark or maximum mark is invalid.')
            else:
                comparison_context = self._build_sample_comparison_context(
                    target_context,
                    strategy_prompt,
                    answer_text,
                    sample.display_name or sample.name or _('Sample'),
                )
                sample_specs.append({
                    'resource': sample,
                    'name': sample_entry['benchmark_name'],
                    'answer_text': answer_text,
                    'maximum': maximum,
                    'official_score': official_score,
                    'target_score': official_score / maximum * target_maximum,
                    'context': comparison_context,
                    'evidence': sample_entry,
                })
            evidence.append(sample_entry)

        audit = {
            'comparisons': evidence,
            'prompt_conflict': prompt_conflict,
            'target_maximum': target_maximum,
            'score_lower': None,
            'score_upper': None,
            'score_estimate': None,
            'confidence': 'LOW',
            'anomaly_count': 0,
            'anomaly_severity': 0.0,
            'review_required': False,
        }
        if not sample_specs or target_maximum <= 0:
            audit['fallback_reason'] = _('No valid benchmark samples or target maximum mark was available.')
            self._persist_sample_comparison_evidence(evidence, ai_run=ai_run)
            audit['summary'] = _('The ordinary AI marking path was used because no usable comparison range could be calculated.')
            return self._generate_sample_comparison_fallback(target_context, ai_run, audit)

        ai_model_service = self.env['aps.ai.model']
        all_contexts = [spec['context'] for spec in sample_specs] + [target_context]
        model = self._get_sample_comparison_model(ai_model_service, resource, all_contexts, ai_run)
        usable_comparisons = []
        calls = []
        for spec in sample_specs:
            entry = spec['evidence']
            entry['model_id'] = model.id
            entry['model_name'] = model.display_name
            try:
                call_result = model.with_context(ai_dry_run=False).generate_feedback(
                    self,
                    ai_run=ai_run,
                    feedback_context=spec['context'],
                )
                calls.append(call_result)
                entry.update({
                    'raw_response': call_result.get('raw_content') or '',
                    'model_id': call_result.get('model_id') or model.id,
                    'model_name': call_result.get('model_name') or model.display_name,
                    'prompt_tokens': call_result.get('prompt_tokens') or 0,
                    'completion_tokens': call_result.get('completion_tokens') or 0,
                    'estimated_cost': call_result.get('estimated_cost') or 0.0,
                    'compared_at': fields.Datetime.now(),
                })
                parsed = model._parse_structured_response(call_result.get('raw_content') or '')
                classification = parsed.get('result') if isinstance(parsed, dict) else False
                if not isinstance(classification, str) or classification.strip().upper() not in ('BETTER', 'SAME', 'WORSE'):
                    entry.update({
                        'status': 'invalid',
                        'reason': _('The comparison response was malformed or did not contain BETTER, SAME, or WORSE.'),
                    })
                    continue
                reason = parsed.get('reason')
                if not isinstance(reason, str):
                    reason = _('No explanation returned.')
                entry.update({'result': classification.strip().upper(), 'status': 'complete', 'reason': reason})
                usable_comparisons.append({
                    'benchmark_id': spec['resource'].id,
                    'benchmark_name': spec['name'],
                    'benchmark_score': spec['target_score'],
                    'result': entry['result'],
                    'reason': reason,
                    'status': 'complete',
                    'official_score': spec['official_score'],
                    'maximum': spec['maximum'],
                })
            except Exception as exc:
                entry.update({'status': 'error', 'reason': str(exc) or _('The comparison call failed.')})

        if not usable_comparisons:
            audit['fallback_reason'] = _('No valid pairwise comparison response was returned.')
            self._persist_sample_comparison_evidence(evidence, ai_run=ai_run)
            audit['summary'] = _('The ordinary AI marking path was used because all pairwise comparisons failed validation.')
            return self._generate_sample_comparison_fallback(target_context, ai_run, audit)

        for item in usable_comparisons:
            item['benchmark_score'] = float(item['benchmark_score'])
        calibration = self.calculate_score_range(usable_comparisons, target_maximum)
        if len(usable_comparisons) < len(sample_specs) and calibration['confidence'] == 'HIGH':
            calibration['confidence'] = 'MEDIUM'
        evidence_by_id = {item['benchmark_resource_id']: item for item in evidence}
        for fitted in calibration['comparisons']:
            source = evidence_by_id.get(fitted.get('benchmark_id'))
            if source:
                source.update({
                    'anomaly': bool(fitted.get('anomaly')),
                    'anomaly_severity': float(fitted.get('anomaly_severity') or 0.0),
                    'predicted_result': fitted.get('predicted_result'),
                })
        audit.update({
            'score_lower': calibration['score_lower'],
            'score_upper': calibration['score_upper'],
            'score_estimate': calibration['score_estimate'],
            'confidence': calibration['confidence'],
            'anomaly_count': calibration['anomaly_count'],
            'anomaly_severity': calibration['anomaly_severity'],
        })
        self._persist_sample_comparison_evidence(evidence, ai_run=ai_run)

        final_context = self._build_sample_comparison_final_context(
            target_context,
            strategy_prompt,
            sample_specs,
            calibration,
        )
        final_result = False
        review_required = False
        lower, upper = calibration['score_lower'], calibration['score_upper']
        for attempt in range(2):
            if attempt:
                final_context = dict(final_context)
                final_context['score_guidance'] += '\n' + (_(
                    'CORRECTION REQUIRED: your previous score was outside the allowed range. Return a score '
                    'within %(lower)s-%(upper)s, inclusive. Do not return a score outside these bounds.'
                ) % {'lower': lower, 'upper': upper})
            final_result = model.with_context(ai_dry_run=False).generate_feedback(
                self,
                ai_run=ai_run,
                feedback_context=final_context,
            )
            calls.append(final_result)
            score = final_result.get('score')
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                numeric_score = None
            if (
                numeric_score is not None
                and numeric_score.is_integer()
                and lower <= numeric_score <= upper
                and final_result.get('feedback_html')
            ):
                final_result['score'] = numeric_score
                audit['final_reason'] = final_result['score_comment'] or ''
                audit['final_feedback'] = final_result.get('feedback_html') or ''
                audit['final_confidence'] = calibration['confidence']
                break
            numeric_score = None
        else:
            review_required = True
            final_result = dict(final_result or {})
            final_result['score'] = calibration['score_estimate']
            if not final_result.get('feedback_html'):
                final_result['feedback_html'] = '<p>%s</p>' % escape(_(
                    'The AI score did not remain within the comparison range after correction. Please review the comparison evidence and final mark.'
                ))
            final_result['score_comment'] = _('The allocated comparison estimate was used pending human review.')
            audit['final_reason'] = final_result['score_comment']
            audit['final_feedback'] = final_result['feedback_html']
            audit['final_confidence'] = 'LOW'

        audit['review_required'] = review_required
        audit['summary'] = _('Student answer (Answer 1) compared against %(count)s benchmark answers (Answer 2).') % {
            'count': sum(1 for item in evidence if item.get('status') == 'complete'),
        }
        audit['comparisons'] = evidence
        final_result = dict(final_result or {})
        final_result['score'] = max(0.0, min(float(final_result.get('score') or 0.0), target_maximum))
        audit['final_score'] = final_result['score']
        audit['final_reason'] = audit.get('final_reason') or final_result.get('score_comment') or ''
        audit['final_feedback'] = audit.get('final_feedback') or final_result.get('feedback_html') or ''
        audit['final_confidence'] = audit.get('final_confidence') or calibration['confidence']
        final_result['sample_comparison_status'] = 'review' if review_required else 'applied'
        final_result['sample_comparison_audit'] = audit
        final_result['sample_comparison_audit_html'] = self._build_sample_comparison_audit_html(audit)
        final_result['model_id'] = model.id
        final_result['model_name'] = model.display_name
        final_result['prompt_tokens'] = sum(call.get('prompt_tokens') or 0 for call in calls)
        final_result['completion_tokens'] = sum(call.get('completion_tokens') or 0 for call in calls)
        final_result['estimated_cost'] = sum(call.get('estimated_cost') or 0.0 for call in calls)
        final_result['raw_content'] = '\n--- SAMPLE COMPARISON / FINAL MARK ---\n'.join(
            call.get('raw_content') or '' for call in calls
        )
        return final_result

    def _generate_sample_comparison_fallback(self, target_context, ai_run, audit):
        resource = self._get_ai_feedback_resource()
        fallback_context = dict(target_context)
        fallback_context.update({
            'prompt_ids': resource.ai_active_prompts.filtered(
                lambda prompt: (prompt.prompt_name or '').strip().casefold() not in (
                    SAMPLE_SCALING_PROMPT_NAME,
                    SAMPLE_COMPARISON_PROMPT_NAME,
                )
            ),
        })
        fallback_context['image_prompt_names'] = fallback_context['prompt_ids'].mapped('prompt_name')
        ai_model = (
            ai_run.override_model_id
            if ai_run and ai_run.override_model_id
            else self.env['aps.ai.model']
        )
        result = ai_model.generate_feedback(
            self,
            ai_run=ai_run,
            feedback_context=fallback_context,
        )
        result = dict(result)
        audit['final_score'] = result.get('score')
        audit['final_reason'] = result.get('score_comment') or ''
        audit['final_feedback'] = result.get('feedback_html') or ''
        audit['final_confidence'] = _('Not calibrated')
        result['sample_comparison_audit'] = audit
        result['sample_comparison_audit_html'] = self._build_sample_comparison_audit_html(audit)
        result['prompt_tokens'] = (result.get('prompt_tokens') or 0) + sum(
            item.get('prompt_tokens') or 0 for item in audit.get('comparisons') or []
        )
        result['completion_tokens'] = (result.get('completion_tokens') or 0) + sum(
            item.get('completion_tokens') or 0 for item in audit.get('comparisons') or []
        )
        result['estimated_cost'] = (result.get('estimated_cost') or 0.0) + sum(
            item.get('estimated_cost') or 0.0 for item in audit.get('comparisons') or []
        )
        result['prompt_tokens'] = (result.get('prompt_tokens') or 0) + sum(
            item.get('prompt_tokens') or 0 for item in audit.get('comparisons') or []
        )
        result['completion_tokens'] = (result.get('completion_tokens') or 0) + sum(
            item.get('completion_tokens') or 0 for item in audit.get('comparisons') or []
        )
        result['estimated_cost'] = (result.get('estimated_cost') or 0.0) + sum(
            item.get('estimated_cost') or 0.0 for item in audit.get('comparisons') or []
        )
        result['raw_content'] = (result.get('raw_content') or '') + '\n--- SAMPLE COMPARISON AUDIT ---\n' + json.dumps(
            audit, ensure_ascii=False, default=str,
        )
        return result

    def _build_sample_comparison_final_note_html(self, result):
        audit = result.get('sample_comparison_audit') or {}
        score = result.get('score')
        maximum = audit.get('target_maximum') or 0
        confidence = audit.get('final_confidence') or (
            _('Not calibrated') if audit.get('fallback_reason') else audit.get('confidence') or 'LOW'
        )
        reason = audit.get('final_reason') or result.get('score_comment') or ''
        parts = ['<p><strong>%s</strong></p>' % escape(_('AI FINAL MARK'))]
        parts.append('<p>%s</p>' % escape(_('Score: %s/%s') % (
            self._format_sample_scaling_score(score or 0),
            self._format_sample_scaling_score(maximum),
        )))
        if audit.get('score_lower') is not None:
            parts.append('<p>%s</p>' % escape(_('Range: %s-%s/%s') % (
                audit['score_lower'], audit['score_upper'],
                self._format_sample_scaling_score(maximum),
            )))
        elif audit.get('fallback_reason'):
            parts.append('<p><strong>%s</strong> %s</p>' % (
                escape(_('Comparison fallback:')),
                escape(audit['fallback_reason']),
            ))
        parts.append('<p>%s %s</p>' % (escape(_('Confidence:')), escape(confidence)))
        if reason:
            parts.append('<p><strong>%s</strong><br/>%s</p>' % (escape(_('Reason:')), escape(reason)))
        if audit.get('review_required'):
            parts.append('<p><strong>%s</strong></p>' % escape(_('Human review required; the estimate was used after an invalid final score.')))
        return Markup(''.join(parts))

    def _build_sample_feedback_context(self, sample, target_context, marking_prompts, include_reasoning):
        sample_context = sample._build_ai_feedback_ctx(include_reasoning=include_reasoning)
        sample_answer = sample.notes or ''
        sample_instructions = sample.ai_instructions or target_context.get('instructions') or ''
        sample_model_answer = sample.answer or target_context.get('model_answer') or ''
        sample_question = sample.question or target_context.get('question') or ''
        sample_context.update({
            'instructions': sample_instructions,
            'out_of_marks': sample.marks,
            'use_question': bool(sample_question and (
                sample.question or target_context.get('use_question')
            )),
            'question': sample_question,
            'use_model_answer': bool(sample_model_answer and (
                sample.answer or target_context.get('use_model_answer')
            )),
            'model_answer': sample_model_answer,
            'use_note': False,
            'notes': '',
            'student_answer_html': sample_answer,
            'prompt_ids': marking_prompts,
            'image_prompt_names': marking_prompts.mapped('prompt_name'),
            'image_sources': {
                'student_answer': sample_answer,
                'question': sample_question,
                'model_answer': sample_model_answer,
                'instructions': sample_instructions,
                'notes': '',
            },
        })
        return sample_context

    @staticmethod
    def _sample_score_ratio(score, maximum):
        return float(score) / float(maximum) if maximum else 0.0

    @staticmethod
    def _normalize_sample_rubric(text):
        return ' '.join(html2plaintext(text or '').casefold().split())

    def _get_sample_rubric_compatibility_error(self, samples, target_context):
        rubric_fields = (
            ('instructions', _('marking instructions')),
            ('model_answer', _('model answer/rubric')),
        )
        for sample in samples:
            sample_context = sample['context']
            for field_name, label in rubric_fields:
                target_text = self._normalize_sample_rubric(target_context.get(field_name))
                sample_text = self._normalize_sample_rubric(sample_context.get(field_name))
                if not target_text or not sample_text:
                    continue
                similarity = SequenceMatcher(None, target_text, sample_text).ratio()
                if similarity < SAMPLE_RUBRIC_SIMILARITY_THRESHOLD:
                    return _(
                        'Sample "%(sample)s" has materially different %(rubric)s; sample scaling was skipped.'
                    ) % {'sample': sample['name'], 'rubric': label}
        return False

    @staticmethod
    def _parse_sample_scaling_results_table_total(table):
        if not isinstance(table, str) or not table.strip():
            return None

        rows = []
        for line in table.splitlines():
            line = line.strip()
            if not line.startswith('|') or not line.endswith('|'):
                continue
            cells = [cell.strip() for cell in line[1:-1].split('|')]
            if cells and all(re.fullmatch(r':?-{3,}:?', cell.replace(' ', '')) for cell in cells):
                continue
            rows.append(cells)
        if len(rows) < 2:
            return None

        headers = [html2plaintext(cell).strip().casefold() for cell in rows[0]]
        mark_columns = [
            index for index, header in enumerate(headers)
            if any(token in header for token in ('mark', 'score', 'point'))
            or re.search(r'\bao\s*\d+\b', header)
        ]
        if not mark_columns:
            return None

        data_rows = [row for row in rows[1:] if len(row) == len(headers)]
        if not data_rows:
            return None

        total_rows = [
            row for row in data_rows
            if any(
                'total' in html2plaintext(cell).casefold()
                for index, cell in enumerate(row)
                if index not in mark_columns
            )
        ]
        rows_to_sum = total_rows[-1:] if total_rows else data_rows
        total = 0.0
        for row in rows_to_sum:
            for index in mark_columns:
                cell = html2plaintext(row[index]).strip()
                if not cell or cell.casefold() in ('-', '\u2014', 'n/a'):
                    continue
                match = re.search(r'(?<![\w.])-?\d+(?:[.,]\d+)?', cell)
                if not match:
                    return None
                total += float(match.group(0).replace(',', '.'))
        return total

    @staticmethod
    def _sample_scaling_requires_results_table(context):
        prompts = context.get('prompt_ids')
        return bool(prompts and prompts.filtered(lambda prompt: prompt.message_section == 'results_table'))

    def _get_sample_scaling_rank_error(self, samples):
        for index, first in enumerate(samples):
            first_official = self._sample_score_ratio(first['official_score'], first['maximum'])
            first_ai = self._sample_score_ratio(first['ai_score'], first['maximum'])
            for second in samples[index + 1:]:
                second_official = self._sample_score_ratio(second['official_score'], second['maximum'])
                if abs(first_official - second_official) <= 1e-9:
                    continue
                second_ai = self._sample_score_ratio(second['ai_score'], second['maximum'])
                if (first_official - second_official) * (first_ai - second_ai) <= 0:
                    return _(
                        'The AI ranked sample answers differently from their official scores; '
                        'sample scaling was skipped.'
                    )
        return False

    def _select_sample_scaling_anchors(self, samples):
        """Keep the largest correctly ordered subset, preferring accurate anchors."""
        indexed_samples = list(enumerate(samples))
        for subset_size in range(len(indexed_samples), 1, -1):
            valid_subsets = []
            for subset in combinations(indexed_samples, subset_size):
                subset_samples = [sample for _index, sample in subset]
                if self._get_sample_scaling_rank_error(subset_samples):
                    continue
                deviation = sum(
                    abs(
                        self._sample_score_ratio(sample['ai_score'], sample['maximum'])
                        - self._sample_score_ratio(sample['official_score'], sample['maximum'])
                    )
                    for sample in subset_samples
                )
                valid_subsets.append((deviation, tuple(index for index, _sample in subset), subset_samples))
            if valid_subsets:
                _deviation, selected_indexes, selected_samples = min(
                    valid_subsets,
                    key=lambda candidate: (candidate[0], candidate[1]),
                )
                excluded_samples = [
                    sample for index, sample in indexed_samples if index not in selected_indexes
                ]
                return selected_samples, excluded_samples
        return [], samples

    def _format_sample_scaling_score(self, value):
        return '%g' % float(value)

    def _build_sample_scaling_audit_html(self, audit):
        self.ensure_one()
        status_labels = {
            'applied': _('Applied'),
            'skipped': _('Skipped'),
            'failed': _('Failed'),
        }
        parts = [
            '<p><strong>%s</strong> %s</p>' % (
                escape(_('Sample scaling:')),
                escape(status_labels.get(audit.get('status'), _('Unknown'))),
            ),
            '<ul>',
        ]
        for sample in audit.get('samples') or []:
            sample_name = escape(sample.get('name') or _('Sample'))
            if sample.get('ai_score') is None:
                detail = escape(sample.get('reason') or _('No AI score was returned.'))
            else:
                detail = _('%(ai)s/%(maximum)s (official %(official)s/%(maximum)s)') % {
                    'ai': self._format_sample_scaling_score(sample['ai_score']),
                    'maximum': self._format_sample_scaling_score(sample['maximum']),
                    'official': self._format_sample_scaling_score(sample['official_score']),
                }
                detail = escape(detail)
                if sample.get('excluded_from_scaling'):
                    detail += ' — %s' % escape(_(
                        'excluded (deviation %(deviation)s percentage points)'
                    ) % {
                        'deviation': self._format_sample_scaling_score(
                            sample['normalized_deviation'] * 100
                        ),
                    })
            parts.append('<li>%s: %s</li>' % (sample_name, detail))

        original_score = audit.get('student_original_score')
        student_maximum = audit.get('student_maximum')
        if original_score is not None and student_maximum:
            if audit.get('scaled_score') is not None:
                student_detail = _('%(original)s/%(maximum)s (scaled %(scaled)s/%(maximum)s)') % {
                    'original': self._format_sample_scaling_score(original_score),
                    'maximum': self._format_sample_scaling_score(student_maximum),
                    'scaled': self._format_sample_scaling_score(audit['scaled_score']),
                }
            else:
                student_detail = _('%(original)s/%(maximum)s (scaling not applied)') % {
                    'original': self._format_sample_scaling_score(original_score),
                    'maximum': self._format_sample_scaling_score(student_maximum),
                }
            parts.append('<li><strong>%s</strong> %s</li>' % (
                escape(_('Student:')),
                escape(student_detail),
            ))
        reason = audit.get('reason')
        if reason:
            parts.append('<li><strong>%s</strong> %s</li>' % (
                escape(_('Reason:')),
                escape(reason),
            ))
        parts.append('</ul>')
        return Markup(''.join(parts))

    def _post_sample_scaling_audit_note(self, result):
        self.ensure_one()
        body = result.get('sample_scaling_audit_html')
        if not body:
            return
        self.with_context(**{_SKIP_CHANNEL_FORWARD_CTX: True}).message_post(
            body=body,
            subtype_xmlid='mail.mt_note',
        )

    def _generate_sample_scaled_feedback(self, ai_run=None):
        self.ensure_one()
        resource = self._get_ai_feedback_resource()
        scaling_prompt = self._get_sample_scaling_prompt()
        if not scaling_prompt:
            return False

        ai_model_service = self.env['aps.ai.model']
        target_context = self._build_ai_feedback_ctx(include_reasoning=bool(ai_run))
        marking_prompts = resource.ai_active_prompts.filtered(
            lambda prompt: (prompt.prompt_name or '').strip().casefold() != SAMPLE_SCALING_PROMPT_NAME
        )
        target_context.update({
            'prompt_ids': marking_prompts,
            'image_prompt_names': marking_prompts.mapped('prompt_name'),
        })

        sample_specs = []
        sample_audit = []
        samples = resource.supporting_resource_ids | resource.child_ids
        for sample in samples:
            maximum = float(sample.marks or 0.0)
            official_score = float(sample.weight or 0.0)
            sample_text = sample.notes or ''
            sample_name = sample.display_name or sample.name or _('Sample')
            if not html2plaintext(sample_text).strip():
                sample_audit.append({
                    'name': sample_name,
                    'reason': _('The sample Notes field is empty.'),
                })
                continue
            if maximum <= 0 or official_score < 0 or official_score > maximum:
                sample_audit.append({
                    'name': sample_name,
                    'reason': _('The official sample mark or maximum mark is invalid.'),
                })
                continue
            sample_specs.append({
                'resource': sample,
                'name': sample_name,
                'maximum': maximum,
                'official_score': official_score,
                'context': self._build_sample_feedback_context(
                    sample,
                    target_context,
                    marking_prompts,
                    bool(ai_run),
                ),
            })

        contexts = [target_context] + [spec['context'] for spec in sample_specs]
        requires_vision = any(
            ai_model_service._feedback_context_requires_vision(context)
            for context in contexts
        )
        candidates = ai_model_service._get_generation_candidates(
            resource=resource,
            require_vision=requires_vision,
        )
        if not candidates:
            raise UserError(_('No enabled AI model can process this sample-scaling request.'))
        pinned_model = candidates[:1]

        calls = []
        scored_samples = []
        for spec in sample_specs:
            try:
                result = pinned_model.with_context(ai_dry_run=False).generate_feedback(
                    self,
                    ai_run=ai_run,
                    feedback_context=spec['context'],
                )
                calls.append(result)
                score = result.get('score')
                if score is None or not 0 <= float(score) <= spec['maximum']:
                    raise ValueError(_('The AI did not return a valid score for this sample.'))
                spec.update({'ai_score': float(score), 'result': result})
                scored_samples.append(spec)
                audit_entry = {
                    'name': spec['name'],
                    'ai_score': float(score),
                    'official_score': spec['official_score'],
                    'maximum': spec['maximum'],
                }
                spec['audit_entry'] = audit_entry
                sample_audit.append(audit_entry)
            except Exception as exc:
                sample_audit.append({
                    'name': spec['name'],
                    'reason': str(exc) or _('The sample could not be marked.'),
                })

        student_result = pinned_model.with_context(ai_dry_run=False).generate_feedback(
            self,
            ai_run=ai_run,
            feedback_context=target_context,
        )
        calls.append(student_result)
        original_score = student_result.get('score')
        student_maximum = float(target_context.get('out_of_marks') or 0.0)

        audit = {
            'status': 'skipped',
            'samples': sample_audit,
            'student_original_score': float(original_score) if original_score is not None else None,
            'student_maximum': student_maximum,
            'scaled_score': None,
        }

        reason = False
        if original_score is None or student_maximum <= 0:
            reason = _('The student answer did not receive a usable original AI score.')
        elif len(scored_samples) < 2:
            reason = _('At least two valid, independently marked samples are required.')
        else:
            selected_samples, excluded_samples = self._select_sample_scaling_anchors(scored_samples)
            for sample in excluded_samples:
                deviation = abs(
                    self._sample_score_ratio(sample['ai_score'], sample['maximum'])
                    - self._sample_score_ratio(sample['official_score'], sample['maximum'])
                )
                sample['audit_entry'].update({
                    'excluded_from_scaling': True,
                    'normalized_deviation': deviation,
                })
            if len(selected_samples) < 2:
                reason = _(
                    'Fewer than two correctly ordered sample answers remain after excluding outliers.'
                )
            else:
                scored_samples = selected_samples

        if reason:
            audit['reason'] = reason
            result = student_result
        else:
            scale_notes = [
                _(
                    'Use the target resource rubric to assess the student response. Use the independently '
                    'marked samples to estimate a calibrated score on the target maximum-mark scale. Do '
                    'not reject calibration solely because sample rubric text differs; if the supplied '
                    'scores do not support a defensible calibration, return a null score and explain why.'
                ),
            ]
            for spec in scored_samples:
                sample_context = spec['context']
                sample_rubric = '\n'.join(filter(None, [
                    html2plaintext(sample_context.get('instructions') or '').strip(),
                    html2plaintext(sample_context.get('model_answer') or '').strip(),
                ]))
                scale_notes.append(
                    _(
                        'Sample %(name)s: AI mark %(ai)s/%(maximum)s; official mark '
                        '%(official)s/%(maximum)s. Sample rubric: %(rubric)s'
                    ) % {
                        'name': spec['name'],
                        'ai': self._format_sample_scaling_score(spec['ai_score']),
                        'maximum': self._format_sample_scaling_score(spec['maximum']),
                        'official': self._format_sample_scaling_score(spec['official_score']),
                        'rubric': sample_rubric or _('Use the target resource rubric.'),
                    }
                )
            scale_context = dict(target_context)
            scale_context.update({
                'instructions': (target_context.get('instructions') or '') + '\n\n' + scale_notes[0],
                'use_note': True,
                'notes': '\n\n'.join(scale_notes[1:]),
                'prompt_ids': scaling_prompt,
                'image_prompt_names': scaling_prompt.mapped('prompt_name'),
            })
            try:
                scaling_result = pinned_model.with_context(ai_dry_run=False).generate_feedback(
                    self,
                    ai_run=ai_run,
                    feedback_context=scale_context,
                )
                calls.append(scaling_result)
                scaled_score = scaling_result.get('score')
                if scaled_score is None:
                    raise ValueError(
                        scaling_result.get('score_comment') or _('The calibration prompt returned no score.')
                    )
                scaled_score = round(max(0.0, min(float(scaled_score), student_maximum)), 2)

                final_context = dict(target_context)
                final_instructions = final_context.get('instructions') or ''
                final_instructions += (
                    '\n\n%s' % _(
                        'The calibrated total mark is %(score)s out of %(maximum)s. Treat this as the '
                        'required final score. Apply the rubric normally and ensure any criterion or '
                        'Table of Results marks add up to this total.'
                    ) % {
                        'score': self._format_sample_scaling_score(scaled_score),
                        'maximum': self._format_sample_scaling_score(student_maximum),
                    }
                )
                final_context['instructions'] = final_instructions
                final_result = pinned_model.with_context(ai_dry_run=False).generate_feedback(
                    self,
                    ai_run=ai_run,
                    feedback_context=final_context,
                )
                calls.append(final_result)
                final_score = final_result.get('score')
                if final_score is None or abs(float(final_score) - scaled_score) > 0.01:
                    raise ValueError(_(
                        'The final rubric pass did not reconcile to the calibrated total; '
                        'the original AI mark was retained.'
                    ))

                parsed_final = pinned_model._parse_structured_response(final_result.get('raw_content') or '')
                results_table = parsed_final.get('results_table') if isinstance(parsed_final, dict) else None
                table_total = self._parse_sample_scaling_results_table_total(results_table)
                if self._sample_scaling_requires_results_table(final_context) and table_total is None:
                    raise ValueError(_(
                        'The final rubric pass did not return a checkable Results Table; '
                        'the original AI mark was retained.'
                    ))
                if table_total is not None and abs(table_total - scaled_score) > 0.01:
                    raise ValueError(_(
                        'The final Results Table totals %(table)s, not the calibrated mark %(score)s; '
                        'the original AI mark was retained.'
                    ) % {
                        'table': self._format_sample_scaling_score(table_total),
                        'score': self._format_sample_scaling_score(scaled_score),
                    })

                final_result['score'] = scaled_score
                final_result['sample_scaling_status'] = 'applied'
                audit.update({
                    'status': 'applied',
                    'scaled_score': scaled_score,
                })
                result = final_result
            except Exception as exc:
                audit.update({
                    'status': 'failed',
                    'reason': str(exc) or _('Sample scaling failed; the original AI mark was retained.'),
                })
                result = student_result

        result = dict(result)
        result['sample_scaling_audit'] = audit
        result['sample_scaling_audit_html'] = self._build_sample_scaling_audit_html(audit)
        result['model_id'] = pinned_model.id
        result['model_name'] = pinned_model.display_name
        result['prompt_tokens'] = sum(call.get('prompt_tokens') or 0 for call in calls)
        result['completion_tokens'] = sum(call.get('completion_tokens') or 0 for call in calls)
        result['estimated_cost'] = sum(call.get('estimated_cost') or 0.0 for call in calls)
        result['raw_content'] = '\n---\n'.join(call.get('raw_content') or '' for call in calls)
        return result

    def _get_ai_feedback_result_write_vals(self, result):
        self.ensure_one()
        return {
            self._get_ai_feedback_storage_field_name(): result.get('feedback_html') or False,
            'ai_answer_chunks': result.get('answer_chunks') or False,
            'ai_answer_chunked_html': result.get('answer_chunked_html') or False,
            'ai_feedback_items': result.get('feedback_items') or False,
            'ai_feedback_links': result.get('feedback_links') or False,
        }

    def _is_no_detailed_feedback_html(self, feedback_html):
        """Return True when *feedback_html* is empty or the standard placeholder.

        ``aps_ai`` emits ``NO_DETAILED_FEEDBACK_HTML`` whenever no structured
        feedback sections could be assembled from the AI response, so callers
        can detect that case and substitute more meaningful content (e.g. the
        score comment).
        """
        text = (feedback_html or '').strip()
        return not text or text == NO_DETAILED_FEEDBACK_HTML

    # -------------------------------------------------------------------------
    # Shared AI run notification helpers
    # -------------------------------------------------------------------------

    def _get_ai_run_link_field(self):
        """Return the ``aps.ai.run`` field name that links a run to this record.

        Override in concrete models: ``'resource_id'`` for ``aps.resources``,
        ``'submission_id'`` for ``aps.resource.submission``.
        """
        raise NotImplementedError('_get_ai_run_link_field must be implemented by the concrete model')

    def _build_ai_run_notification(self, run, title, message, notification_type='info'):
        """Return a display_notification action for an AI background run."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'run_id': run.id,
            }
        }

    def _build_ai_failure_notification(self, error_text):
        """Return a sticky warning display_notification for a failed AI call."""
        message = error_text or _('The AI call failed.')
        normalized_message = message.lower()
        if 'empty completion' in normalized_message or 'did not return the final answer' in normalized_message:
            message = _(
                '%s\n\nIf AI > Logs only shows connection tests, clear that filter or apply the Submission Feedback filter.'
            ) % message
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Marking Failed'),
                'message': message,
                'type': 'warning',
                'sticky': True,
            }
        }