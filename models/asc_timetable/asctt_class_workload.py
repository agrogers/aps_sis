from odoo import fields, models

from .asctt_flat_row import _PERIOD_MINUTES_EXPR, _WEEK_WEIGHT_EXPR


class ASCTTClassWorkload(models.Model):
    """One row per class per timetable card for accurate class load."""

    _name = 'asctt.class.workload'
    _description = 'aSc Class Workload'
    _auto = False
    _rec_name = 'class_id'
    _order = 'day, period_id, class_id'

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
    class_id = fields.Many2one('asctt.class', string='aSc Class', readonly=True)
    aps_class_id = fields.Many2one('aps.class', string='APEX Class', readonly=True)
    teacher_names = fields.Char(string='Teachers', readonly=True)
    subject_name = fields.Char(string='Subject', readonly=True)
    card_id = fields.Many2one('asctt.card', string='Card', readonly=True)

    def init(self):
        self.env.cr.execute('DROP VIEW IF EXISTS asctt_class_workload CASCADE')
        self.env.cr.execute("""
            CREATE VIEW asctt_class_workload AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY c.id, cls.id) AS id,
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
                    cls.id AS class_id,
                    NULL::INTEGER AS aps_class_id,
                    teachers.teacher_names,
                    COALESCE(s.name, 'Unknown') AS subject_name,
                    c.id AS card_id
                FROM asctt_card c
                JOIN asctt_lesson l ON l.id = c.lesson_id
                JOIN asctt_lesson_class_rel lcr ON lcr.lesson_id = l.id
                JOIN asctt_class cls ON cls.id = lcr.class_id
                LEFT JOIN asctt_period p ON p.id = c.period_id
                LEFT JOIN asctt_weeks_def wd ON wd.id = c.weeks_def_id
                LEFT JOIN asctt_subject s ON s.id = l.subject_id
                LEFT JOIN LATERAL (
                    SELECT STRING_AGG(DISTINCT t.name, ', ' ORDER BY t.name) AS teacher_names
                    FROM asctt_lesson_teacher_rel ltr
                    JOIN asctt_teacher t ON t.id = ltr.teacher_id
                    WHERE ltr.lesson_id = l.id
                ) teachers ON TRUE
            )
        """.format(
            period_minutes=_PERIOD_MINUTES_EXPR,
            week_weight=_WEEK_WEIGHT_EXPR,
        ))
