"""Shared constants and helper methods for AI feedback payload assembly.

Both the generic (non-targeted) and targeted feedback pipelines use the
constants and model methods defined here.  Import from here rather than
duplicating values in ai_answer_generic.py or ai_answer_targeted.py.
"""
import json
import logging
import re
from html import escape

from odoo import api, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical section order  (matches message_section selection values)
# ---------------------------------------------------------------------------
PROMPT_SECTION_ORDER = [
    'ai_instructions',
    'maximum_mark',
    'question',
    'model_answer',
    'notes',
    'detailed_feedback',   # targeted-only: prior-phase context
    'additional_context',
    'student_answer',
    'response_format',
]

# Display name for each section key.
# Used for tag matching in the targeted pipeline and for prompt_names_used lists.
SECTION_DISPLAY_NAMES = {
    'ai_instructions':    'Specific Instructions',
    'maximum_mark':       'Maximum Mark',
    'question':           'Question',
    'model_answer':       'Model Answer',
    'notes':              'Notes',
    'detailed_feedback':  'Detailed Feedback',
    'additional_context': 'Additional Context',
    'student_answer':     'Student Answer',
    'response_format':    'Response Format',
}

# Heading template for each section.  ``%s`` is replaced with body content.
# additional_context has no heading.  response_format heading is baked into
# PROMPT_RESPONSE_FORMAT itself.
SECTION_HEADINGS = {
    'ai_instructions':    '# AI INSTRUCTIONS:\n%s',
    'maximum_mark':       '# MAXIMUM MARKS:\n%s',
    'question':           '%s',
    'model_answer':       '%s',
    'notes':              '%s',
    'detailed_feedback':  '# Detailed Feedback:\n%s',
    'additional_context': '# ADDITIONAL CONTEXT\n%s',
    'student_answer':     '%s',
    'response_format':    '%s',  # heading already inside PROMPT_RESPONSE_FORMAT
}

# ---------------------------------------------------------------------------
# Shared prompt body constants
# ---------------------------------------------------------------------------
PROMPT_MODEL_ANSWER_FALLBACK = 'No model answer provided.'

PROMPT_RESPONSE_FORMAT = (
    # '# Response Format:\n'
    'Return ONLY valid JSON with these keys:\n'
    '{"feedback_html": string, "score": number|null, "score_comment": string|null}.\n'
    'feedback_html must be an HTML fragment using tags such as <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.\n'
    'If you cannot determine a mark, set score to null and explain why in score_comment.'
)

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

    def _build_payload(self, prompt_records, dynamic_section_data, include_reasoning=False):
        """Build a complete chat payload by merging prompt records with dynamic data.

        For each section in ``PROMPT_SECTION_ORDER``:

        1. Prompt template records whose ``message_section`` matches are emitted
           first (in sequence order), before any dynamic content.
        2. Dynamic content (field values from the submission or resource) follows.
        3. The ``response_format`` section falls back to ``PROMPT_RESPONSE_FORMAT``
           when neither records nor dynamic data supply any content for it.

        Returns ``(payload_dict, prompt_names_used_list)``.
        """
        prompts_by_section = {key: [] for key in PROMPT_SECTION_ORDER}
        names = []

        for prompt in (prompt_records or self.env['ai_prompts']):
            text = (prompt.prompt or '').strip()
            if not text:
                continue
            sec = (prompt.message_section or 'additional_context')
            if sec not in prompts_by_section:
                sec = 'additional_context'
            prompts_by_section[sec].append((prompt.prompt_name or '', text))

        sections = []

        for section_key in PROMPT_SECTION_ORDER:
            prompt_items = prompts_by_section[section_key]  # list of (name, text)
            dynamic_text = (dynamic_section_data.get(section_key) or '').strip()

            # Fallback response format when no records or dynamic data cover it.
            if section_key == 'response_format' and not prompt_items and not dynamic_text:
                dynamic_text = PROMPT_RESPONSE_FORMAT

            if not prompt_items and not dynamic_text:
                continue

            lines = []
            for pname, ptext in prompt_items:
                lines.append(ptext)
                names.append(pname or SECTION_DISPLAY_NAMES[section_key])

            if dynamic_text:
                lines.append(dynamic_text)
                names.append(SECTION_DISPLAY_NAMES[section_key])

            sections.append(SECTION_HEADINGS[section_key] % '\n\n'.join(lines))

        user_messages = [{'role': 'user', 'content': s} for s in sections if s]
        payload = {
            'model': self.model_key,
            'messages': [
                {'role': 'system', 'content': self._build_system_content()},
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
        return (selected_prompts or self.env['ai_prompts']).sorted(
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
        selected = (selected_prompts or self.env['ai_prompts']).filtered(
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
