from odoo import fields, models


class ASCTTCard(models.Model):
    _name = 'asctt.card'
    _description = 'aSc Timetable Card'
    _order = 'lesson_id, day, period_id'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    lesson_id = fields.Many2one(
        'asctt.lesson',
        string='Lesson',
        ondelete='cascade',
    )
    period_id = fields.Many2one(
        'asctt.period',
        string='Period',
        ondelete='set null',
    )
    day = fields.Integer(string='Day', help='Day of week (1=Monday, 5=Friday)')
    weeks_def_id = fields.Many2one(
        'asctt.weeks.def',
        string='Weeks Definition',
        ondelete='set null',
    )
    classroom_ids = fields.Many2many(
        'asctt.classroom',
        relation='asctt_card_classroom_rel',
        column1='card_id',
        column2='classroom_id',
        string='Classrooms',
    )
    teacher_ids = fields.Many2many(
        'asctt.teacher',
        relation='asctt_card_teacher_rel',
        column1='card_id',
        column2='teacher_id',
        string='Teachers',
    )
