from odoo import fields, models, api
from odoo.exceptions import ValidationError


class APSAcademicYear(models.Model):
    _name = 'aps.academic.year'
    _description = 'Academic Year'
    _order = 'start_date desc'

    name = fields.Char(string='Name', required=True, translate=True, help='e.g. Academic Year 2025-2026')
    short_name = fields.Char(string='Short Name', size=20, help='e.g. AY25-26')
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    is_current = fields.Boolean(
        string='Current Year',
        default=False,
        help='Mark this as the active/current academic year. Only one year should be current at a time.',
    )
    active = fields.Boolean(default=True, string='Active')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Academic year name must be unique!'),
    ]

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date <= rec.start_date:
                raise ValidationError('End date must be after start date.')

    def action_set_current(self):
        self.search([('is_current', '=', True)]).write({'is_current': False})
        self.is_current = True

    @api.depends('short_name', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.short_name or rec.name
