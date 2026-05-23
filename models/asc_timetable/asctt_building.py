from odoo import fields, models


class ASCTTBuilding(models.Model):
    _name = 'asctt.building'
    _description = 'aSc Timetable Building'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
