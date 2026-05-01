from odoo import models


class APSResourceAIFeedback(models.Model):
    _name = 'aps.resources'
    _inherit = ['aps.resources', 'aps.ai.feedback.storage.mixin']

    def _get_ai_feedback_storage_field_name(self):
        self.ensure_one()
        return 'ai_feedback'

    def _apply_ai_feedback_result(self, result):
        self.ensure_one()
        self.sudo().write(self._get_ai_feedback_result_write_vals(result))