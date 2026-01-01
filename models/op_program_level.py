from odoo import fields, models


class OpProgramLevel(models.Model):
    _inherit = "op.program.level"
    _order = "sequence, name"

    sequence = fields.Integer('Sequence', default=10, help="Determines the display order. Lower values appear first.")
    short_name = fields.Char('Short Name', size=16, help="Abbreviated name (e.g., 'BSc', 'MSc')")
    code = fields.Char('Code', size=8, help="Internal code for the academic level")
