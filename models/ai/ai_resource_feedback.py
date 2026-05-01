"""
Resource-specific AI feedback methods on aps.ai.model.

Knows about aps.resources field layout; generic engine lives in ai_model.py.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSAIModelResourceFeedback(models.Model):
    _inherit = 'aps.ai.model'

    @api.model
    def generate_resource_test_feedback(self, resource, ai_run=None):
        """Run the AI marking prompt against a resource's ai_answer test field."""
        resource.ensure_one()
        candidates = self.sudo().search(
            [('enabled', '=', True), ('provider_id.enabled', '=', True)],
        ).sorted(key=lambda rec: (-(rec.priority or 0), -(rec.provider_id.priority or 0), rec.id))
        if not candidates:
            raise UserError(_('No enabled AI models are configured.'))

        errors = []
        for model in candidates:
            try:
                return model._generate_resource_test_feedback(resource, ai_run=ai_run)
            except UserError:
                raise
            except Exception as exc:
                _logger.exception('AI test feedback call failed for model %s: %s', model.display_name, exc)
                errors.append(f'{model.display_name}: {exc}')

        detail = '\n'.join(errors[:3])
        if detail:
            raise UserError(_('All enabled AI models failed.\n%s') % detail)
        raise UserError(_('All enabled AI models failed.'))

    def _generate_resource_test_feedback(self, resource, ai_run=None):
        """Build and execute a test prompt payload for a resource."""
        self.ensure_one()
        payload = self._build_chat_payload_for_resource(resource, include_reasoning=bool(ai_run))
        progress_callback = ai_run._build_stream_callback() if ai_run else None
        result = self._execute_logged_router_call(
            payload,
            request_type='submission_feedback',
            related_record=resource,
            stream_callback=progress_callback,
        )
        try:
            response_json = result['response_json']
            raw_content = self._extract_message_content(response_json)
        except Exception as exc:
            self._update_call_log_error(result.get('log_record'), exc)
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

    def _build_chat_payload_for_resource(self, resource, include_reasoning=False):
        """Build a chat payload from a resource's fields, using ai_answer as the student answer."""
        student_answer = self._html_to_text(resource.ai_answer)
        if not student_answer.strip():
            raise UserError(_('Please enter a test answer in the "Test Answer" field before running the AI mark.'))
        out_of_marks = resource.marks if resource.marks and resource.marks > 0 else False
        selected_prompt = self._collect_applicable_prompt_text(resource.ai_prompt_ids, resource._name)
        return self._assemble_chat_payload(
            instructions=self._html_to_text(resource.ai_instructions),
            external_prompt=selected_prompt,
            out_of_marks=out_of_marks,
            use_question=resource.ai_use_question,
            question=self._html_to_text(resource.question),
            use_model_answer=resource.ai_use_model_answer or resource.ai_action == 'mark_submission_use_answer',
            model_answer=self._html_to_text(resource.answer),
            use_note=resource.ai_use_notes,
            notes=self._html_to_text(resource.notes),
            student_answer=student_answer,
            include_reasoning=include_reasoning,
        )
