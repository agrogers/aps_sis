from odoo import fields, models

# Reuse the same expressions from asctt_flat_row
_WEEK_WEIGHT_EXPR = """
    CASE WHEN wd.weeks IN ('10', '01') THEN 0.5 ELSE 1.0 END
""".strip()

_PERIOD_MINUTES_EXPR = """
    CASE
        WHEN NULLIF(p.starttime, '') IS NOT NULL
             AND NULLIF(p.endtime, '') IS NOT NULL
        THEN ROUND(
            EXTRACT(EPOCH FROM (
                NULLIF(p.endtime, '')::TIME - NULLIF(p.starttime, '')::TIME
            )) / 60
        )::INTEGER
        ELSE NULL
    END
""".strip()


class ASCTTClassSubjectMinutes(models.Model):
    """Read-only SQL view: one row per (class, subject).

    Unlike ``asctt.flat.row`` (which creates one row per *teacher* per card
    and over-counts when multiple teachers share a lesson), this view does
    NOT join the teacher relation at all.  Each card contributes exactly once
    per class it is assigned to, so the sum per class/subject is correct
    regardless of co-teaching.
    """

    _name = 'asctt.class.subject.minutes'
    _description = 'Timetable Minutes by Class and Subject'
    _auto = False
    _rec_name = 'subject_name'
    _order = 'class_name, subject_name'

    # ── Class ──────────────────────────────────────────────────────────────────
    class_id = fields.Many2one('asctt.class', string='aSc Class', readonly=True)
    aps_class_id = fields.Many2one('aps.class', string='APEX Class', readonly=True)
    class_name = fields.Char(string='Class Name', readonly=True)

    # ── Subject ────────────────────────────────────────────────────────────────
    subject_id = fields.Many2one('asctt.subject', string='Subject', readonly=True)
    subject_name = fields.Char(string='Subject Name', readonly=True)

    # ── Aggregated measures ────────────────────────────────────────────────────
    total_weighted_minutes = fields.Float(
        string='Minutes/Week', digits=(7, 2), readonly=True,
        help='Total weekly minutes for this class+subject. '
             'Unlike the teacher-level flat view, each card contributes only once '
             'per class, so co-taught lessons are not over-counted.')
    period_slots_per_week = fields.Float(
        string='Periods/Week', digits=(5, 2), readonly=True,
        help='Number of period slots per week respecting week weights.')

    # ── SQL view definition ────────────────────────────────────────────────────

    def init(self):
        self.env.cr.execute(
            "DROP VIEW IF EXISTS asctt_class_subject_minutes CASCADE")
        self.env.cr.execute("""
            CREATE VIEW asctt_class_subject_minutes AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY cls.id, COALESCE(s.id, 0)) AS id,

                    cls.id          AS class_id,
                    cls.aps_class_id,
                    cls.name        AS class_name,

                    s.id            AS subject_id,
                    COALESCE(s.name, 'Unknown') AS subject_name,

                    SUM(
                        ({period_minutes})
                        * ({week_weight})
                    ) AS total_weighted_minutes,

                    SUM({week_weight}) AS period_slots_per_week

                FROM asctt_card c
                JOIN asctt_lesson l ON l.id = c.lesson_id
                LEFT JOIN asctt_subject s ON s.id = l.subject_id
                LEFT JOIN asctt_period p ON p.id = c.period_id
                LEFT JOIN asctt_weeks_def wd ON wd.id = c.weeks_def_id
                LEFT JOIN asctt_lesson_class_rel lcr ON lcr.lesson_id = l.id
                LEFT JOIN asctt_class cls ON cls.id = lcr.class_id
                WHERE cls.id IS NOT NULL
                GROUP BY cls.id, cls.aps_class_id, cls.name,
                         s.id, s.name
            )
        """.format(
            period_minutes=_PERIOD_MINUTES_EXPR,
            week_weight=_WEEK_WEIGHT_EXPR,
        ))
