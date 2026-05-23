from odoo import fields, models


class ASCTTLesson(models.Model):
    _name = 'asctt.lesson'
    _description = 'aSc Timetable Lesson'
    _order = 'id'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    subject_id = fields.Many2one(
        'asctt.subject',
        string='Subject',
        ondelete='set null',
    )
    class_ids = fields.Many2many(
        'asctt.class',
        relation='asctt_lesson_class_rel',
        column1='lesson_id',
        column2='class_id',
        string='Classes',
    )
    group_ids = fields.Many2many(
        'asctt.group',
        relation='asctt_lesson_group_rel',
        column1='lesson_id',
        column2='group_id',
        string='Groups',
    )
    teacher_ids = fields.Many2many(
        'asctt.teacher',
        relation='asctt_lesson_teacher_rel',
        column1='lesson_id',
        column2='teacher_id',
        string='Teachers',
    )
    classroom_ids = fields.Many2many(
        'asctt.classroom',
        relation='asctt_lesson_classroom_rel',
        column1='lesson_id',
        column2='classroom_id',
        string='Classrooms',
    )
    periods_per_card = fields.Integer(string='Periods per Card')
    periods_per_week = fields.Float(string='Periods per Week')
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
    terms_def_id = fields.Many2one(
        'asctt.terms.def',
        string='Terms Definition',
        ondelete='set null',
    )
    seminar_group = fields.Char(string='Seminar Group')
    capacity = fields.Char(string='Capacity', size=20)
