from odoo import fields, models


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