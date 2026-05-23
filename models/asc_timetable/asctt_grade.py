from odoo import fields, models


class ASCTTGrade(models.Model):
    _name = 'asctt.grade'
    _description = 'aSc Timetable Grade'
    _order = 'grade'

    grade = fields.Integer(string='Grade Number', required=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)

    # APEX link
    aps_level_id = fields.Many2one(
        'aps.level',
        string='APEX Academic Level',
        ondelete='set null',
        help='Link to the corresponding APEX Academic Level record.',
    )
