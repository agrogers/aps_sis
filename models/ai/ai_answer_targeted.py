import json
import re
from html import escape

from lxml import etree
from lxml import html as lxml_html

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from .ai_answer_base import PROMPT_MODEL_ANSWER_FALLBACK

_logger = logging.getLogger(__name__)


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
    ):
        # Retained for external callers; internally _assemble_chat_payload now
        # delegates to _build_dynamic_section_data + _build_payload.
        ctx = {
            'instructions': instructions,
            'out_of_marks': out_of_marks,
            'use_question': use_question,
            'question': question,
            'use_model_answer': use_model_answer,
            'model_answer': model_answer,
            'use_note': use_note,
            'notes': notes,
        }
        if targeted_feedback and student_answer_chunks:
            student_text = json.dumps(student_answer_chunks, indent=2, ensure_ascii=False)
        else:
            student_text = student_answer.strip()
        data = self._build_dynamic_section_data(ctx, student_answer_text=student_text)
        return list(data.items())

    def _assemble_chat_payload(
        self,
        instructions='',
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
        # legacy parameter — unused
        external_prompt='',
    ):
        """Build an OpenAI-compatible chat payload — delegates to _assemble_feedback_payload."""
        ctx = {
            'instructions': instructions,
            'out_of_marks': out_of_marks,
            'use_question': use_question,
            'question': question,
            'use_model_answer': use_model_answer,
            'model_answer': model_answer,
            'use_note': use_note,
            'notes': notes,
            'include_reasoning': include_reasoning,
        }
        chunks = student_answer_chunks if targeted_feedback else None
        return self._assemble_feedback_payload(
            ctx,
            prompt_records or self.env['ai_prompts'],
            student_answer,
            student_answer_chunks=chunks,
        )

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

        if candidate_prompts:
            local_matches = candidate_prompts.filtered(
                lambda p: p.enabled and any(
                    t.name.strip().casefold() == tag_key for t in p.tag_ids
                )
            )
            if local_matches:
                return local_matches

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

    _CTX_TAG_MAP = {
        'ai_targeted_feedback': 'Targeted Feedback',
        'use_question':         'Question',
        'use_model_answer':     'Model Answer',
        'use_note':             'Notes',
        'instructions':         'Specific Instructions',
        'student_answer':       'Student Answer',
        'ai_standard_feedback': 'Standard Feedback',
    }

    # Maps each ctx_key to the message_section it corresponds to.
    # Used to skip auto tag-resolution when the user has already added a
    # prompt covering that section to their explicit ai_prompt_ids selection.
    _CTX_SECTION_MAP = {
        'ai_targeted_feedback': 'targeted_feedback',
        'use_question':         'question',
        'use_model_answer':     'model_answer',
        'use_note':             'notes',
        'instructions':         'ai_instructions',
        'student_answer':       'student_answer',
        # 'ai_standard_feedback' maps to no single section — skip
    }

    def _resolve_ctx_tagged_prompts(self, ctx, candidate_prompts):
        """Return a merged recordset of all tag-resolved prompts for the active ctx flags.

        Tag resolution is skipped for a ctx_key when *candidate_prompts* already
        contains a prompt whose ``message_section`` covers that section — this
        prevents auto-resolved default prompts from being added alongside a
        user-supplied prompt for the same section.
        """
        self.ensure_one()
        extra = self.env['ai_prompts']
        for ctx_key, tag_name in self._CTX_TAG_MAP.items():
            if not ctx.get(ctx_key):
                continue
            section = self._CTX_SECTION_MAP.get(ctx_key)
            if section and any(p.message_section == section for p in candidate_prompts):
                continue  # user already has a prompt covering this section
            extra |= self._resolve_tagged_prompts(tag_name, candidate_prompts)
        return extra.sorted(key=lambda r: ((r.sequence or 0), r.id))

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
        payload, names = self._assemble_feedback_payload(
            ctx,
            prompts,
            student_answer,
            student_answer_chunks=answer_chunk_data['chunks'],
        )
        result, raw_content, parsed = self._execute_feedback_call_with_json_retries(
            payload,
            record,
            progress_callback,
            prompt_names_used=names,
        )
        feedback_html = self._combine_feedback_parts(parsed) or self._normalize_feedback_html(raw_content)
        targeted_result = self._extract_targeted_feedback(parsed, raw_content, answer_chunk_data)
        score = self._extract_score(parsed, raw_content)
        score_comment = self._extract_score_comment(parsed)
        return {
            'feedback_html': feedback_html,
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
            'model_name': self.name,
            'raw_content': raw_content,
        }
