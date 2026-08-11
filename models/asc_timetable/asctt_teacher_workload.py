from odoo import fields, models

from .asctt_flat_row import (
    _PERIOD_MINUTES_EXPR,
    _TEACHER_FIRST_ID_EXPR,
    _WEEK_WEIGHT_EXPR,
)


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
    week_weight = fields.Float(string='Week Weight', digits=(3, 2), readonly=True)
    weighted_minutes = fields.Float(string='Weighted Minutes', digits=(7, 2), readonly=True)
    teacher_id = fields.Many2one('asctt.teacher', string='aSc Teacher', readonly=True)
    aps_teacher_id = fields.Many2one('aps.teacher', string='APEX Teacher', readonly=True)
    class_names = fields.Char(string='Classes', readonly=True)
    subject_name = fields.Char(string='Subject', readonly=True)
    is_assistant = fields.Boolean(string='Assistant', readonly=True)
    is_supervision = fields.Boolean(string='Supervision', readonly=True)
    card_id = fields.Many2one('asctt.card', string='Card', readonly=True)
    supervision_id = fields.Many2one(
        'asctt.classroom.supervision', string='Supervision', readonly=True)

    def init(self):
        self.env.cr.execute('DROP VIEW IF EXISTS asctt_teacher_workload CASCADE')
        self.env.cr.execute("""
            CREATE VIEW asctt_teacher_workload AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY c.id, t.id) AS id,
                    c.day,
                    CASE c.day
                        WHEN 1 THEN 'Monday' WHEN 2 THEN 'Tuesday'
                        WHEN 3 THEN 'Wednesday' WHEN 4 THEN 'Thursday'
                        WHEN 5 THEN 'Friday' ELSE 'Unknown'
                    END AS day_name,
                    c.period_id,
                    {period_minutes} AS period_length_minutes,
                    {week_weight} AS week_weight,
                    ({period_minutes}) * ({week_weight}) AS weighted_minutes,
                    t.id AS teacher_id,
                    t.aps_teacher_id,
                    classes.class_names,
                    COALESCE(s.name, 'Unknown') AS subject_name,
                    (
                        t.id <> ({teacher_first_id})
                    ) AS is_assistant,
                    FALSE AS is_supervision,
                    c.id AS card_id,
                    NULL::INTEGER AS supervision_id
                FROM asctt_card c
                JOIN asctt_lesson l ON l.id = c.lesson_id
                JOIN asctt_lesson_teacher_rel ltr ON ltr.lesson_id = l.id
                JOIN asctt_teacher t ON t.id = ltr.teacher_id
                LEFT JOIN asctt_period p ON p.id = c.period_id
                LEFT JOIN asctt_weeks_def wd ON wd.id = c.weeks_def_id
                LEFT JOIN asctt_subject s ON s.id = l.subject_id
                LEFT JOIN LATERAL (
                    SELECT STRING_AGG(DISTINCT cls.name, ', ' ORDER BY cls.name) AS class_names
                    FROM asctt_lesson_class_rel lcr
                    JOIN asctt_class cls ON cls.id = lcr.class_id
                    WHERE lcr.lesson_id = l.id
                ) classes ON TRUE

                UNION ALL

                SELECT
                    1000000 + ROW_NUMBER() OVER (ORDER BY sv.id) AS id,
                    sv.day + 1 AS day,
                    CASE sv.day
                        WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday'
                        WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday'
                        WHEN 4 THEN 'Friday' ELSE 'Unknown'
                    END AS day_name,
                    sv.period_id,
                    {period_minutes} AS period_length_minutes,
                    {week_weight} AS week_weight,
                    ({period_minutes}) * ({week_weight}) AS weighted_minutes,
                    t.id AS teacher_id,
                    t.aps_teacher_id,
                    NULL::VARCHAR AS class_names,
                    'Supervision' AS subject_name,
                    TRUE AS is_assistant,
                    TRUE AS is_supervision,
                    NULL::INTEGER AS card_id,
                    sv.id AS supervision_id
                FROM asctt_classroom_supervision sv
                JOIN asctt_teacher t ON t.id = sv.teacher_id
                LEFT JOIN asctt_period p ON p.id = sv.period_id
                LEFT JOIN asctt_weeks_def wd ON wd.id = sv.weeks_def_id
            )
        """.format(
            period_minutes=_PERIOD_MINUTES_EXPR,
            week_weight=_WEEK_WEIGHT_EXPR,
            teacher_first_id=_TEACHER_FIRST_ID_EXPR,
        ))
