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
# Prompt section metadata
# ---------------------------------------------------------------------------
# Prompt block order is sourced at runtime from
# ai_prompts.message_section selection.

# Heading template for each section.  ``%s`` is replaced with body content.
# 'system' is not used as a user block; its entry is a no-op placeholder.
# response_format heading is baked into the format constant itself.
SECTION_HEADINGS = {
    'system':                    '%s',  # not used — handled as the system message
    'maximum_mark':              '<maximum_mark>\n%s</maximum_mark>',
    'model_answer':              '<model_answer>%s</model_answer>',
    'additional_context':        '<additional_context>\n%s</additional_context>',
    'notes':                     '<notes>\n%s</notes>',
    'question':                  '<question>%s</question>',
    'student_answer':            '<student_answer>\n%s</student_answer>',
    'detailed_analysis':         '<detailed_analysis>\n%s</detailed_analysis>',
    'detailed_analysis_format':  None,  # nested inside detailed_analysis as <output_format>
    'results_table':             '<results_table>\n%s</results_table>',
    'results_table_format':      None,  # nested inside results_table as <output_format>
    'targeted_feedback':         '<targeted_feedback>\n%s</targeted_feedback>',
    'score':                     '<score>\n%s</score>',
    'summary':                   '<summary>\n%s</summary>',
    'summary_format':            None,  # nested inside summary as <output_format>
    'output_schema':             '<output_schema>\n%s</output_schema>',
    'other':                     '%s',
    'ai_instructions':           '%s',  # deprecated — kept so old prompt records don't crash
}

# ---------------------------------------------------------------------------
# Shared prompt body constants
# ---------------------------------------------------------------------------
PROMPT_MODEL_ANSWER_FALLBACK = 'No model answer provided.'

# Default results-table format injected when no prompt template covers that section.
_DEFAULT_RESULTS_TABLE_FORMAT = (
    'Produce a markdown table with this format:\n\n'
    '| Criterion | Met? | Marks | Justification |\n'
    '| --------- |:----:|:-----:| ------------- |'
)

_DEFAULT_SECTION_FORMAT = (
    'Use Markdown with bold and italics to highlight key words or phrases. '
    'Use bullets and icons.'
)

# Default rules injected into the targeted_feedback section when no prompt
# template covers it.  Governs JSON structure, data integrity, and chip text.
_TARGETED_FEEDBACK_RULES = (
    'No markdown fences, no commentary, no preface, no trailing text.\n'
    '\n'
    '## JSON rules:\n'
    '- Must parse with standard JSON parser (RFC 8259).\n'
    '- All keys and all string values use double quotes.\n'
    '- Escape internal double quotes as \\\\\"\n'
    '- Use \\n for new lines inside strings.\n'
    '- No trailing commas.\n'
    '- Do not duplicate keys.\n'
    '- Do not nest feedback inside feedback.\n'
    '- Do not output null for required fields.\n'
    '\n'
    '## Data Structuring\n'
    '- feedback.id must be unique.\n'
    '- links.feedback_id must reference an existing feedback.id.\n'
    '- chunk_ids must be an array of strings.\n'
    '- If no feedback items, return "feedback": [] and "links": [].\n'
    '- Do not add any other keys.\n'
    '- Each feedback.text value must be short and suitable for a small clickable chip, ideally 2 to 8 words.\n'
    '- Choose a value for feedback.type from this closed set: ["success", "error", "info"]. '
    'If the value is not in this list, the response is invalid.\n'
    '- Each feedback.justification must be a concise 1\u20132 sentence explanation of why this feedback item was included.\n'
    '- Use ONLY chunk IDs from the supplied Student Answer Chunks. Do NOT invent chunk IDs.\n'
    '- Not every feedback item needs linked chunks.\n'
    '- Never show the chunk IDs or feedback IDs.\n'
    '- Do not use the word \'chunk\'. Instead use \'section\'.\n'
    '- Always try and include one positive feature of the answer with a feedback.type="success".'
)

# Per-key JSON schema fragments used by ``_build_output_schema``.
# Keys must match the canonical AI response keys.
_OUTPUT_SCHEMA_KEY_DESCRIPTIONS = {
    'detailed_analysis': (
        '"detailed_analysis": "string — Markdown with headings, text, and bullet points '
        'for a detailed point-by-point assessment"'
    ),
    'results_table': (
        '"results_table": "string — A heading with a markdown table with columns for criterion, mark, '
        'and justification"'
    ),
    'summary': (
        '"summary": "string — brief Markdown overview of the student\'s performance with headings and key points highlighted in bold or italics"'
    ),
    'score': '"score": number|null',
    'score_comment': (
        '"score_comment": "string|null — brief explanation of the score, '
        'or why it could not be determined"'
    ),
    'feedback': (
        '"feedback": [{"id": "f1", "text": "string", '
        '"type": "success|info|error|warning", "justification": "string"}]'
    ),
    'links': (
        '"links": [{"feedback_id": "f1", "chunk_ids": ["c1", "c2"]}]'
    ),
}

