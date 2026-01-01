from odoo import models, fields, api

class APSResourceAttempt(models.Model):
    _name = 'aps.resource.attempt'
    _description = 'Resource Attempt'

    assignment_id = fields.Many2one('aps.resource.assignment', string='Assignment', required=True)
    resource_id = fields.Many2one('aps.resources', string='Resource', related='assignment_id.resource_id', store=True)
    batch_id = fields.Char(string='Batch ID')
    state = fields.Selection([
        ('incomplete', 'Incomplete'),
        ('complete', 'Complete'),
    ], string='State', default='incomplete')
    date_assigned = fields.Date(string='Date Assigned')
    date_completed = fields.Date(string='Date Completed')
    result_percent = fields.Float(string='Result %')
    due_date = fields.Date(string='Due Date')
    due_status = fields.Selection([
        ('late', 'Late'),
        ('complete', 'Complete'),
        ('early', 'Early'),
    ], string='Due Status')
    actual_duration = fields.Float(string='Actual Duration (hours)')
    feedback = fields.Html(string='Feedback')

    def action_mark_complete(self):
        self.write({
            'state': 'complete',
            'date_completed': fields.Date.today(),
        })