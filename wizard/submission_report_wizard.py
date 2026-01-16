from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SubmissionReportWizard(models.TransientModel):
    _name = 'aps.submission.report.wizard'
    _description = 'Submission Report Options'

    submission_ids = fields.Many2many(
        'aps.resource.submission', 
        'aps_submission_report_wizard_rel',
        'wizard_id', 
        'submission_id',
        string='Submissions'
    )
    submission_count = fields.Integer(string='Submissions Selected')
    show_score = fields.Boolean(string='Show Score & Percentage', default=True)
    show_metadata = fields.Boolean(string='Show Metadata (Dates)', default=True)
    show_answer = fields.Boolean(string='Show Student Answer', default=True)
    show_feedback = fields.Boolean(string='Show Teacher Feedback', default=True)
    show_model_answer = fields.Boolean(string='Show Model Answer', default=True)
    page_break_before_resource = fields.Boolean(string='Page Break Before Each Resource', default=False)
    page_break_before_student = fields.Boolean(string='Page Break Before Each Student', default=False)
    page_break_after_model_answer = fields.Boolean(string='Page Break After Model Answer', default=False)

    @api.model
    def default_get(self, fields_list):
        """Override to get submission_ids from context active_ids"""
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        _logger.info("=== WIZARD default_get ===")
        _logger.info("active_ids from context: %s", active_ids)
        _logger.info("fields_list: %s", fields_list)
        if active_ids:
            res['submission_ids'] = [(6, 0, active_ids)]
            res['submission_count'] = len(active_ids)
        _logger.info("Returning res: %s", res)
        return res

    def action_print_report(self):
        """Generate the report with selected options"""
        _logger.info("=== WIZARD action_print_report ===")
        _logger.info("self.submission_ids: %s", self.submission_ids)
        _logger.info("self.submission_ids.ids: %s", self.submission_ids.ids)
        
        data = {
            'show_score': self.show_score,
            'show_metadata': self.show_metadata,
            'show_answer': self.show_answer,
            'show_feedback': self.show_feedback,
            'show_model_answer': self.show_model_answer,
            'page_break_before_resource': self.page_break_before_resource,
            'page_break_before_student': self.page_break_before_student,
            'page_break_after_model_answer': self.page_break_after_model_answer,
            'submission_ids': self.submission_ids.ids,  # Pass IDs in data
        }
        _logger.info("data: %s", data)
        
        # Save user preferences
        preference_fields = ['show_score', 'show_metadata', 'show_answer', 'show_feedback', 'show_model_answer', 'page_break_before_resource', 'page_break_before_student', 'page_break_after_model_answer']
        for field_name in preference_fields:
            self.env['ir.default'].set('aps.submission.report.wizard', field_name, getattr(self, field_name), user_id=self.env.user.id)
        
        # Pass the submission_ids as the recordset to report_action
        return self.env.ref('aps_sis.submission_report_action').report_action(
            self.submission_ids, data=data
        )
