from odoo import fields, models


class ASCTTDaysDef(models.Model):
    _name = 'asctt.days.def'
    _description = 'aSc Timetable Days Definition'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    days = fields.Char(string='Days Pattern', help='Comma-separated binary day patterns, e.g. "10000" for Monday')
