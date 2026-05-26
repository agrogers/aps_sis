from odoo import fields, models


class ASCTTClassroomSupervision(models.Model):
    _name = 'asctt.classroom.supervision'
    _description = 'aSc Timetable Classroom Supervision'
    _order = 'id'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    teacher_id = fields.Many2one(
        'asctt.teacher',
        string='Teacher',
        ondelete='set null',
    )
    classroom_id = fields.Many2one(
        'asctt.classroom',
        string='Classroom',
        ondelete='set null',
    )
    period_id = fields.Many2one(
        'asctt.period',
        string='Period',
        ondelete='set null',
    )
    day = fields.Integer(string='Day Index', help='Raw 0-indexed day from aSc XML (0=Monday, 4=Friday)')
    days_def_id = fields.Many2one(
        'asctt.days.def',
        string='Days Definition',
        ondelete='set null',
    )
    weeks_def_id = fields.Many2one(
        'asctt.weeks.def',
        string='Weeks Definition',
        ondelete='set null',
    )
