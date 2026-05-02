"""Backward-compatibility shim for resource AI test feedback.

All generic AI pipeline logic lives in ai_model.py.
To run AI feedback for an aps.resources record, call::

    self.env['aps.ai.model'].generate_feedback(resource, ai_run=ai_run)

or use the shim below which existing callers already reference.
"""
import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class APSAIModelResourceFeedback(models.Model):
    _inherit = 'aps.ai.model'

    @api.model
    def generate_resource_test_feedback(self, resource, ai_run=None):
        """Backward-compat entry point — delegates to generate_feedback()."""
        return self.generate_feedback(resource, ai_run=ai_run)

