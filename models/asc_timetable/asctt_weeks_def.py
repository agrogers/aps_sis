from odoo import fields, models


class ASCTTWeeksDef(models.Model):
    _name = 'asctt.weeks.def'
    _description = 'aSc Timetable Weeks Definition'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    weeks = fields.Char(string='Weeks Pattern', help='Comma-separated binary week patterns, e.g. "10" for Week A')
