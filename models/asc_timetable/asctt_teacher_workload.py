from odoo import fields, models

from .asctt_flat_row import get_timetable_view_query


class ASCTTTeacherWorkload(models.Model):
    """One row per teacher per timetable card for accurate teacher load."""

    _name = 'asctt.teacher.workload'
    _description = 'aSc Teacher Workload'
    _auto = False
    _rec_name = 'teacher_id'
    _order = 'day, period_id, teacher_id'

    day = fields.Integer(string='Day (1=Mon)', readonly=True)
    day_name = fields.Selection([
        ('Monday', 'Monday'), ('Tuesday', 'Tuesday'),
        ('Wednesday', 'Wednesday'), ('Thursday', 'Thursday'),
        ('Friday', 'Friday'), ('Unknown', 'Unknown'),
    ], string='Day', readonly=True)
    period_id = fields.Many2one('asctt.period', string='Period', readonly=True)
    period_length_minutes = fields.Integer(string='Period Length (min)', readonly=True)
    week_weight = fields.Float(
        string='Week Weight', digits=(3, 2), readonly=True,
        help='',
        )
    weighted_minutes = fields.Float(
        string='Weighted Minutes', digits=(7, 2), readonly=True,
        help='Weighted minutes = period length * week weight',
        )
    teacher_id = fields.Many2one('asctt.teacher', string='aSc Teacher', readonly=True)
    aps_teacher_id = fields.Many2one('aps.teacher', string='APEX Teacher', readonly=True)
    class_names = fields.Char(string='Classes', readonly=True)
    subject_name = fields.Char(string='Subject', readonly=True)
    is_assistant = fields.Boolean(string='Assistant', readonly=True, help="This lesson is taught by this teacher as an assistant, not the main teacher.")
    is_supervision = fields.Boolean(string='Supervision', readonly=True, help="This lesson is a supervision duty, not a teaching lesson.")
    card_id = fields.Many2one('asctt.card', string='Card', readonly=True)
    supervision_id = fields.Many2one(
        'asctt.classroom.supervision', string='Supervision', readonly=True)

    def init(self):
        self.env.cr.execute('DROP VIEW IF EXISTS asctt_teacher_workload CASCADE')
        self.env.cr.execute(get_timetable_view_query('teacher_workload'))