# Maps each prompt section key to the JSON output key(s) it contributes.
# Iteration order follows SECTION_HEADINGS, so the output schema key list is
# always derived from that declaration order rather than being hardcoded.
# 'score' is special: it is gated on out_of_marks, not on section presence.
_SECTION_TO_OUTPUT_KEYS = {
    'detailed_analysis':  ['detailed_analysis'],
    'results_table':      ['results_table'],
    'targeted_feedback':  ['feedback', 'links'],
    'score':              ['score', 'score_comment'],
    'summary':            ['summary'],
}

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
    f'{SYSTEM_PROMPT_FEEDBACK} Do not return reasoning, chain-of-thought, or thinking text.'
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
            return '<p><em>No detailed feedback was returned by the AI model.</em></p>'
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
            data['additional_context'] = instructions

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

    @api.model
    def _get_prompt_section_order(self):
        """Return prompt section order from ai_prompts.message_section selection."""
        selection = self.env['ai_prompts']._fields['message_section'].selection or []
        return [key for key, _label in selection]

    @api.model
    def _get_prompt_section_labels(self):
        """Return display labels for section keys from ai_prompts.message_section."""
        selection = self.env['ai_prompts']._fields['message_section'].selection or []
        labels = {key: label for key, label in selection}
        labels.setdefault('detailed_feedback', 'Detailed Feedback')
        return labels

    def _build_output_schema(self, prompt_records, out_of_marks):
        """Return a JSON schema instruction string based on active prompts and marking context.

        Included output keys:

        * ``summary`` — if any active prompt has section ``summary``
        * ``detailed_analysis`` — if any active prompt has section ``detailed_analysis``
        * ``results_table`` — if any active prompt has section ``results_table``
        * ``score`` + ``score_comment`` — if *out_of_marks* is non-zero
        * ``feedback`` + ``links`` — if any active prompt has section ``targeted_feedback``
        """
        active_sections = {
            (p.message_section or '')
            for p in (prompt_records or self.env['ai_prompts'].browse())
        }
        include_score = bool(out_of_marks)
        keys = []
        # Iterate SECTION_HEADINGS in declaration order so this list never
        # needs manual reordering — just update SECTION_HEADINGS / _SECTION_TO_OUTPUT_KEYS.
        for section_key in SECTION_HEADINGS:
            output_keys = _SECTION_TO_OUTPUT_KEYS.get(section_key)
            if not output_keys:
                continue
            if section_key == 'score':
                if include_score:
                    keys.extend(output_keys)
            elif section_key in active_sections:
                keys.extend(output_keys)
        if not keys:
            return ''
        key_lines = ',\n  '.join(
            _OUTPUT_SCHEMA_KEY_DESCRIPTIONS.get(k, f'"{k}": ...')
            for k in keys
        )
        lines = [
            'Return ONLY valid JSON with these exact keys (no others):',
            '{',
            f'  {key_lines}',
            '}',
        ]
        if include_score:
            lines.append(
                'Set score to null and explain in score_comment if you cannot determine a mark.'
            )
        return '\n'.join(lines)

    def _build_payload(self, prompt_records, dynamic_section_data, include_reasoning=False):
        """Build a complete chat payload by merging prompt records with dynamic data.

        For each section in the prompt section order from ``ai_prompts``:

        1. Prompt template records whose ``message_section`` matches are emitted
           first (in sequence order), before any dynamic content.
        2. Dynamic content (field values from the submission or resource) follows.
           The ``output_schema`` section is populated by ``_build_output_schema``
           in ``_assemble_feedback_payload`` before this method is called.

        The ``system`` section is special: any prompt templates assigned to it
        override the default ``_build_system_content()`` system message instead
        of becoming a user content block.

        Returns ``(payload_dict, prompt_names_used_list)``.
        """
        prompt_section_order = self._get_prompt_section_order()
        section_labels = self._get_prompt_section_labels()
        prompts_by_section = {key: [] for key in prompt_section_order}
        names = []

        for prompt in (prompt_records or self.env['ai_prompts'].browse()):  # browse() returns empty recordset when prompt_records is falsy)
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

        # Sections whose content should be nested as <output_format> inside a
        # parent section rather than emitted as standalone blocks.
        _FORMAT_PARENT = {
            'summary_format': 'summary',
            'detailed_analysis_format': 'detailed_analysis',
            'results_table_format': 'results_table',
        }

        # Pre-collect format-section text so parent sections can embed it.
        _format_text_for_parent = {}  # parent_key -> formatted child text
        for fmt_key, parent_key in _FORMAT_PARENT.items():
            fmt_items = prompts_by_section.get(fmt_key, [])
            fmt_dynamic = (dynamic_section_data.get(fmt_key) or '').strip()
            parts = [t for _, t in fmt_items] + ([fmt_dynamic] if fmt_dynamic else [])
            if parts:
                _format_text_for_parent[parent_key] = '<output_format>\n' + '\n\n'.join(parts) + '\n</output_format>'
                for pname, _ in fmt_items:
                    names.append(pname or section_labels.get(fmt_key, fmt_key.replace('_', ' ').title()))

        sections = []

        for section_key in prompt_section_order:
            if section_key == 'system':
                continue  # already handled above as the system message
            if section_key in _FORMAT_PARENT:
                continue  # emitted as a nested child of its parent section

            prompt_items = prompts_by_section[section_key]  # list of (name, text)
            dynamic_text = (dynamic_section_data.get(section_key) or '').strip()

            if not prompt_items and not dynamic_text:
                continue

            lines = []
            for pname, ptext in prompt_items:
                lines.append(ptext)
                names.append(pname or section_labels.get(section_key, section_key.replace('_', ' ').title()))

            # Dynamic text is always appended after any prompt template framing.
            if dynamic_text:
                lines.append(dynamic_text)
                names.append(section_labels.get(section_key, section_key.replace('_', ' ').title()))

            # Append the nested <output_format> block when this section has a
            # paired format section.
            fmt_block = _format_text_for_parent.get(section_key)
            if fmt_block:
                lines.append(fmt_block)

            sections.append(SECTION_HEADINGS.get(section_key, '%s') % '\n\n'.join(lines))

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
        """Return *selected_prompts* sorted by section order, then sequence.

        Callers are expected to pass an already-filtered set (e.g.
        ``resource.ai_active_prompts``).  The ``db_model_name`` parameter is
        kept for signature compatibility but is no longer used here.
        """
        self.ensure_one()
        section_order = {k: i for i, k in enumerate(self._get_prompt_section_order())}
        return (selected_prompts or self.env['ai_prompts'].browse()).sorted(
            key=lambda rec: (
                section_order.get(rec.message_section or '', 9999),
                (rec.sequence or 0),
                rec.id,
            )
        )

    def _collect_all_applicable_prompts(self, selected_prompts, db_model_name):
        """Full candidate-building used by ``_compute_ai_active_prompts``.

        Merges *selected_prompts* with global always-include prompts, then
        filters to those applicable to this AI model and *db_model_name*.
        Called at compute time; the result is stored as ``ai_active_prompts``.
        """
        self.ensure_one()
        section_order = {k: i for i, k in enumerate(self._get_prompt_section_order())}
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
        return applicable.sorted(
            key=lambda rec: (
                section_order.get(rec.message_section or '', 9999),
                (rec.sequence or 0),
                rec.id,
            )
        )

    # -------------------------------------------------------------------------
    # Markdown → HTML conversion (used by both feedback pipelines)
    # -------------------------------------------------------------------------

    def _prompts_request_toc(self, prompts):
        """Return True if *prompts* contains an 'other'-section prompt tagged 'TOC'."""
        return self.env['ai_prompts'].sudo()._has_tag(
            prompts.filtered(lambda p: p.message_section == 'other'), 'TOC'
        )

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

    def _combine_feedback_parts(self, parsed, include_toc=False):
        """Assemble summary, detailed_analysis, and results_table into a single HTML string.

        When the ``markdown`` package is available the sections are concatenated
        as raw Markdown and converted in a single pass so the ``toc`` extension
        can build one cross-section table of contents.  A styled TOC block is
        prepended to the output when ``include_toc=True`` and at least two
        distinct headings are present.

        ``include_toc`` should be set to ``True`` only when the active prompt
        set contains a prompt whose ``message_section`` is ``'other'`` and that
        has a tag named ``'TOC'``.

        Falls back to ``_normalize_feedback_html`` when none of the structured
        keys are present (e.g. when the AI returned plain text instead of JSON).
        """
        raw_parts = []
        for key in ('summary', 'detailed_analysis', 'results_table'):
            val = (parsed.get(key) or '').strip() if isinstance(parsed, dict) else ''
            if val:
                raw_parts.append(val)

        if not raw_parts:
            legacy = (parsed.get('feedback_html') if isinstance(parsed, dict) else None) or ''
            return self._normalize_feedback_html(legacy or None)

        if not _MARKDOWN_AVAILABLE:
            # Fallback: convert each part individually (no TOC).
            return '\n'.join(self._normalize_feedback_html(p) for p in raw_parts)

        combined_md = '\n\n'.join(raw_parts)
        md = _md_lib.Markdown(extensions=['tables', 'fenced_code', 'nl2br', 'toc'])
        body = md.convert(combined_md)
        body = body.replace('<table>', '<table class="table table-bordered table-sm">')

        toc_html = getattr(md, 'toc', '') if include_toc else ''
        # Only show the TOC when requested and at least two distinct headings exist.
        if toc_html and toc_html.strip() not in ('', '<div class="toc"></div>'):
            toc_block = (
                '<div class="o_field_html ai-feedback-toc" '
                'style="background:#f8f9fa;border:1px solid #dee2e6;'
                'border-radius:4px;padding:10px 16px;margin-bottom:16px;">'
                '<strong style="display:block;margin-bottom:6px;">Contents</strong>'
                + toc_html
                + '</div>'
            )
            return toc_block + '\n' + body

        return body

    # -------------------------------------------------------------------------
    # Base (non-targeted) feedback runner
    # -------------------------------------------------------------------------

    def _assemble_feedback_payload(
        self,
        ctx,
        prompts,
        student_answer,
        student_answer_chunks=None,
    ):
        """Assemble the complete OpenAI-compatible chat payload for one feedback call.

        This is the single integration point between the resource/submission context
        and ``_build_payload``.  It is called by both the generic and targeted
        feedback runners.

        Parameters
        ----------
        ctx : dict
            Feedback context built by ``_build_ai_feedback_ctx`` on the submission
            or resource.  Relevant keys used here:

            * ``out_of_marks`` – total marks available; drives ``_build_output_schema``.
            * ``include_reasoning`` – forwarded to ``_build_payload`` / provider.
            * All keys consumed by ``_build_dynamic_section_data`` (``instructions``,
              ``question``, ``model_answer``, ``notes``, ``out_of_marks``, …).

        prompts : ``ai_prompts`` recordset
            The active prompt records for this resource, typically
            ``resource.ai_active_prompts``.  Each record carries a
            ``message_section`` that determines which XML-tagged block it is
            placed in (see ``SECTION_HEADINGS``).

        student_answer : str
            Plain-text student answer.  Used when *student_answer_chunks* is
            absent (generic path).

        student_answer_chunks : list or None
            Pre-parsed answer chunks for the targeted feedback path.  When
            provided the student answer section is replaced with the JSON
            serialisation of the chunks.

        Returns
        -------
        tuple
            ``(payload_dict, prompt_names_used_list)`` as returned by
            ``_build_payload``.

        Processing steps
        ----------------
        1. Resolve the student answer text (plain string or JSON-serialised chunks).
        2. Call ``_build_dynamic_section_data`` to produce the base section dict
           from ``ctx`` (question, model answer, teacher notes, instructions, …).
        3. Inject the JSON output schema into the ``output_schema`` section via
           ``_build_output_schema``.
        4. Inject fallback format hints (``results_table_format``,
           ``summary_format``, ``detailed_analysis_format``) for any active
           section that has no dedicated format prompt template.
        5. Inject ``_TARGETED_FEEDBACK_RULES`` into ``targeted_feedback`` when
           that section is active and no prompt template covers it.
        6. Delegate final payload construction to ``_build_payload``, which
           merges prompt templates with dynamic data, wraps each section in its
           ``SECTION_HEADINGS`` XML tag, and builds the messages list.
        """
        if student_answer_chunks:
            student_text = json.dumps(student_answer_chunks, indent=2, ensure_ascii=False)
        else:
            student_text = student_answer.strip()

        dynamic_data = self._build_dynamic_section_data(ctx, student_answer_text=student_text)

        # Inject the dynamically built output schema into the output_schema section.
        out_of_marks = ctx.get('out_of_marks') or 0
        schema_text = self._build_output_schema(prompts, out_of_marks)
        if schema_text and 'output_schema' not in dynamic_data:
            dynamic_data['output_schema'] = schema_text

        # Inject default results-table format when no prompt template covers it.

        active_sections = {p.message_section for p in (prompts or self.env['ai_prompts'].browse())}

        # if 'results_table' in active_sections and 'results_table_format' not in active_sections:
        #     dynamic_data.setdefault('results_table_format', _DEFAULT_RESULTS_TABLE_FORMAT)
        # if 'summary' in active_sections and 'summary_format' not in active_sections:
        #     dynamic_data.setdefault('summary_format', _DEFAULT_SECTION_FORMAT)
        # if 'detailed_analysis' in active_sections and 'detailed_analysis_format' not in active_sections:
        #     dynamic_data.setdefault('detailed_analysis_format', _DEFAULT_SECTION_FORMAT)
        # if 'targeted_feedback' in active_sections:
        #     dynamic_data.setdefault('targeted_feedback', _TARGETED_FEEDBACK_RULES)

        return self._build_payload(
            prompts,
            dynamic_data,
            include_reasoning=ctx.get('include_reasoning', False),
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
        feedback_html = self._combine_feedback_parts(parsed, include_toc=self._prompts_request_toc(prompts)) or self._normalize_feedback_html(raw_content)
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
