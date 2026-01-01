from odoo import fields, models


class OpCourse(models.Model):
    _inherit = "op.course"
    _order = "sequence, name"

    sequence = fields.Integer('Sequence', default=10, help="Determines the display order. Lower values appear first.")
    short_name = fields.Char('Short Name', size=16, help="Abbreviated name (e.g., 'Y1', 'Y2')")
