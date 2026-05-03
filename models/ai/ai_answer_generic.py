import json
import logging
import re
from html import escape

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates and system prompts used by the generic (non-targeted) path
# ---------------------------------------------------------------------------
_PROMPT_RESPONSE_FORMAT = (
    'Return ONLY valid JSON with these keys:\n'
    '{"feedback_html": string, "score": number|null, "score_comment": string|null}.\n'
    'feedback_html must be an HTML fragment using tags such as <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.\n'
    'If you cannot determine a mark, set score to null and explain why in score_comment.'
)
_SYSTEM_PROMPT_FEEDBACK = (
    'You are an expert teacher assistant. Follow the supplied instructions exactly, '
    'produce constructive teacher feedback for students, and when possible determine a mark.'
)
_SYSTEM_PROMPT_FEEDBACK_NO_REASONING = (
    ' Do not return reasoning, chain-of-thought, or thinking text. Return only the final answer.'
)


class APSAIModelAnswerProcessing(models.Model):
    _inherit = 'aps.ai.model'

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

    def _normalize_feedback_html(self, feedback_html):
        text = (feedback_html or '').strip()
        if not text:
            return '<p>No feedback was returned by the AI model.</p>'
        if '<' in text and '>' in text:
            return text
        paragraphs = [segment.strip() for segment in text.split('\n\n') if segment.strip()]
        if not paragraphs:
            paragraphs = [text]
        return ''.join('<p>%s</p>' % escape(paragraph).replace('\n', '<br/>') for paragraph in paragraphs)

    def _html_to_text(self, html_value):
        if not html_value:
            return ''
        text = str(html_value)
        text = text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
        for tag in ('</p>', '</div>', '</li>', '</h1>', '</h2>', '</h3>', '</h4>'):
            text = text.replace(tag, '\n')
        text = re.sub(r'<[^>]+>', '', text)
        return text.replace('&nbsp;', ' ').strip()

    # -------------------------------------------------------------------------
    # Generic (non-targeted) feedback path
    # -------------------------------------------------------------------------

    def _assemble_generic_payload(self, ctx, prompts, student_answer):
        """Build a simple chat payload for non-targeted feedback.

        Builds the user message directly from ctx — no named
        mechanism needed.  Prompt records are appended verbatim.
        Student Answer and the JSON Response Format are always included last.
        """
        sections = []
        names = []

        instructions = self._html_to_text(ctx.get('instructions', ''))
        if instructions.strip():
            sections.append('## AI Instructions:\n%s' % instructions.strip())
            names.append('Specific Instructions')

        out_of_marks = ctx.get('out_of_marks')
        if out_of_marks:
            sections.append('## Maximum Mark:\n%s' % out_of_marks)
            names.append('Maximum Mark')

        if ctx.get('use_question'):
            question = self._html_to_text(ctx.get('question', ''))
            if question.strip():
                sections.append('## Question:\n%s' % question.strip())
                names.append('Question')

        if ctx.get('use_model_answer'):
            model_answer = self._html_to_text(ctx.get('model_answer', ''))
            sections.append('## Model Answer:\n%s' % (model_answer.strip() or 'No model answer provided.'))
            names.append('Model Answer')

        if ctx.get('use_note'):
            notes = self._html_to_text(ctx.get('notes', ''))
            if notes.strip():
                sections.append('## Notes:\n%s' % notes.strip())
                names.append('Notes')

        # Append prompt records verbatim
        for prompt in prompts or self.env['ai_prompts']:
            prompt_text = (prompt.prompt or '').strip()
            if prompt_text:
                sections.append(prompt_text)
                names.append((prompt.prompt_name or '').strip() or 'Prompt Template')

        sections.append('Student Answer:\n%s' % student_answer.strip())
        names.append('Student Answer')

        sections.append(_PROMPT_RESPONSE_FORMAT)
        names.append('Response Format')

        system_content = _SYSTEM_PROMPT_FEEDBACK
        if self.disable_reasoning:
            system_content += _SYSTEM_PROMPT_FEEDBACK_NO_REASONING

        payload = {
            'model': self.model_key,
            'messages': [
                {'role': 'system', 'content': system_content},
                {'role': 'user', 'content': '\n\n'.join(s for s in sections if s)},
            ],
            'temperature': self.temperature,
            'max_completion_tokens': self.max_completion_tokens,
        }
        if self.disable_reasoning:
            payload['reasoning'] = {'enabled': False, 'exclude': True}
        elif ctx.get('include_reasoning'):
            payload['reasoning'] = {'enabled': True, 'exclude': False, 'effort': 'low'}
        if self.force_json_response:
            payload['response_format'] = {'type': 'json_object'}
        return payload, names

    def _run_feedback_generic(self, ctx, prompts, record, progress_callback):
        """Execute the non-targeted feedback path for this model instance."""
        self.ensure_one()
        student_answer = self._html_to_text(ctx.get('student_answer_html', ''))
        if not student_answer.strip():
            raise UserError(ctx.get('empty_answer_error') or _('No student answer provided.'))

        payload, names = self._assemble_generic_payload(ctx, prompts, student_answer)
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
        feedback_html = self._normalize_feedback_html(
            (parsed.get('feedback_html') if isinstance(parsed, dict) else None)
            or raw_content
        )
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
