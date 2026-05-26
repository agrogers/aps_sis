from odoo import fields, models


class ASCTTClassroom(models.Model):
    _name = 'asctt.classroom'
    _description = 'aSc Timetable Classroom'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    capacity = fields.Char(string='Capacity', size=20, help='Capacity or * for unlimited')
    building_id = fields.Many2one(
        'asctt.building',
        string='Building',
        ondelete='set null',
    )
