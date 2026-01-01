from odoo import models, fields, api

class APSResourceAssignment(models.Model):
    _name = 'aps.resource.assignment'
    _description = 'Resource Assignment'

    resource_id = fields.Many2one('aps.resources', string='Resource', required=True)
    student_id = fields.Many2one('res.partner', string='Student', domain=[('is_student', '=', True)])
    attempt_count = fields.Integer(string='Attempt Count', compute='_compute_attempt_stats', store=True)
    last_score = fields.Float(string='Last Score', compute='_compute_attempt_stats', store=True)
    avg_score = fields.Float(string='Average Score', compute='_compute_attempt_stats', store=True)
    weighted_score = fields.Float(string='Weighted Score', compute='_compute_attempt_stats', store=True)
    max_score = fields.Float(string='Max Score')
    state = fields.Selection([
        ('created', 'Created'),
        ('assigned', 'Assigned'),
        ('reassigned', 'Reassigned'),
        ('due', 'Due'),
        ('overdue', 'Overdue'),
        ('complete', 'Complete'),
        ('late', 'Late'),
    ], string='State', default='created')
    redo_resource_id = fields.Many2one('aps.resources', string='Redo Resource')
    due_date = fields.Date(string='Due Date', compute='_compute_due_date', store=True)
    attempt_ids = fields.One2many('aps.resource.attempt', 'assignment_id', string='Attempts')

    @api.depends('attempt_ids', 'attempt_ids.state', 'attempt_ids.result_percent', 'attempt_ids.due_date')
    def _compute_attempt_stats(self):
        for rec in self:
            attempts = rec.attempt_ids.filtered(lambda a: a.state == 'complete')
            rec.attempt_count = len(attempts)
            if attempts:
                scores = attempts.mapped('result_percent')
                rec.last_score = scores[-1] if scores else 0.0
                rec.avg_score = sum(scores) / len(scores) if scores else 0.0
                rec.weighted_score = rec.avg_score  # Placeholder, could be weighted differently
            else:
                rec.last_score = 0.0
                rec.avg_score = 0.0
                rec.weighted_score = 0.0

    @api.depends('attempt_ids.due_date', 'attempt_ids.state')
    def _compute_due_date(self):
        for rec in self:
            incomplete_attempts = rec.attempt_ids.filtered(lambda a: a.state == 'incomplete')
            if incomplete_attempts:
                due_dates = incomplete_attempts.mapped('due_date')
                rec.due_date = max(due_dates) if due_dates else False
            else:
                rec.due_date = False

    def action_create_attempt(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Attempt',
            'res_model': 'aps.resource.attempt',
            'view_mode': 'form',
            'view_id': self.env.ref('aps_sis.view_aps_resource_attempt_form').id,
            'context': {
                'default_assignment_id': self.id,
                'default_resource_id': self.resource_id.id,
                'default_date_assigned': fields.Date.today(),
            },
            'target': 'new',
        }