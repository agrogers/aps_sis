from odoo import fields, models


class ASCTTBreak(models.Model):
    _name = 'asctt.break'
    _description = 'aSc Timetable Break'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    starttime = fields.Char(string='Start Time', size=10, help='Format: HH:MM')
    endtime = fields.Char(string='End Time', size=10, help='Format: HH:MM')
