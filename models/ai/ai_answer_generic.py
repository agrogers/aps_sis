import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSAIModelAnswerProcessing(models.Model):
    _inherit = 'aps.ai.model'

    # -------------------------------------------------------------------------
    # Generic (non-targeted) feedback path
    # -------------------------------------------------------------------------

    def _assemble_generic_payload(self, ctx, prompts, student_answer):
        """Build a multi-message chat payload for non-targeted feedback.

        Delegates to the unified ``_build_payload`` helper in
        ``ai_answer_base.py``.  Each logical section (AI Instructions,
        Maximum Mark, Question, …) becomes its own ``user`` message.
        Prompt records are emitted before the corresponding dynamic field
        content for every section.
        """
        dynamic_data = self._build_dynamic_section_data(ctx, student_answer_text=student_answer.strip())
        return self._build_payload(prompts, dynamic_data, include_reasoning=ctx.get('include_reasoning', False))

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
