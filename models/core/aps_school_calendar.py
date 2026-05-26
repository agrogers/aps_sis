from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ApsSchoolCalendar(models.Model):
    _name = 'aps.school.calendar'
    _description = 'School Calendar'
    _order = 'date, applies_to_level_id'

    DATE_TYPE = [
        ('school_day', 'School Day'),
        ('event', 'Event'),
        ('public_holiday', 'Public Holiday'),
        ('school_holiday', 'School Holiday'),
        ('student_free', 'Student Free Day'),
        ('weekend', 'Weekend'),
    ]

    date = fields.Date(string='Date', required=True, index=True)
    date_type = fields.Selection(
        DATE_TYPE,
        string='Type',
        required=True,
    )
    repeating = fields.Boolean(
        string='Repeats Annually',
        default=False,
        help='If set, this entry will be automatically re-created when generating the calendar for the following year.',
    )
    description = fields.Char(string='Description')
    notes = fields.Text(string='Notes')
    applies_to_level_id = fields.Many2one(
        'aps.level',
        string='Applies To Level',
        ondelete='set null',
        index=True,
        help='Leave blank to apply to all levels.',
    )

    # Calendar colour index per date_type
    # Odoo palette: 0=grey, 1=red, 2=orange, 3=yellow, 4=teal, 5=purple,
    #               6=salmon, 7=blue, 8=pink, 10=green, 11=dark-blue
    _DATE_TYPE_COLOR = {
        'school_day':    10,   # green
        'event':          7,   # blue
        'public_holiday': 3,   # yellow
        'school_holiday': 2,   # orange
        'student_free':   6,   # salmon
        'weekend':        0,   # grey
    }

    color = fields.Integer(
        string='Color',
        compute='_compute_color',
        store=True,
    )

    @api.depends('date_type')
    def _compute_color(self):
        for rec in self:
            rec.color = self._DATE_TYPE_COLOR.get(rec.date_type, 0)

    # Computed: which academic week does this date fall in?
    week_id = fields.Many2one(
        'aps.academic.week',
        string='Academic Week',
        compute='_compute_week_id',
        store=True,
    )

    @api.depends('date')
    def _compute_week_id(self):
        Week = self.env['aps.academic.week']
        for rec in self:
            if rec.date:
                week = Week.search([
                    ('date_start', '<=', rec.date),
                    ('date_stop', '>=', rec.date),
                ], limit=1)
                rec.week_id = week
            else:
                rec.week_id = False

    @api.depends('date', 'description', 'week_id.short_name', 'week_id.academic_term_id.short_name')
    def _compute_display_name(self):
        for rec in self:
            term_code = rec.week_id.academic_term_id.short_name if rec.week_id and rec.week_id.academic_term_id else None
            week_code = rec.week_id.short_name if rec.week_id else None
            if term_code and week_code:
                rec.display_name = f'{term_code}-{week_code}'
            elif week_code:
                rec.display_name = week_code
            elif rec.date:
                rec.display_name = rec.date.strftime('%d %b')
            else:
                rec.display_name = '(no date)'
            if rec.description:
                rec.display_name = f'{rec.display_name} ({rec.description})'

    @api.constrains('date', 'applies_to_level_id')
    def _check_unique_date_level(self):
        for rec in self:
            domain = [('date', '=', rec.date), ('id', '!=', rec.id)]
            if rec.applies_to_level_id:
                domain.append(('applies_to_level_id', '=', rec.applies_to_level_id.id))
            else:
                domain.append(('applies_to_level_id', '=', False))
            if self.search_count(domain):
                level_label = rec.applies_to_level_id.display_name if rec.applies_to_level_id else 'All Levels'
                raise ValidationError(
                    f'A calendar entry for {rec.date} already exists for {level_label}.'
                )
