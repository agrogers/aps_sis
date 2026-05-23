from odoo import fields, models, api
from odoo.exceptions import ValidationError


class APSAcademicTerm(models.Model):
    _name = 'aps.academic.term'
    _description = 'Academic Term'
    _order = 'start_date desc'

    name = fields.Char(string='Name', required=True, translate=True, help='e.g. Term 1 2025-2026')
    short_name = fields.Char(string='Short Name', size=20, help='e.g. T1-25')
    academic_year_id = fields.Many2one(
        'aps.academic.year',
        string='Academic Year',
        required=True,
        ondelete='cascade',
    )
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    active = fields.Boolean(default=True, string='Active')

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date <= rec.start_date:
                raise ValidationError('End date must be after start date.')

    def write(self, vals):
        result = super().write(vals)
        if 'start_date' in vals or 'end_date' in vals:
            for term in self:
                if term.start_date and term.end_date:
                    weeks = self.env['aps.academic.week'].search([
                        ('date_start', '>=', term.start_date),
                        ('date_stop', '<=', term.end_date),
                    ])
                    weeks.write({'academic_term_id': term.id})
        return result

    @api.depends('short_name', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.short_name or rec.name
