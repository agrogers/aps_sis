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

    # APEX link
    aps_class_id = fields.Many2one(
        'aps.class',
        string='APEX Class',
        ondelete='set null',
        help='Link to the corresponding APEX Class record.',
    )
