from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ApsSchoolCalendar(models.Model):
    _name = 'aps.school.calendar'
    _description = 'School Calendar'
    _order = 'date, applies_to_level_id'

    DATE_TYPE = [
        ('school_day', 'School Day'),
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

    @api.depends('date', 'applies_to_level_id')
    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.date:
                parts.append(fields.Date.to_string(rec.date))
            if rec.date_type:
                parts.append(dict(rec._fields['date_type'].selection).get(rec.date_type, ''))
            if rec.applies_to_level_id:
                parts.append(rec.applies_to_level_id.display_name)
            else:
                parts.append('All Levels')
            rec.display_name = ' – '.join(parts)

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
