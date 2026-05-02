"""Backward-compatibility shim -- all logic now lives in ai_model.py."""
from odoo import api, models


class APSAIModelSubmissionFeedback(models.Model):
    _inherit = 'aps.ai.model'

    @api.model
    def generate_submission_feedback(self, submission, ai_run=None):
        """Backward-compat entry point -- delegates to generate_feedback()."""
        return self.generate_feedback(submission, ai_run=ai_run)
