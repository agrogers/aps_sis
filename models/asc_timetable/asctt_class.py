from odoo import fields, models


class ASCTTClass(models.Model):
    _name = 'asctt.class'
    _description = 'aSc Timetable Class'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    classroom_ids = fields.Many2many(
        'asctt.classroom',
        relation='asctt_class_classroom_rel',
        column1='class_id',
        column2='classroom_id',
        string='Classrooms',
    )
    teacher_id = fields.Many2one(
        'asctt.teacher',
        string='Home Room Teacher',
        ondelete='set null',
    )
    grade = fields.Char(string='Grade', size=20)

    aps_class_identifier = fields.Char(
        string='APEX Class Identifier',
        size=64,
        help='Optional identifier used to document the corresponding APEX class.',
    )
