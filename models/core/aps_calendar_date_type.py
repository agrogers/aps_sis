from odoo import api, fields, models, _


class ApsCalendarDateType(models.Model):
    _name = 'aps.calendar.date.type'
    _description = 'School Calendar Date Type'
    _order = 'sequence, name'
    _rec_name = 'name'

    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Code',
        required=True,
        index=True,
        help='Stable technical key used by code and imports (e.g. school_day). '
             'Do not change after creation.',
    )
    name = fields.Char(string='Name', required=True)
    icon = fields.Image(
        string='Icon',
        max_width=64,
        max_height=64,
        help='Icon displayed for calendar entries of this type.',
    )
    print_color = fields.Char(
        string='Print Color',
        default='#FFFFFF',
        help='Hex colour code used in the printable calendar report, e.g. #3F80D0.',
    )
    color = fields.Integer(
        string='Color Index',
        default=0,
        help='Odoo palette colour index (0-11) used by calendar/kanban views.',
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Date type code must be unique.'),
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or rec.code or ''

    def _load_type_map(self):
        """Return {code: record} for all active date types."""
        return {t.code: t for t in self.search([])}

    @api.model
    def get_by_code(self, code):
        """Return the date type record for a code, or empty recordset."""
        return self.search([('code', '=', code)], limit=1)
