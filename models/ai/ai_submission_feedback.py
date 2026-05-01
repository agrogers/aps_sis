"""
Submission-specific AI feedback methods on aps.ai.model.

Knows about aps.resource.submission field layout; generic engine lives in ai_model.py.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSAIModelSubmissionFeedback(models.Model):
    _inherit = 'aps.ai.model'

    @api.model
    def generate_submission_feedback(self, submission, ai_run=None):
        submission.ensure_one()
        candidates = self.sudo().search(
            [('enabled', '=', True), ('provider_id.enabled', '=', True)],
        ).sorted(key=lambda rec: (-(rec.priority or 0), -(rec.provider_id.priority or 0), rec.id))
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
        payload = self._build_chat_payload_for_submission(submission, include_reasoning=bool(ai_run))
        progress_callback = ai_run._build_stream_callback() if ai_run else None
        result = self._execute_logged_router_call(
            payload,
            request_type='submission_feedback',
            related_record=submission,
            stream_callback=progress_callback,
        )
        try:
            response_json = result['response_json']
            raw_content = self._extract_message_content(response_json)
        except Exception as exc:
            self._update_call_log_error(result.get('log_record'), exc)
            if self._is_reasoning_only_truncation(response_json):
                retry_payload = dict(payload)
                retry_payload['max_completion_tokens'] = self._get_retry_max_completion_tokens(
                    payload.get('max_completion_tokens')
                )
                retry_result = self._execute_logged_router_call(
                    retry_payload,
                    request_type='submission_feedback',
                    related_record=submission,
                    stream_callback=progress_callback,
                )
                try:
                    result = retry_result
                    response_json = result['response_json']
                    raw_content = self._extract_message_content(response_json)
                except Exception as retry_exc:
                    self._update_call_log_error(result.get('log_record'), retry_exc)
                    raise
            else:
                raise
        parsed = self._parse_structured_response(raw_content)
        feedback_html = self._normalize_feedback_html(
            (parsed.get('feedback_html') if isinstance(parsed, dict) else None)
            or (parsed.get('feedback') if isinstance(parsed, dict) else None)
            or raw_content
        )
        score = self._extract_score(parsed, raw_content)
        return {
            'feedback_html': feedback_html,
            'score': score,
            'prompt_tokens': result['prompt_tokens'],
            'completion_tokens': result['completion_tokens'],
            'estimated_cost': result['estimated_cost'],
            'model_id': self.id,
            'model_name': self.display_name,
            'raw_content': raw_content,
        }

    def _build_chat_payload_for_submission(self, submission, include_reasoning=False):
        """Build a chat payload from a submission's fields."""
        student_answer = self._html_to_text(submission.answer)
        if not student_answer.strip():
            raise UserError(_('The submission has no student answer to mark.'))
        out_of_marks = submission.out_of_marks if submission.out_of_marks and submission.out_of_marks > 0 else False
        selected_prompt = self._collect_applicable_prompt_text(submission.ai_prompt_ids, submission._name)
        return self._assemble_chat_payload(
            instructions=self._html_to_text(submission.ai_instructions),
            external_prompt=selected_prompt,
            out_of_marks=out_of_marks,
            use_question=submission.ai_use_question,
            question=self._html_to_text(submission.question),
            use_model_answer=submission.ai_use_model_answer or submission.ai_action == 'mark_submission_use_answer',
            model_answer=self._html_to_text(submission.model_answer),
            use_note=submission.ai_use_notes,
            notes=self._html_to_text(submission.resource_notes),
            student_answer=student_answer,
            include_reasoning=include_reasoning,
        )
