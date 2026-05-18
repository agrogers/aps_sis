from odoo import api, fields, models
from odoo.exceptions import ValidationError


class APSAcademicWeek(models.Model):
    _name = 'aps.academic.week'
    _description = 'Academic Week'
    _order = 'academic_term_id, sequence, week_number'

    academic_term_id = fields.Many2one(
        'aps.academic.term',
        string='Academic Term',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Name', required=True, help='e.g. Week 1')
    short_name = fields.Char(string='Name', required=True, help='e.g. W1')
    week_number = fields.Integer(string='Week Number')
    sequence = fields.Integer(string='Sequence', default=10)
    current = fields.Boolean(string='Current Week', default=False)
    date_start = fields.Date(string='Start Date')
    date_stop = fields.Date(string='End Date')

    @api.depends('name', 'week_number', 'academic_term_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.week_number:
                rec.display_name = f"Week {rec.week_number} – {rec.name}" if rec.name else f"Week {rec.week_number}"
            else:
                rec.display_name = rec.name or ''

    @api.constrains('date_start', 'date_stop')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_stop and rec.date_stop < rec.date_start:
                raise ValidationError('End date must be on or after start date.')
