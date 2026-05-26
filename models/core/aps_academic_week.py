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

    @api.depends('name', 'short_name', 'week_number', 'week_cycle', 'academic_term_id')
    def _compute_display_name(self):
        for rec in self:
            week_code = rec.short_name or (f'W{rec.week_number}' if rec.week_number else rec.name or '')
            if week_code and rec.week_cycle:
                week_code = f'{week_code}({rec.week_cycle})'
            term_code = rec.academic_term_id.short_name if rec.academic_term_id else ''
            if week_code and term_code:
                rec.display_name = f'{week_code}-{term_code}'
            else:
                rec.display_name = week_code or term_code or rec.name or ''

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

    # --------------------------------------------------
    # ORM overrides – keep school calendar in sync
    # --------------------------------------------------

    def _recompute_school_calendar_week_ids(self):
        """Recompute aps.school.calendar.week_id for dates covered by these weeks.

        aps.school.calendar._compute_week_id only depends on 'date', so Odoo
        will not automatically recompute it when week date ranges change.
        We trigger it explicitly here.
        """
        Calendar = self.env['aps.school.calendar']
        for rec in self:
            if rec.date_start and rec.date_stop:
                cal_records = Calendar.search([
                    ('date', '>=', rec.date_start),
                    ('date', '<=', rec.date_stop),
                ])
                if cal_records:
                    cal_records._compute_week_id()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._recompute_school_calendar_week_ids()
        return records

    def write(self, vals):
        result = super().write(vals)
        if any(k in vals for k in ('date_start', 'date_stop', 'academic_term_id')):
            self._recompute_school_calendar_week_ids()
        return result
