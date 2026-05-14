"""Shared constants and helper methods for AI feedback payload assembly.

Both the generic (non-targeted) and targeted feedback pipelines use the
constants and model methods defined here.  Import from here rather than
duplicating values in ai_answer_generic.py or ai_answer_targeted.py.
"""
import json
import logging
import re
from html import escape

from odoo import _, api, models
from odoo.exceptions import UserError

try:
    import markdown as _md_lib
    _MARKDOWN_AVAILABLE = True
except ImportError:
    _MARKDOWN_AVAILABLE = False

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical section order  (matches message_section selection values)
# ---------------------------------------------------------------------------
PROMPT_SECTION_ORDER = [
    'system',              # → system message, not a user content block
    'ai_instructions',
    'maximum_mark',
    'question',
    'model_answer',
    'notes',
    'detailed_feedback',   # targeted-only: prior-phase context
    'additional_context',
    'opening_summary',     # generic: brief performance overview
    'detailed_analysis',   # generic: point-by-point assessment
    'results_table',       # generic: criteria / mark table
    'student_answer',
    'response_format',
]

# Display name for each section key.
# Used for tag matching in the targeted pipeline and for prompt_names_used lists.
SECTION_DISPLAY_NAMES = {
    'system':             'System',
    'ai_instructions':    'Specific Instructions',
    'maximum_mark':       'Maximum Mark',
    'question':           'Question',
    'model_answer':       'Model Answer',
    'notes':              'Notes',
    'detailed_feedback':  'Detailed Feedback',
    'additional_context': 'Additional Context',
    'opening_summary':    'Opening Summary',
    'detailed_analysis':  'Detailed Analysis',
    'results_table':      'Results Table',
    'student_answer':     'Student Answer',
    'response_format':    'Response Format',
}

# Heading template for each section.  ``%s`` is replaced with body content.
# 'system' is not used as a user block; its entry is a no-op placeholder.
# response_format heading is baked into the format constant itself.
SECTION_HEADINGS = {
    'system':             '%s',  # not used — handled as the system message
    'ai_instructions':    '## AI Instructions:\n%s',
    'maximum_mark':       '## Maximum Mark:\n%s',
    'question':           '%s',
    'model_answer':       '%s',
    'notes':              '%s',
    'detailed_feedback':  '## Detailed Feedback:\n%s',
    'additional_context': '## Additional Context:\n%s',
    'opening_summary':    '## Opening Summary:\n%s',
    'detailed_analysis':  '## Detailed Analysis:\n%s',
    'results_table':      '## Results Table:\n%s',
    'student_answer':     '%s',
    'response_format':    '%s',  # heading already inside the format constant
}

# ---------------------------------------------------------------------------
# Shared prompt body constants
# ---------------------------------------------------------------------------
PROMPT_MODEL_ANSWER_FALLBACK = 'No model answer provided.'

# Response format for the targeted pipeline.
# Extends the generic format with inline chunk-linked feedback items.
PROMPT_RESPONSE_FORMAT = (
    'Return ONLY valid JSON with these keys:\n'
    '{"opening_summary": string, "detailed_analysis": string, "results_table": string,\n'
    ' "feedback": [{"id": string, "text": string, "type": string, "justification": string}],\n'
    ' "links": [{"feedback_id": string, "chunk_ids": [string]}],\n'
    ' "score": number|null, "score_comment": string|null}.\n'
    'opening_summary: brief plain-text overview of the student\'s performance (Markdown allowed).\n'
    'detailed_analysis: Markdown with headings, bullet points, and bold text for a detailed point-by-point assessment.\n'
    'results_table: Markdown table with columns for each criterion, mark, and justification.\n'
    'feedback: array of inline feedback items with unique ids; type is "positive", "negative", or "neutral".\n'
    'links: each entry maps a feedback id to the chunk ids from the student answer it refers to.\n'
    'If you cannot determine a mark, set score to null and explain why in score_comment.'
)

# Response format for the generic (non-targeted) pipeline — structured Markdown.
# Pass as ``response_format_fallback`` when calling ``_build_payload``.
PROMPT_RESPONSE_FORMAT_GENERIC = (
    'Return ONLY valid JSON with these keys:\n'
    '{"opening_summary": string, "detailed_analysis": string, "results_table": string, '
    '"score": number|null, "score_comment": string|null}.\n'
    'opening_summary must be a brief plain-text overview of the student\'s performance (Markdown allowed).\n'
    'detailed_analysis must use Markdown with headings, bullet points, and bold text for a '
    'detailed point-by-point assessment.\n'
    'results_table must be a Markdown table with columns for each criterion, mark, and justification.\n'
    'If you cannot determine a mark, set score to null and explain why in score_comment.'
)

