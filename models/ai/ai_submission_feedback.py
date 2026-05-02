"""
Submission-specific AI feedback methods on aps.ai.model.

Knows about aps.resource.submission field layout; generic engine lives in ai_model.py.
"""
import logging
import re
from html import escape

from lxml import etree, html

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSAIModelSubmissionFeedback(models.Model):
    _inherit = 'aps.ai.model'

    @api.model
    def generate_submission_feedback(self, submission, ai_run=None):
        submission.ensure_one()
        candidates = self.browse() if not self else self
        if not candidates:
            candidates = self._get_generation_candidates(resource=submission.resource_id)
        if not candidates:
            raise UserError(_('No enabled AI models are configured.'))

        errors = []
        for model in candidates:
            try:
                return model._generate_submission_feedback(submission, ai_run=ai_run)
            except UserError:
                raise
            except Exception as exc:
                _logger.exception('AI feedback call failed for model %s: %s', model.display_name, exc)
                errors.append(f'{model.display_name}: {exc}')

        detail = '\n'.join(errors[:3])
        if detail:
            raise UserError(_('All enabled AI models failed.\n%s') % detail)
        raise UserError(_('All enabled AI models failed.'))

    def _generate_submission_feedback(self, submission, ai_run=None):
        self.ensure_one()
        applicable_prompts = self._collect_applicable_prompts(submission.ai_prompt_ids, submission._name)
        phase_map = self._split_prompts_by_phase(applicable_prompts)
        ctx = self._build_submission_feedback_context(submission, include_reasoning=bool(ai_run))
        if any(phase_map.get(n) for n in (1, 2, 3)):
            return self._generate_feedback_multiphase(ctx, phase_map, related_record=submission, ai_run=ai_run)

        # Single-phase path.
        answer_chunk_data = (
            self._build_submission_answer_chunks(ctx['student_answer_html'])
            if ctx['ai_targeted_feedback'] else None
        )
        payload, prompt_names_used = self._build_chat_payload_from_ctx(ctx, applicable_prompts, answer_chunk_data)
        progress_callback = ai_run._build_stream_callback() if ai_run else None
        raw_content, result = self._execute_phase_call(
            payload, 'single', submission, progress_callback, prompt_names_used
        )
        parsed = self._parse_structured_response(raw_content)
        targeted_result = self._extract_targeted_feedback(parsed, raw_content, answer_chunk_data)
        score = self._extract_score(parsed, raw_content)
        final_result = {
            'feedback_html': targeted_result['feedback_html'],
            'score': score,
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
        self._log_ai_result(final_result)
        return final_result

    def _build_submission_feedback_context(self, submission, include_reasoning=False):
        """Extract AI feedback fields from a submission into a plain context dict."""
        return {
            'instructions': self._html_to_text(submission.ai_instructions),
            'out_of_marks': submission.out_of_marks if submission.out_of_marks and submission.out_of_marks > 0 else False,
            'use_question': submission.ai_use_question,
            'question': self._html_to_text(submission.question),
            'use_model_answer': submission.ai_use_model_answer or submission.ai_action == 'mark_submission_use_answer',
            'model_answer': self._html_to_text(submission.model_answer),
            'use_note': submission.ai_use_notes,
            'notes': self._html_to_text(submission.resource_notes),
            'student_answer': self._html_to_text(submission.answer),
            'student_answer_html': submission.answer,
            'ai_targeted_feedback': bool(submission.ai_targeted_feedback),
            'include_reasoning': include_reasoning,
            'empty_answer_error': _('The submission has no student answer to mark.'),
        }

    @api.model
    def _build_submission_answer_chunks(self, answer_html):
        html_chunk_data = self._build_submission_answer_chunks_from_html(answer_html)
        if html_chunk_data:
            return html_chunk_data

        answer_text = self._html_to_text(answer_html)
        chunk_texts = self._split_submission_answer_chunks(answer_text)
        chunks = [
            {
                'id': f'c{index}',
                'text': chunk_text,
            }
            for index, chunk_text in enumerate(chunk_texts, start=1)
        ]
        chunk_html = ''.join(
            '<span class="aps-ai-answer-chunk" data-chunk-id="%s">%s</span> '
            % (chunk['id'], escape(chunk['text']).replace('\n', '<br/>'))
            for chunk in chunks
        ).strip()
        return {
            'chunks': chunks,
            'chunked_html': chunk_html,
        }

    @api.model
    def _build_submission_answer_chunks_from_html(self, answer_html):
        if not answer_html or '<' not in answer_html:
            return False

        try:
            wrapper = html.fragment_fromstring(answer_html, create_parent='div')
        except (etree.ParserError, ValueError, TypeError):
            return False

        chunk_nodes = []
        for child in wrapper:
            chunk_nodes.extend(self._collect_answer_chunk_nodes(child))

        if not chunk_nodes:
            return False

        chunks = []
        for index, node in enumerate(chunk_nodes, start=1):
            chunk_text = self._normalize_answer_chunk_text(self._get_chunk_node_text(node))
            if not chunk_text:
                continue
            chunk_id = f'c{len(chunks) + 1}'
            existing_classes = [part for part in (node.get('class') or '').split() if part]
            if 'aps-ai-answer-chunk' not in existing_classes:
                existing_classes.append('aps-ai-answer-chunk')
            node.set('class', ' '.join(existing_classes))
            node.set('data-chunk-id', chunk_id)
            chunks.append({
                'id': chunk_id,
                'text': chunk_text,
            })

        if not chunks:
            return False

        chunk_html = self._serialize_answer_chunk_wrapper(wrapper)
        return {
            'chunks': chunks,
            'chunked_html': chunk_html,
        }

    @api.model
    def _collect_answer_chunk_nodes(self, node):
        tag_name = getattr(node, 'tag', None)
        if not isinstance(tag_name, str):
            return []

        tag_name = tag_name.lower()
        if tag_name in {'ul', 'ol'}:
            nodes = []
            for child in node:
                nodes.extend(self._collect_answer_chunk_nodes(child))
            return nodes

        child_block_nodes = [
            child for child in node
            if isinstance(getattr(child, 'tag', None), str)
            and child.tag.lower() in {'div', 'p', 'li', 'blockquote', 'pre'}
        ]

        if tag_name in {'div', 'p', 'li', 'blockquote', 'pre'} and not child_block_nodes:
            return self._split_leaf_block_node_into_chunks(node)

        nodes = []
        for child in node:
            nodes.extend(self._collect_answer_chunk_nodes(child))
        return nodes

    @api.model
    def _split_leaf_block_node_into_chunks(self, node):
        segments = self._split_leaf_block_segments(self._get_chunk_node_text(node))
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
                separator_node = etree.Element('br')
                separator_node.tail = ''
                node.append(separator_node)

        return chunk_nodes

    @api.model
    def _get_chunk_node_text(self, node):
        return ''.join(node.itertext()) if node is not None else ''

    @api.model
    def _split_leaf_block_segments(self, text):
        _MIN_SUB_CHUNK_WORDS = 5
        normalized_text = re.sub(r'\r\n?', '\n', text or '').strip()
        if not normalized_text:
            return []

        segments = []
        lines = [line.strip() for line in normalized_text.split('\n') if line.strip()]
        for line_index, line in enumerate(lines):
            sentences = [
                sentence.strip()
                for sentence in re.split(r'(?<=[.!?])(?:\s+|(?=[A-Z"\'(]))', line)
                if sentence.strip()
            ]
            if not sentences:
                continue
            for sentence_index, sentence in enumerate(sentences):
                # Determine the separator that follows this sentence.
                if sentence_index < len(sentences) - 1:
                    trailing_separator = 'space'
                elif line_index < len(lines) - 1:
                    trailing_separator = 'br'
                else:
                    trailing_separator = None

                # Try comma/semicolon sub-chunking within the sentence.
                sub_parts = re.split(r'(?<=[,;])\s+|\s+-\s+', sentence)
                if len(sub_parts) > 1 and all(
                    len(re.findall(r'\b\w+\b', p)) >= _MIN_SUB_CHUNK_WORDS for p in sub_parts
                ):
                    for sub_index, sub in enumerate(sub_parts):
                        sub_separator = 'space' if sub_index < len(sub_parts) - 1 else trailing_separator
                        segments.append({'text': sub, 'separator': sub_separator})
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

        # Pass 1: split on sentence boundaries (hard punctuation .!? and newlines)
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

        # Pass 2: sub-chunk each sentence on commas/semicolons if all resulting
        # pieces are at least _MIN_SUB_CHUNK_WORDS words long.
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

        # Merge orphaned single-word trailing chunks back into the previous chunk.
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
            or ((parsed.get('feedback') if isinstance(parsed, dict) and isinstance(parsed.get('feedback'), str) else None))
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
        raw_feedback_items = parsed.get('feedback') if isinstance(parsed, dict) and isinstance(parsed.get('feedback'), list) else []
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

        raw_links = parsed.get('links') if isinstance(parsed, dict) and isinstance(parsed.get('links'), list) else []
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
                feedback_links.append({
                    'feedback_id': feedback_id,
                    'chunk_ids': chunk_ids,
                })

        return {
            'feedback_html': fallback_html,
            'answer_chunks': answer_chunk_data['chunks'],
            'answer_chunked_html': answer_chunk_data['chunked_html'],
            'feedback_items': feedback_items,
            'feedback_links': feedback_links,
            'targeted_feedback': True,
        }
