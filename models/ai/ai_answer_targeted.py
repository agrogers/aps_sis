import json
import re
from html import escape

from lxml import etree
from lxml import html as lxml_html

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt section labels (matched against prompt record names)
# ---------------------------------------------------------------------------
_SECTION_SPECIFIC_INSTRUCTIONS = 'Specific Instructions'
_SECTION_MAXIMUM_MARK = 'Maximum Mark'
_SECTION_QUESTION = 'Question'
_SECTION_MODEL_ANSWER = 'Model Answer'
_SECTION_NOTES = 'Notes'
_SECTION_DETAILED_FEEDBACK = 'Detailed Feedback'
_SECTION_STUDENT_ANSWER = 'Student Answer'
_SECTION_TARGETED_FEEDBACK = 'Targeted Feedback'
_SECTION_RESPONSE_FORMAT = 'Response Format'
_SECTION_PROMPT_TEMPLATE = 'Prompt Template'

# ---------------------------------------------------------------------------
# Prompt section body templates
# ---------------------------------------------------------------------------
_PROMPT_AI_INSTRUCTIONS = '## AI Instructions:\n%s'
_PROMPT_MAXIMUM_MARK = '## Maximum Mark:\n%s'
_PROMPT_QUESTION = '## Question:\n%s'
_PROMPT_MODEL_ANSWER = '## Model Answer:\n%s'
_PROMPT_MODEL_ANSWER_FALLBACK = 'No model answer provided.'
_PROMPT_NOTES = '## Notes:\n%s'
_PROMPT_DETAILED_FEEDBACK = '## DETAILED FEEDBACK:\n%s'
_PROMPT_STUDENT_ANSWER = 'Student Answer:\n%s'
_PROMPT_STUDENT_ANSWER_CHUNKS = 'Student Answer Chunks:\n%s'
_PROMPT_EXTERNAL_TEMPLATE = '## Prompt Template:\n%s'

_PROMPT_RESPONSE_FORMAT = (
    'Return ONLY valid JSON with these keys:\n'
    '{"feedback_html": string, "score": number|null, "score_comment": string|null}.\n'
    'feedback_html must be an HTML fragment using tags such as <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.\n'
    'If you cannot determine a mark, set score to null and explain why in score_comment.'
)

# ---------------------------------------------------------------------------
# System prompt for answer-grading calls
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_FEEDBACK = (
    'You are an expert teacher assistant. Follow the supplied instructions exactly, '
    'produce constructive teacher feedback for students, and when possible determine a mark.'
)
_SYSTEM_PROMPT_FEEDBACK_NO_REASONING = (
    ' Do not return reasoning, chain-of-thought, or thinking text. Return only the final answer.'
)