# Maximum number of model calls when the response content is not parseable JSON.
JSON_PARSE_MAX_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_FEEDBACK = (
    'You are an expert teacher assistant. Follow the supplied instructions exactly, '
    'produce constructive teacher feedback for students, and when possible determine a mark.'
)
SYSTEM_PROMPT_FEEDBACK_NO_REASONING = (
    ' Do not return reasoning, chain-of-thought, or thinking text. Return only the final answer.'
)


class APSAIModelAnswerBase(models.Model):
    """Shared utility methods for AI feedback payload assembly.

    Both APSAIModelAnswerProcessing (generic) and the targeted answer classes
    inherit from this via the aps.ai.model mixin chain.
    """
    _inherit = 'aps.ai.model'

    # -------------------------------------------------------------------------
    # HTML / text helpers
    # -------------------------------------------------------------------------

    def _html_to_text(self, html_value):
        if not html_value:
            return ''
        text = str(html_value)
        text = text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
        for tag in ('</p>', '</div>', '</li>', '</h1>', '</h2>', '</h3>', '</h4>'):
            text = text.replace(tag, '\n')
        text = re.sub(r'<[^>]+>', '', text)
        return text.replace('&nbsp;', ' ').strip()

    def _normalize_feedback_html(self, feedback_html):
        text = (feedback_html or '').strip()
        if not text:
            return '<p>No feedback was returned by the AI model.</p>'
        if '<' in text and '>' in text:
            return text
        paragraphs = [segment.strip() for segment in text.split('\n\n') if segment.strip()]
        if not paragraphs:
            paragraphs = [text]
        return ''.join(
            '<p>%s</p>' % escape(paragraph).replace('\n', '<br/>')
            for paragraph in paragraphs
        )

    # -------------------------------------------------------------------------
    # Response parsing helpers
    # -------------------------------------------------------------------------

    def _parse_structured_response(self, raw_content):
        text = (raw_content or '').strip()
        if text.startswith('```'):
            lines = [line for line in text.splitlines() if not line.strip().startswith('```')]
            text = '\n'.join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def _extract_score(self, parsed, raw_content):
        if isinstance(parsed, dict):
            score = parsed.get('score')
            if score not in (None, ''):
                try:
                    return float(score)
                except (TypeError, ValueError):
                    pass
        return None

    def _extract_score_comment(self, parsed):
        if isinstance(parsed, dict):
            comment = parsed.get('score_comment')
            if comment and isinstance(comment, str):
                return comment.strip()
        return None

    # -------------------------------------------------------------------------
    # Prompt name normalisation (used by targeted pipeline for tag matching)
    # -------------------------------------------------------------------------

    @api.model
    def _normalize_prompt_name(self, prompt_name):
        return re.sub(r'\s+', ' ', (prompt_name or '').strip()).casefold()

    # -------------------------------------------------------------------------
    # Payload metadata helpers (shared by both pipelines)
    # -------------------------------------------------------------------------

    def _build_system_content(self):
        """Return the system message string for this model instance."""
        content = SYSTEM_PROMPT_FEEDBACK
        if self.disable_reasoning:
            content += SYSTEM_PROMPT_FEEDBACK_NO_REASONING
        return content

    def _apply_payload_metadata(self, payload, include_reasoning=False):
        """Attach reasoning and response_format fields to *payload* in-place."""
        if self.disable_reasoning:
            payload['reasoning'] = {'enabled': False, 'exclude': True}
        elif include_reasoning:
            payload['reasoning'] = {'enabled': True, 'exclude': False, 'effort': 'low'}
        if self.force_json_response:
            payload['response_format'] = {'type': 'json_object'}
        return payload

    # -------------------------------------------------------------------------
    # Unified payload builder (used by both generic and targeted pipelines)
    # -------------------------------------------------------------------------

    def _build_dynamic_section_data(self, ctx, student_answer_text=''):
        """Extract dynamic content from *ctx* into a section-keyed dict.

        *ctx* is the standard AI feedback context dict produced by
        ``_build_ai_feedback_ctx``.  *student_answer_text* must already be
        plain text (or pre-formatted JSON for the targeted pipeline).

        Only keys with non-empty content are included in the returned dict.
        """
        data = {}

        instructions = self._html_to_text(ctx.get('instructions', '')).strip()
        if instructions:
            data['ai_instructions'] = instructions

        out_of_marks = str(ctx.get('out_of_marks') or '').strip()
        if out_of_marks:
            data['maximum_mark'] = out_of_marks

        if ctx.get('use_question'):
            q = self._html_to_text(ctx.get('question', '')).strip()
            if q:
                data['question'] = q

        if ctx.get('use_model_answer'):
            ma = self._html_to_text(ctx.get('model_answer', '')).strip() or PROMPT_MODEL_ANSWER_FALLBACK
            data['model_answer'] = ma

        if ctx.get('use_note'):
            notes = self._html_to_text(ctx.get('notes', '')).strip()
            if notes:
                data['notes'] = notes

        if student_answer_text:
            data['student_answer'] = student_answer_text

        return data

    def _build_payload(self, prompt_records, dynamic_section_data, include_reasoning=False,
                       response_format_fallback=None):
        """Build a complete chat payload by merging prompt records with dynamic data.

        For each section in ``PROMPT_SECTION_ORDER``:

        1. Prompt template records whose ``message_section`` matches are emitted
           first (in sequence order), before any dynamic content.
        2. Dynamic content (field values from the submission or resource) follows.
        3. The ``response_format`` section falls back to ``response_format_fallback``
           (or ``PROMPT_RESPONSE_FORMAT`` when not supplied) if neither records
           nor dynamic data provide any content for it.

        The ``system`` section is special: any prompt templates assigned to it
        override the default ``_build_system_content()`` system message instead
        of becoming a user content block.

        Returns ``(payload_dict, prompt_names_used_list)``.
        """
        prompts_by_section = {key: [] for key in PROMPT_SECTION_ORDER}
        names = []

        for prompt in (prompt_records or self.env['ai_prompts'].browse()):
            text = (prompt.prompt or '').strip()
            if not text:
                continue
            sec = (prompt.message_section or 'additional_context')
            if sec not in prompts_by_section:
                sec = 'additional_context'
            prompts_by_section[sec].append((prompt.prompt_name or '', text))

        # 'system' feeds the system message, not a user content block.
        system_prompt_items = prompts_by_section['system']
        if system_prompt_items:
            system_content = '\n\n'.join(t for _, t in system_prompt_items)
            if self.disable_reasoning:
                system_content += SYSTEM_PROMPT_FEEDBACK_NO_REASONING
        else:
            system_content = self._build_system_content()

        sections = []
        _rf_fallback = response_format_fallback if response_format_fallback is not None else PROMPT_RESPONSE_FORMAT

        for section_key in PROMPT_SECTION_ORDER:
            if section_key == 'system':
                continue  # already handled above as the system message

            prompt_items = prompts_by_section[section_key]  # list of (name, text)
            dynamic_text = (dynamic_section_data.get(section_key) or '').strip()

            # Fallback response format when no records or dynamic data cover it.
            if section_key == 'response_format' and not prompt_items and not dynamic_text:
                dynamic_text = _rf_fallback

            if not prompt_items and not dynamic_text:
                continue

            lines = []
            for pname, ptext in prompt_items:
                lines.append(ptext)
                names.append(pname or SECTION_DISPLAY_NAMES[section_key])

            # Inject dynamic text only when no prompt template covers this section
            # (so it acts as a fallback), OR for student_answer where the actual
            # submission text must always follow any template framing.
            if dynamic_text and (not prompt_items or section_key in ['student_answer','model_answer']):
                lines.append(dynamic_text)
                names.append(SECTION_DISPLAY_NAMES[section_key])

            sections.append(SECTION_HEADINGS[section_key] % '\n\n'.join(lines))

        user_messages = [{'role': 'user', 'content': s} for s in sections if s]
        payload = {
            'model': self.model_key,
            'messages': [
                {'role': 'system', 'content': system_content},
            ] + user_messages,
            'temperature': self.temperature,
            'max_completion_tokens': self.max_completion_tokens,
        }
        self._apply_payload_metadata(payload, include_reasoning=include_reasoning)
        return payload, names

    # -------------------------------------------------------------------------
    # Prompt collection helpers (shared by both pipelines)
    # -------------------------------------------------------------------------

    def _collect_applicable_prompts(self, selected_prompts, db_model_name):
        """Return *selected_prompts* sorted by sequence.

        Callers are expected to pass an already-filtered set (e.g.
        ``resource.ai_active_prompts``).  The ``db_model_name`` parameter is
        kept for signature compatibility but is no longer used here.
        """
        self.ensure_one()
        return (selected_prompts or self.env['ai_prompts'].browse()).sorted(
            key=lambda rec: ((rec.sequence or 0), rec.id)
        )

    def _collect_all_applicable_prompts(self, selected_prompts, db_model_name):
        """Full candidate-building used by ``_compute_ai_active_prompts``.

        Merges *selected_prompts* with global always-include prompts, then
        filters to those applicable to this AI model and *db_model_name*.
        Called at compute time; the result is stored as ``ai_active_prompts``.
        """
        self.ensure_one()
        self.env['ai_prompts'].sudo().ensure_default_targeted_feedback_prompt()
        self.env['ai_prompts'].sudo().ensure_default_specific_instructions_prompt()
        selected = (selected_prompts or self.env['ai_prompts'].browse()).filtered(
            lambda rec: rec.enabled and (rec.prompt or rec.prompt_name)
        )
        always = self.env['ai_prompts'].sudo().search([
            ('enabled', '=', True),
            ('always_include', '=', True),
        ])
        applicable = (selected | always).filtered(
            lambda rec: (
                not rec.applies_to_ai_models or self in rec.applies_to_ai_models
            ) and (
                not rec.applies_to_db_models
                or db_model_name in rec.applies_to_db_models.mapped('model')
            )
        )
        return applicable.sorted(key=lambda rec: ((rec.sequence or 0), rec.id))

    # -------------------------------------------------------------------------
    # Markdown → HTML conversion (used by both feedback pipelines)
    # -------------------------------------------------------------------------

    def _markdown_to_html(self, text):
        """Convert a Markdown string to an HTML fragment.

        Uses the ``markdown`` package when available; falls back to
        ``_normalize_feedback_html`` (plain-text → ``<p>`` wrapping) if the
        package is not installed.
        """
        text = (text or '').strip()
        if not text:
            return ''
        if _MARKDOWN_AVAILABLE:
            html = _md_lib.markdown(text, extensions=['tables', 'fenced_code', 'nl2br'])
            html = html.replace('<table>', '<table class="table table-bordered table-sm">')
            return html
        return self._normalize_feedback_html(text)

    def _combine_feedback_parts(self, parsed):
        """Assemble opening_summary, detailed_analysis, and results_table into a single HTML string.

        Falls back to ``_normalize_feedback_html`` when none of the structured
        keys are present (e.g. when the AI returned plain text instead of JSON).
        """
        parts = []
        for key in ('opening_summary', 'detailed_analysis', 'results_table'):
            val = (parsed.get(key) or '').strip() if isinstance(parsed, dict) else ''
            if val:
                parts.append(self._markdown_to_html(val))
        if not parts:
            legacy = (parsed.get('feedback_html') if isinstance(parsed, dict) else None) or ''
            return self._normalize_feedback_html(legacy or None)
        return '\n'.join(parts)

    # -------------------------------------------------------------------------
    # Base (non-targeted) feedback runner
    # -------------------------------------------------------------------------

    def _assemble_feedback_payload(
        self,
        ctx,
        prompts,
        student_answer,
        student_answer_chunks=None,
        prior_phase_context='',
    ):
        """Build a chat payload for either feedback pipeline.

        When *student_answer_chunks* is provided the student answer section is
        replaced with a JSON serialisation of the chunks (targeted path).
        When *prior_phase_context* is provided it is injected as the
        ``detailed_feedback`` section.

        The generic path calls this without the optional arguments and gets
        ``PROMPT_RESPONSE_FORMAT_GENERIC`` as the response format.  The
        targeted path passes chunk data and gets the default
        ``PROMPT_RESPONSE_FORMAT``.
        """
        if student_answer_chunks:
            student_text = json.dumps(student_answer_chunks, indent=2, ensure_ascii=False)
        else:
            student_text = student_answer.strip()

        dynamic_data = self._build_dynamic_section_data(ctx, student_answer_text=student_text)

        if prior_phase_context and prior_phase_context.strip():
            dynamic_data['detailed_feedback'] = prior_phase_context.strip()

        # Use the generic (3-section Markdown) format for non-targeted calls;
        # targeted calls get the default PROMPT_RESPONSE_FORMAT which also
        # includes feedback items and chunk links.
        response_format_fallback = (
            None if student_answer_chunks else PROMPT_RESPONSE_FORMAT_GENERIC
        )
        return self._build_payload(
            prompts,
            dynamic_data,
            include_reasoning=ctx.get('include_reasoning', False),
            response_format_fallback=response_format_fallback,
        )

    def _execute_feedback_call_with_content(self, payload, record, progress_callback, prompt_names_used=None):
        """Execute one AI call and return ``(result_dict, raw_content_text)``.

        Retains the existing one-time retry for reasoning-only truncation where
        the provider returns no final message content.
        """
        result = self._execute_logged_router_call(
            payload,
            request_type='submission_feedback',
            related_record=record,
            stream_callback=progress_callback,
            prompt_names_used=prompt_names_used,
        )
        try:
            raw_content = self._extract_message_content(result['response_json'])
        except Exception as exc:
            self._update_call_log_error(result.get('log_record'), exc)
            if self._is_reasoning_only_truncation(result.get('response_json') or {}):
                retry_payload = dict(payload)
                retry_payload['max_completion_tokens'] = self._get_retry_max_completion_tokens(
                    payload.get('max_completion_tokens')
                )
                retry_result = self._execute_logged_router_call(
                    retry_payload,
                    request_type='submission_feedback',
                    related_record=record,
                    stream_callback=progress_callback,
                    prompt_names_used=prompt_names_used,
                )
                try:
                    result = retry_result
                    raw_content = self._extract_message_content(result['response_json'])
                except Exception as retry_exc:
                    self._update_call_log_error(result.get('log_record'), retry_exc)
                    raise
            else:
                raise
        return result, raw_content

    def _execute_feedback_call_with_json_retries(
        self,
        payload,
        record,
        progress_callback,
        prompt_names_used=None,
        max_attempts=JSON_PARSE_MAX_ATTEMPTS,
    ):
        """Execute AI call(s) until JSON is parseable or attempts are exhausted."""
        parsed = {}
        raw_content = ''
        result = None

        for attempt in range(1, max_attempts + 1):
            result, raw_content = self._execute_feedback_call_with_content(
                payload,
                record,
                progress_callback,
                prompt_names_used=prompt_names_used,
            )
            parsed = self._parse_structured_response(raw_content)
            if parsed:
                if attempt > 1:
                    _logger.info(
                        'AI JSON parse recovered on attempt %s/%s for model %s.',
                        attempt,
                        max_attempts,
                        self.display_name,
                    )
                break

            if attempt < max_attempts:
                _logger.warning(
                    'AI returned invalid/empty JSON (attempt %s/%s) for model %s; retrying.',
                    attempt,
                    max_attempts,
                    self.display_name,
                )

        if not parsed:
            _logger.warning(
                'AI returned invalid/empty JSON after %s attempts for model %s; using fallback handling.',
                max_attempts,
                self.display_name,
            )

        return result, raw_content, parsed

    def _run_feedback_generic(self, ctx, prompts, record, progress_callback):
        """Execute the non-targeted (holistic summary) feedback path."""
        self.ensure_one()
        student_answer = self._html_to_text(ctx.get('student_answer_html', ''))
        if not student_answer.strip():
            raise UserError(ctx.get('empty_answer_error') or _('No student answer provided.'))

        payload, names = self._assemble_feedback_payload(ctx, prompts, student_answer)
        result, raw_content, parsed = self._execute_feedback_call_with_json_retries(
            payload,
            record,
            progress_callback,
            prompt_names_used=names,
        )
        feedback_html = self._combine_feedback_parts(parsed) or self._normalize_feedback_html(raw_content)
        score = self._extract_score(parsed, raw_content)
        score_comment = self._extract_score_comment(parsed)
        return {
            'feedback_html': feedback_html,
            'score': score,
            'score_comment': score_comment,
            'answer_chunks': False,
            'answer_chunked_html': False,
            'feedback_items': False,
            'feedback_links': False,
            'targeted_feedback': False,
            'prompt_tokens': result['prompt_tokens'],
            'completion_tokens': result['completion_tokens'],
            'estimated_cost': result['estimated_cost'],
            'model_id': self.id,
            'model_name': self.display_name,
            'raw_content': raw_content,
        }
