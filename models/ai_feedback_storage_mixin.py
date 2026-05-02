from odoo import _, fields, models
from odoo.exceptions import UserError


class APSAIFeedbackStorageMixin(models.AbstractModel):
    _name = 'aps.ai.feedback.storage.mixin'
    _description = 'Shared AI Feedback Storage'

    ai_answer_chunks = fields.Json(string='AI Answer Chunks', readonly=True, copy=False)
    ai_answer_chunked_html = fields.Text(string='AI Chunked Answer HTML', readonly=True, copy=False)
    ai_feedback_items = fields.Json(string='AI Feedback Items', readonly=True, copy=False)
    ai_feedback_links = fields.Json(string='AI Feedback Links', readonly=True, copy=False)

    def _get_ai_feedback_storage_field_name(self):
        self.ensure_one()
        return 'feedback'

    def _get_ai_feedback_result_write_vals(self, result):
        self.ensure_one()
        return {
            self._get_ai_feedback_storage_field_name(): result.get('feedback_html') or False,
            'ai_answer_chunks': result.get('answer_chunks') or False,
            'ai_answer_chunked_html': result.get('answer_chunked_html') or False,
            'ai_feedback_items': result.get('feedback_items') or False,
            'ai_feedback_links': result.get('feedback_links') or False,
        }

    # -------------------------------------------------------------------------
    # Shared AI run notification helpers
    # -------------------------------------------------------------------------

    def _get_ai_run_link_field(self):
        """Return the ``aps.ai.run`` field name that links a run to this record.

        Override in concrete models: ``'resource_id'`` for ``aps.resources``,
        ``'submission_id'`` for ``aps.resource.submission``.
        """
        raise NotImplementedError('_get_ai_run_link_field must be implemented by the concrete model')

    def _build_ai_run_notification(self, run, title, message, notification_type='info'):
        """Return a display_notification action for an AI background run."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'run_id': run.id,
            }
        }

    def _build_ai_failure_notification(self, error_text):
        """Return a sticky warning display_notification for a failed AI call."""
        message = error_text or _('The AI call failed.')
        normalized_message = message.lower()
        if 'empty completion' in normalized_message or 'did not return the final answer' in normalized_message:
            message = _(
                '%s\n\nIf AI > Logs only shows connection tests, clear that filter or apply the Submission Feedback filter.'
            ) % message
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Marking Failed'),
                'message': message,
                'type': 'warning',
                'sticky': True,
            }
        }

    def action_get_ai_run_status(self, run_id):
        """Return serialised status for an AI background run belonging to this record."""
        self.ensure_one()
        run = self.env['aps.ai.run'].sudo().browse(run_id)
        link_field = self._get_ai_run_link_field()
        if not run.exists() or getattr(run, link_field).id != self.id:
            raise UserError(_('The requested AI run does not belong to this record.'))
        return run._serialize_status()