class APSAIModelAnswerChunking(models.Model):
    _inherit = 'aps.ai.model'

    @api.model
    def _build_submission_answer_chunks(self, answer_html, chunk_mode='auto'):
        html_chunk_data = self._build_submission_answer_chunks_from_html(answer_html, chunk_mode=chunk_mode)
        if html_chunk_data:
            return html_chunk_data

        answer_text = self._html_to_text(answer_html)
        chunk_texts = self._split_submission_answer_chunks(answer_text)
        chunks = [
            {'id': f'c{index}', 'text': chunk_text}
            for index, chunk_text in enumerate(chunk_texts, start=1)
        ]
        chunk_html = ''.join(
            '<span class="aps-ai-answer-chunk" data-chunk-id="%s">%s</span> '
            % (chunk['id'], escape(chunk['text']).replace('\n', '<br/>'))
            for chunk in chunks
        ).strip()
        return {'chunks': chunks, 'chunked_html': chunk_html}

    @api.model
    def _build_submission_answer_chunks_from_html(self, answer_html, chunk_mode='auto'):
        if not answer_html or '<' not in answer_html:
            return False
        try:
            wrapper = lxml_html.fragment_fromstring(answer_html, create_parent='div')
        except (etree.ParserError, ValueError, TypeError):
            return False

        chunk_nodes = []
        for child in wrapper:
            chunk_nodes.extend(self._collect_answer_chunk_nodes(child, chunk_mode=chunk_mode))
        if not chunk_nodes:
            return False

        chunks = []
        for _index, node in enumerate(chunk_nodes, start=1):
            chunk_text = self._normalize_answer_chunk_text(self._get_chunk_node_text(node))
            if not chunk_text:
                continue
            chunk_id = f'c{len(chunks) + 1}'
            existing_classes = [p for p in (node.get('class') or '').split() if p]
            if 'aps-ai-answer-chunk' not in existing_classes:
                existing_classes.append('aps-ai-answer-chunk')
            node.set('class', ' '.join(existing_classes))
            node.set('data-chunk-id', chunk_id)
            chunks.append({'id': chunk_id, 'text': chunk_text})
        if not chunks:
            return False

        chunk_html = self._serialize_answer_chunk_wrapper(wrapper)
        return {'chunks': chunks, 'chunked_html': chunk_html}

    @api.model
    def _collect_answer_chunk_nodes(self, node, chunk_mode='auto'):
        tag_name = getattr(node, 'tag', None)
        if not isinstance(tag_name, str):
            return []
        tag_name = tag_name.lower()
        if tag_name in {'ul', 'ol'}:
            nodes = []
            for child in node:
                nodes.extend(self._collect_answer_chunk_nodes(child, chunk_mode=chunk_mode))
            return nodes
        child_block_nodes = [
            child for child in node
            if isinstance(getattr(child, 'tag', None), str)
            and child.tag.lower() in {'div', 'p', 'li', 'blockquote', 'pre'}
        ]
        if tag_name in {'div', 'p', 'li', 'blockquote', 'pre'} and not child_block_nodes:
            return self._split_leaf_block_node_into_chunks(node, chunk_mode=chunk_mode)
        nodes = []
        for child in node:
            nodes.extend(self._collect_answer_chunk_nodes(child, chunk_mode=chunk_mode))
        return nodes

    @api.model
    def _split_leaf_block_node_into_chunks(self, node, chunk_mode='auto'):
        segments = self._split_leaf_block_segments(self._get_chunk_node_text(node), chunk_mode=chunk_mode)
        if not segments:
            return []
        if len(segments) == 1:
            return [node]
        for child in list(node):
            node.remove(child)
        node.text = None
        chunk_nodes = []
        for segment in segments:
            chunk_node = etree.Element('span')
            chunk_node.text = segment['text']
            node.append(chunk_node)
            chunk_nodes.append(chunk_node)
            if segment['separator'] == 'space':
                chunk_node.tail = ' '
            elif segment['separator'] == 'br':
                sep = etree.Element('br')
                sep.tail = ''
                node.append(sep)
        return chunk_nodes

    @api.model
    def _get_chunk_node_text(self, node):
        return ''.join(node.itertext()) if node is not None else ''

    @api.model
    def _split_leaf_block_segments(self, text, chunk_mode='auto'):
        _MIN_SUB_CHUNK_WORDS = 5
        normalized_text = re.sub(r'\r\n?', '\n', text or '').strip()
        if not normalized_text:
            return []

        # Code mode: treat each non-empty line as its own chunk.
        if chunk_mode == 'code':
            lines = [line for line in normalized_text.split('\n') if line.strip()]
            return [
                {'text': line, 'separator': 'br' if idx < len(lines) - 1 else None}
                for idx, line in enumerate(lines)
            ]

        segments = []
        lines = [line.strip() for line in normalized_text.split('\n') if line.strip()]
        for line_index, line in enumerate(lines):
            raw_sentences = [
                s.strip()
                for s in re.split(r'(?<=[.!?])(?:\s+|(?=[A-Z"\'(]))', line)
                if s.strip()
            ]
            # Merge parts that are too short back into the previous part so that
            # e.g. print("Error: Please enter 2 words. ") doesn't get split on
            # the "." leaving a bare `")` fragment.
            sentences = []
            for s in raw_sentences:
                if sentences and len(re.findall(r'\b\w+\b', s)) < _MIN_SUB_CHUNK_WORDS:
                    sentences[-1] = sentences[-1] + ' ' + s
                else:
                    sentences.append(s)
            if not sentences:
                continue
            for sentence_index, sentence in enumerate(sentences):
                if sentence_index < len(sentences) - 1:
                    trailing_separator = 'space'
                elif line_index < len(lines) - 1:
                    trailing_separator = 'br'
                else:
                    trailing_separator = None
                sub_parts = re.split(r'(?<=[,;])\s+', sentence)
                if len(sub_parts) > 1 and all(
                    len(re.findall(r'\b\w+\b', p)) >= _MIN_SUB_CHUNK_WORDS for p in sub_parts
                ):
                    for sub_index, sub in enumerate(sub_parts):
                        sub_sep = 'space' if sub_index < len(sub_parts) - 1 else trailing_separator
                        segments.append({'text': sub, 'separator': sub_sep})
                else:
                    segments.append({'text': sentence, 'separator': trailing_separator})
        return segments

    @api.model
    def _normalize_answer_chunk_text(self, text):
        lines = [re.sub(r'\s+', ' ', (line or '')).strip() for line in re.split(r'\r?\n', text or '')]
        return '\n'.join(line for line in lines if line)

    @api.model
    def _serialize_answer_chunk_wrapper(self, wrapper):
        parts = []
        if wrapper.text and wrapper.text.strip():
            parts.append(escape(wrapper.text))
        for child in wrapper:
            parts.append(etree.tostring(child, encoding='unicode', method='html'))
        return ''.join(parts).strip()

    @api.model
    def _split_submission_answer_chunks(self, answer_text):
        text = re.sub(r'\r\n?', '\n', answer_text or '').strip()
        if not text:
            return []
        tokens = re.findall(r'\S+|\s+', text)
        sentences = []
        current = []
        word_count = 0
        for token in tokens:
            current.append(token)
            if token.isspace():
                if '\n' in token and word_count:
                    chunk = ''.join(current).strip()
                    if chunk:
                        sentences.append(chunk)
                    current = []
                    word_count = 0
                continue
            word_count += 1
            if re.search(r'[.!?]+$', token):
                chunk = ''.join(current).strip()
                if chunk:
                    sentences.append(chunk)
                current = []
                word_count = 0
        tail = ''.join(current).strip()
        if tail:
            sentences.append(tail)

        _MIN_SUB_CHUNK_WORDS = 5
        chunks = []
        for sentence in sentences:
            sub_tokens = re.findall(r'\S+|\s+', sentence)
            sub_parts = []
            current_sub = []
            for token in sub_tokens:
                current_sub.append(token)
                if not token.isspace() and re.search(r'[,;]+$', token):
                    part = ''.join(current_sub).strip()
                    if part:
                        sub_parts.append(part)
                    current_sub = []
            tail_sub = ''.join(current_sub).strip()
            if tail_sub:
                sub_parts.append(tail_sub)
            if len(sub_parts) > 1 and all(
                len(re.findall(r'\b\w+\b', p)) >= _MIN_SUB_CHUNK_WORDS for p in sub_parts
            ):
                chunks.extend(sub_parts)
            else:
                chunks.append(sentence)

        merged = []
        for chunk in chunks:
            if '\n' not in chunk and len(re.findall(r'\b\w+\b', chunk)) < 2 and merged:
                merged[-1] = '%s %s' % (merged[-1], chunk)
            else:
                merged.append(chunk)
        return merged

    @api.model
    def _extract_targeted_feedback(self, parsed, raw_content, answer_chunk_data):
        fallback_html = self._normalize_feedback_html(
            (parsed.get('html') if isinstance(parsed, dict) else None)
            or (parsed.get('feedback_html') if isinstance(parsed, dict) else None)
            or (parsed.get('feedback') if isinstance(parsed, dict) and isinstance(parsed.get('feedback'), str) else None)
            or raw_content
        )
        if not answer_chunk_data:
            return {
                'feedback_html': fallback_html,
                'answer_chunks': False,
                'answer_chunked_html': False,
                'feedback_items': False,
                'feedback_links': False,
                'targeted_feedback': False,
            }
        valid_chunk_ids = {chunk['id'] for chunk in answer_chunk_data['chunks']}
        raw_feedback_items = (
            parsed.get('feedback')
            if isinstance(parsed, dict) and isinstance(parsed.get('feedback'), list)
            else []
        )
        feedback_items = []
        valid_feedback_ids = set()
        for item in raw_feedback_items:
            if not isinstance(item, dict):
                continue
            feedback_id = str(item.get('id') or '').strip()
            if not feedback_id or feedback_id in valid_feedback_ids:
                continue
            feedback_items.append({
                'id': feedback_id,
                'text': item.get('text') or '',
                'type': item.get('type') or False,
                'justification': item.get('justification') or '',
            })
            valid_feedback_ids.add(feedback_id)
        raw_links = (
            parsed.get('links')
            if isinstance(parsed, dict) and isinstance(parsed.get('links'), list)
            else []
        )
        feedback_links = []
        for link in raw_links:
            if not isinstance(link, dict):
                continue
            feedback_id = str(link.get('feedback_id') or '').strip()
            if not feedback_id or feedback_id not in valid_feedback_ids:
                continue
            seen_chunk_ids = set()
            chunk_ids = []
            for chunk_id in link.get('chunk_ids') or []:
                chunk_key = str(chunk_id or '').strip()
                if not chunk_key or chunk_key not in valid_chunk_ids or chunk_key in seen_chunk_ids:
                    continue
                chunk_ids.append(chunk_key)
                seen_chunk_ids.add(chunk_key)
            if chunk_ids:
                feedback_links.append({'feedback_id': feedback_id, 'chunk_ids': chunk_ids})
        return {
            'feedback_html': fallback_html,
            'answer_chunks': answer_chunk_data['chunks'],
            'answer_chunked_html': answer_chunk_data['chunked_html'],
            'feedback_items': feedback_items,
            'feedback_links': feedback_links,
            'targeted_feedback': True,
        }

    @api.model
    def _build_dynamic_prompt_sections(
        self,
        instructions='',
        out_of_marks=False,
        use_question=False,
        question='',
        use_model_answer=False,
        model_answer='',
        use_note=False,
        notes='',
        student_answer='',
        student_answer_chunks=None,
        targeted_feedback=False,
        prior_phase_context='',
    ):
        dynamic_sections = []

        if instructions and instructions.strip():
            dynamic_sections.append((_SECTION_SPECIFIC_INSTRUCTIONS, _PROMPT_AI_INSTRUCTIONS % instructions.strip()))
        if out_of_marks:
            dynamic_sections.append((_SECTION_MAXIMUM_MARK, _PROMPT_MAXIMUM_MARK % out_of_marks))
        if use_question and question.strip():
            dynamic_sections.append((_SECTION_QUESTION, _PROMPT_QUESTION % question.strip()))
        if use_model_answer:
            dynamic_sections.append((_SECTION_MODEL_ANSWER, _PROMPT_MODEL_ANSWER % (model_answer.strip() or _PROMPT_MODEL_ANSWER_FALLBACK)))
        if use_note and notes.strip():
            dynamic_sections.append((_SECTION_NOTES, _PROMPT_NOTES % notes.strip()))
        if prior_phase_context and prior_phase_context.strip():
            dynamic_sections.append((_SECTION_DETAILED_FEEDBACK, _PROMPT_DETAILED_FEEDBACK % prior_phase_context.strip()))
        if targeted_feedback and student_answer_chunks:
            dynamic_sections.append((
                _SECTION_STUDENT_ANSWER,
                _PROMPT_STUDENT_ANSWER_CHUNKS % json.dumps(student_answer_chunks, indent=2, ensure_ascii=False),
            ))
            dynamic_sections.append((_SECTION_TARGETED_FEEDBACK, self._PROMPT_TEMPLATE_SECTION_SENTINEL))
        else:
            dynamic_sections.append((_SECTION_STUDENT_ANSWER, _PROMPT_STUDENT_ANSWER % student_answer.strip()))
            dynamic_sections.append((_SECTION_RESPONSE_FORMAT, _PROMPT_RESPONSE_FORMAT))

        return dynamic_sections

    def _assemble_chat_payload(
        self,
        instructions='',
        external_prompt='',
        prompt_records=None,
        out_of_marks=False,
        use_question=False,
        question='',
        use_model_answer=False,
        model_answer='',
        use_note=False,
        notes='',
        student_answer='',
        student_answer_chunks=None,
        targeted_feedback=False,
        include_reasoning=False,
        prior_phase_context='',
    ):
        """Build an OpenAI-compatible chat payload from resolved prompt components."""
        prompt_sections = []
        prompt_names_used = []
        dynamic_sections = self._build_dynamic_prompt_sections(
            instructions=instructions,
            out_of_marks=out_of_marks,
            use_question=use_question,
            question=question,
            use_model_answer=use_model_answer,
            model_answer=model_answer,
            use_note=use_note,
            notes=notes,
            student_answer=student_answer,
            student_answer_chunks=student_answer_chunks,
            targeted_feedback=targeted_feedback,
            prior_phase_context=prior_phase_context,
        )

        dynamic_section_map = {
            self._normalize_prompt_name(name): (name, content)
            for name, content in dynamic_sections
            if content
        }
        used_dynamic_keys = set()

        # Build a reverse map: normalised tag name → prompt record (first match wins per tag).
        # This lets us look up a prompt by its section tag in O(1) inside the loop.
        tag_to_prompt = {}
        for prompt in prompt_records or self.env['ai_prompts']:
            for tag in prompt.tag_ids:
                tag_key = self._normalize_prompt_name(tag.name)
                if tag_key not in tag_to_prompt:
                    tag_to_prompt[tag_key] = prompt

        for prompt in prompt_records or self.env['ai_prompts']:
            # Check whether any tag on this prompt matches a dynamic section.
            matched_key = None
            for tag in prompt.tag_ids:
                tag_key = self._normalize_prompt_name(tag.name)
                if tag_key in dynamic_section_map and tag_key not in used_dynamic_keys:
                    matched_key = tag_key
                    break

            if matched_key is not None:
                section_name, section_content = dynamic_section_map[matched_key]
                if section_content == self._PROMPT_TEMPLATE_SECTION_SENTINEL:
                    # Targeted Feedback: the prompt's own text IS the section content.
                    section_content = (prompt.prompt or '').strip()
                else:
                    # Question / Model Answer / Notes / etc.: prepend the prompt's
                    # custom text above the dynamic field content when both exist.
                    prefix = (prompt.prompt or '').strip()
                    if prefix:
                        section_content = prefix + '\n\n' + section_content
                if not section_content:
                    used_dynamic_keys.add(matched_key)
                    continue
                prompt_sections.append(section_content)
                prompt_names_used.append(section_name)
                used_dynamic_keys.add(matched_key)
                continue

            # No tag matched a dynamic section — emit the prompt text directly.
            prompt_text = (prompt.prompt or '').strip()
            if prompt_text:
                prompt_sections.append(prompt_text)
                prompt_names_used.append((prompt.prompt_name or '').strip() or _SECTION_PROMPT_TEMPLATE)

        # Always include any dynamic sections not consumed by a prompt record.
        # This ensures Student Answer and Response Format are never silently
        # dropped when no placeholder prompt record with those names exists.
        for _dyn_name, _dyn_content in dynamic_sections:
            _dyn_key = self._normalize_prompt_name(_dyn_name)
            if _dyn_key not in used_dynamic_keys and _dyn_content and _dyn_content != self._PROMPT_TEMPLATE_SECTION_SENTINEL:
                prompt_sections.append(_dyn_content)
                prompt_names_used.append(_dyn_name)

        if external_prompt and prompt_records:
            prompt_sections.append(_PROMPT_EXTERNAL_TEMPLATE % external_prompt.strip())
            prompt_names_used.append(_SECTION_PROMPT_TEMPLATE)

        system_content = _SYSTEM_PROMPT_FEEDBACK
        if self.disable_reasoning:
            system_content += _SYSTEM_PROMPT_FEEDBACK_NO_REASONING
        payload = {
            'model': self.model_key,
            'messages': [
                {
                    'role': 'system',
                    'content': system_content,
                },
                {
                    'role': 'user',
                    'content': '\n\n'.join(section for section in prompt_sections if section),
                },
            ],
            'temperature': self.temperature,
            'max_completion_tokens': self.max_completion_tokens,
        }
        if self.disable_reasoning:
            payload['reasoning'] = {
                'enabled': False,
                'exclude': True,
            }
        elif include_reasoning:
            payload['reasoning'] = {
                'enabled': True,
                'exclude': False,
                'effort': 'low',
            }
        if self.force_json_response:
            payload['response_format'] = {'type': 'json_object'}
        return payload, prompt_names_used

    @api.model
    def _normalize_prompt_name(self, prompt_name):
        return re.sub(r'\s+', ' ', (prompt_name or '').strip()).casefold()

    def _resolve_tagged_prompts(self, tag_name, candidate_prompts):
        """Return prompts tagged *tag_name*, preferring records already in *candidate_prompts*.

        Resolution order:
        1. Any enabled prompt inside *candidate_prompts* that carries the tag.
        2. If none found there, the first enabled prompt in the global table that
           carries the tag (ordered by sequence, id).

        Returns an ``ai_prompts`` recordset (possibly empty).
        """
        self.ensure_one()
        tag_key = (tag_name or '').strip().casefold()

        # Step 1: look inside the caller-supplied candidate set (e.g. resource's ai_prompt_ids)
        if candidate_prompts:
            local_matches = candidate_prompts.filtered(
                lambda p: p.enabled and any(
                    t.name.strip().casefold() == tag_key for t in p.tag_ids
                )
            )
            if local_matches:
                return local_matches

        # Step 2: global fallback — find the tag record then search for prompts referencing it
        tag = self.env['ai.prompt.tag'].sudo().search(
            [('name', '=ilike', tag_name)], limit=1
        )
        if not tag:
            return self.env['ai_prompts']
        return self.env['ai_prompts'].sudo().search(
            [('enabled', '=', True), ('tag_ids', 'in', tag.ids)],
            order='sequence, id',
            limit=1,
        )

    # Map from ctx key → tag name used to auto-resolve supplementary prompts.
    _CTX_TAG_MAP = {
        'ai_targeted_feedback': 'Targeted Feedback',
        'use_question': 'Question',
        'use_model_answer': 'Model Answer',
        'use_note': 'Notes',
        'instructions': 'Specific Instructions',
    }

    def _resolve_ctx_tagged_prompts(self, ctx, candidate_prompts):
        """Return a merged recordset of all tag-resolved prompts for the active ctx flags.

        Iterates over ``_CTX_TAG_MAP``: for each key that is truthy in *ctx*,
        calls ``_resolve_tagged_prompts`` and accumulates the results.
        The returned set is de-duplicated and sorted by (sequence, id).
        """
        self.ensure_one()
        extra = self.env['ai_prompts']
        for ctx_key, tag_name in self._CTX_TAG_MAP.items():
            if ctx.get(ctx_key):
                extra |= self._resolve_tagged_prompts(tag_name, candidate_prompts)
        return extra.sorted(key=lambda r: ((r.sequence or 0), r.id))

    def _collect_applicable_prompts(self, selected_prompts, db_model_name):
        self.ensure_one()
        self.env['ai_prompts'].sudo().ensure_default_targeted_feedback_prompt()
        self.env['ai_prompts'].sudo().ensure_default_specific_instructions_prompt()
        selected = (selected_prompts or self.env['ai_prompts']).filtered(lambda rec: rec.enabled and (rec.prompt or rec.prompt_name))
        always = self.env['ai_prompts'].sudo().search([
            ('enabled', '=', True),
            ('always_include', '=', True),
        ])
        candidates = (selected | always)

        applicable = candidates.filtered(
            lambda rec: (
                not rec.applies_to_ai_models or self in rec.applies_to_ai_models
            ) and (
                not rec.applies_to_db_models or db_model_name in rec.applies_to_db_models.mapped('model')
            )
        )

        return applicable.sorted(key=lambda rec: ((rec.sequence or 0), rec.id))

    def _run_feedback_targeted(self, ctx, prompts, record, progress_callback):
        """Targeted AI feedback execution — always chunks the answer.

        Builds the targeted payload, calls the router, parses the structured
        response (feedback items + chunk links), and returns a normalised result.
        """
        self.ensure_one()
        student_answer = self._html_to_text(ctx.get('student_answer_html', ''))
        if not student_answer.strip():
            raise UserError(ctx.get('empty_answer_error') or _('No student answer provided.'))

        chunk_mode = 'code' if self.env['ai_prompts'].sudo()._has_tag(prompts, 'code') else 'auto'
        answer_chunk_data = self._build_submission_answer_chunks(ctx['student_answer_html'], chunk_mode=chunk_mode)
        payload, names = self._assemble_chat_payload(
            instructions=self._html_to_text(ctx.get('instructions', '')),
            prompt_records=prompts,
            out_of_marks=ctx.get('out_of_marks', False),
            use_question=ctx.get('use_question', False),
            question=self._html_to_text(ctx.get('question', '')),
            use_model_answer=ctx.get('use_model_answer', False),
            model_answer=self._html_to_text(ctx.get('model_answer', '')),
            use_note=ctx.get('use_note', False),
            notes=self._html_to_text(ctx.get('notes', '')),
            student_answer=student_answer,
            student_answer_chunks=answer_chunk_data['chunks'],
            targeted_feedback=True,
            include_reasoning=ctx.get('include_reasoning', False),
        )
        result = self._execute_logged_router_call(
            payload,
            request_type='submission_feedback',
            related_record=record,
            stream_callback=progress_callback,
            prompt_names_used=names,
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
                )
                try:
                    result = retry_result
                    raw_content = self._extract_message_content(result['response_json'])
                except Exception as retry_exc:
                    self._update_call_log_error(result.get('log_record'), retry_exc)
                    raise
            else:
                raise

        parsed = self._parse_structured_response(raw_content)
        targeted_result = self._extract_targeted_feedback(parsed, raw_content, answer_chunk_data)
        score = self._extract_score(parsed, raw_content)
        score_comment = self._extract_score_comment(parsed)
        return {
            'feedback_html': targeted_result['feedback_html'],
            'score': score,
            'score_comment': score_comment,
            'answer_chunks': targeted_result['answer_chunks'],
            'answer_chunked_html': targeted_result['answer_chunked_html'],
            'feedback_items': targeted_result['feedback_items'],
            'feedback_links': targeted_result['feedback_links'],
            'targeted_feedback': targeted_result['targeted_feedback'],
            'prompt_tokens': result['prompt_tokens'],
            'completion_tokens': result['completion_tokens'],
            'estimated_cost': result['estimated_cost'],
            'model_id': self.id,
            'model_name': self.display_name,
            'raw_content': raw_content,
        }
