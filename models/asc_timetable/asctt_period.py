from odoo import fields, models


class ASCTTPeriod(models.Model):
    _name = 'asctt.period'
    _description = 'aSc Timetable Period'
    _order = 'period'

    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    period = fields.Integer(string='Period Number')
    starttime = fields.Char(string='Start Time', size=10, help='Format: HH:MM')
    endtime = fields.Char(string='End Time', size=10, help='Format: HH:MM')
