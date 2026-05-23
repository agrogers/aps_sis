from odoo import api, fields, models
from odoo.exceptions import ValidationError


class APSAcademicWeek(models.Model):
    _name = 'aps.academic.week'
    _description = 'Academic Week'
    _order = 'academic_term_id, sequence, week_number'

    academic_term_id = fields.Many2one(
        'aps.academic.term',
        string='Academic Term',
        required=False,
        ondelete='set null',
        index=True,
        help='Auto-detected from week dates; can be manually overridden.',
    )
    name = fields.Char(string='Name', required=True, help='e.g. Week 1')
    short_name = fields.Char(string='Code', required=True, help='e.g. W1')
    week_number = fields.Integer(string='Week Number')
    week_cycle = fields.Char(string='Cycle', required=True, help='A or B or 1 or 2 for Week A/B or 1/2 cycle')
    sequence = fields.Integer(string='Sequence', default=10)
    current = fields.Boolean(
        string='Current Week',
        compute='_compute_current',
        store=True,
        help='True when today falls within the week\'s start and end dates.',
    )
    date_start = fields.Date(string='Start Date')
    date_stop = fields.Date(string='End Date')

    @api.depends('name', 'week_number', 'academic_term_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.week_number:
                rec.display_name = f"Week {rec.week_number} – {rec.name}" if rec.name else f"Week {rec.week_number}"
            else:
                rec.display_name = rec.name or ''

    @api.depends('date_start', 'date_stop')
    def _compute_current(self):
        today = fields.Date.today()
        for rec in self:
            rec.current = bool(
                rec.date_start and rec.date_stop
                and rec.date_start <= today <= rec.date_stop
            )

    @api.onchange('date_start', 'date_stop')
    def _onchange_dates_suggest_term(self):
        """Auto-suggest the academic term whose date range contains this week."""
        if self.date_start and self.date_stop:
            term = self.env['aps.academic.term'].search([
                ('start_date', '<=', self.date_start),
                ('end_date', '>=', self.date_stop),
            ], limit=1)
            if term:
                self.academic_term_id = term

    @api.constrains('date_start', 'date_stop')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_stop and rec.date_stop < rec.date_start:
                raise ValidationError('End date must be on or after start date.')
