from odoo import models, fields, api, _
from odoo.exceptions import UserError

class APSSubmissionMassUpdateWizard(models.TransientModel):
    _name = 'aps.submission.mass.update.wizard'
    _description = 'Mass Update Submissions Wizard'

    submission_ids = fields.Many2many(
        'aps.resource.submission',
        string='Submissions',
        required=True,
        default=lambda self: self._default_submission_ids()
    )

    # Update options
    update_points_scale = fields.Boolean(string='Points Scale')
    points_scale_value = fields.Integer(string='Value')
    update_state = fields.Boolean(string='State')
    state_value = fields.Selection([
        ('assigned', 'Assigned'),
        ('submitted', 'Submitted'),
        ('complete', 'Finalised'),  # Leave the underlying value as 'complete' for easier sync with task state 
        ], string='Value',
        )
    update_due_date = fields.Boolean(string='Due Date')
    due_date_value = fields.Date(string='Value')
    update_points = fields.Boolean(string='Points')
    points_value = fields.Integer(string='Value')
    update_submission_active = fields.Boolean(string='Submission Active')
    submission_active_value = fields.Boolean(string='Value')
    update_date_assigned = fields.Boolean(string='Date Assigned')
    date_assigned_value = fields.Date(string='Value')
    update_time_assigned = fields.Boolean(string='Time Assigned')
    time_assigned_value = fields.Float(string='Value')
    update_date_submitted = fields.Boolean(string='Date Submitted')
    date_submitted_value = fields.Date(string='Value')
    update_date_completed = fields.Boolean(string='Date Completed')
    date_completed_value = fields.Date(string='Value')
    update_score = fields.Boolean(string='Score')
    score_value = fields.Float(string='Value')
    update_out_of_marks = fields.Boolean(string='Out of Marks')
    out_of_marks_value = fields.Float(string='Value')
    update_submission_name = fields.Boolean(string='Submission Name')
    submission_name_value = fields.Char(string='Value')
    update_due_status = fields.Boolean(string='Due Status')
    due_status_value = fields.Selection([
        ('early', 'Early'),
        ('on-time', 'On Time'),
        ('late', 'Late'),
        ], string='Value',
        )
    update_notification_state = fields.Boolean(string='Notification State')
    notification_state_value = fields.Selection([
        ('not_sent', 'Not Sent'),
        ('sent', 'Sent'),
        ('posted', 'Posted'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
        ], string='Value',
        )
    update_question = fields.Boolean(string='Question')
    question_value = fields.Html(string='Value')
    update_answer = fields.Boolean(string='Answer')
    answer_value = fields.Html(string='Value')
    update_model_answer = fields.Boolean(string='Model Answer')
    model_answer_value = fields.Html(string='Value')
    update_feedback = fields.Boolean(string='Feedback')
    feedback_value = fields.Html(string='Value')

    # Confirmation
    confirm_update = fields.Boolean(string='I confirm I want to apply these changes to the selected submissions')

    @api.model
    def _default_submission_ids(self):
        return self.env.context.get('active_ids', [])

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            first = self.env['aps.resource.submission'].browse(active_ids[0])
            if first.exists():
                if 'question_value' in fields_list:
                    defaults['question_value'] = first.question
                if 'answer_value' in fields_list:
                    defaults['answer_value'] = first.answer
                if 'model_answer_value' in fields_list:
                    defaults['model_answer_value'] = first.model_answer
                if 'feedback_value' in fields_list:
                    defaults['feedback_value'] = first.feedback
        return defaults

    def action_update(self):
        self.ensure_one()

        if not self.submission_ids:
            raise UserError(_("No submissions selected."))

        # if not self.confirm_update:
        #     raise UserError(_("Please confirm that you want to apply these changes."))

        updates = {}

        if self.update_points_scale:
            updates['points_scale'] = self.points_scale_value

        if self.update_state:
            updates['state'] = self.state_value

        if self.update_due_date:
            updates['date_due'] = self.due_date_value

        if self.update_points:
            updates['points'] = self.points_value

        if self.update_date_assigned:
            updates['date_assigned'] = self.date_assigned_value

        if self.update_time_assigned:
            updates['time_assigned'] = self.time_assigned_value

        if self.update_submission_active:
            updates['submission_active'] = self.submission_active_value

        if self.update_date_submitted:
            updates['date_submitted'] = self.date_submitted_value

        if self.update_date_completed:
            updates['date_completed'] = self.date_completed_value

        if self.update_score:
            updates['score'] = self.score_value

        if self.update_out_of_marks:
            updates['out_of_marks'] = self.out_of_marks_value

        if self.update_submission_name:
            updates['submission_name'] = self.submission_name_value

        if self.update_due_status:
            updates['due_status'] = self.due_status_value

        if self.update_notification_state:
            updates['notification_state'] = self.notification_state_value

        if self.update_question:
            updates['question'] = self.question_value

        if self.update_answer:
            updates['answer'] = self.answer_value

        if self.update_feedback:
            updates['feedback'] = self.feedback_value

        if not updates and not self.update_model_answer:
            raise UserError(_("No updates selected. Please enable at least one update option."))

        # Perform the updates
        self.submission_ids.write(updates)

        # Update model answer (resource_id.answer) separately as it is a related readonly field
        if self.update_model_answer:
            resources = self.submission_ids.mapped('resource_id').filtered(lambda resource: resource.id)
            resources.write({'answer': self.model_answer_value})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Successfully updated %d submissions.') % len(self.submission_ids),
                'type': 'success',
            }
        }