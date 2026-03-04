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
    

    # Confirmation
    confirm_update = fields.Boolean(string='I confirm I want to apply these changes to the selected submissions')

    @api.model
    def _default_submission_ids(self):
        return self.env.context.get('active_ids', [])

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

        if not updates:
            raise UserError(_("No updates selected. Please enable at least one update option."))

        # Perform the updates
        self.submission_ids.write(updates)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Successfully updated %d submissions.') % len(self.submission_ids),
                'type': 'success',
            }
        }