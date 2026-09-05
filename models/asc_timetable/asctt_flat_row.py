from odoo import fields, models

# SQL column name for asctt.days.def → table asctt_days_def
# SQL column name for asctt.weeks.def → table asctt_weeks_def

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

_TEACHER_FIRST_ID_EXPR = """
    COALESCE(
        NULLIF(SPLIT_PART(l.teacher_order, ',', 1), '')::INTEGER,
        (
            SELECT MIN(ltr2.teacher_id)
            FROM asctt_lesson_teacher_rel ltr2
            WHERE ltr2.lesson_id = l.id
        )
    )
""".strip()


def get_timetable_view_query(view_name):
    """Return the SQL for one of the related timetable workload views.

    Keep both view definitions here because changes to timetable workload
    calculations may need to be applied to both views.
    """
    queries = {
        'flat_row': """
            CREATE VIEW asctt_flat_row AS (
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
                    cls.id AS class_id,
                    NULL::INTEGER AS aps_class_id,
                    CASE WHEN cls.id IS NULL THEN 'Supervision'
                         ELSE COALESCE(s.name, 'Unknown') END AS subject_name,
                    (t.id <> ({teacher_first_id})
                     OR cls.id IS NULL
                     OR COALESCE(s.force_assistant, FALSE)) AS is_assistant,
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
                LEFT JOIN asctt_lesson_class_rel lcr ON lcr.lesson_id = l.id
                LEFT JOIN asctt_class cls ON cls.id = lcr.class_id

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
                    NULL::INTEGER AS class_id,
                    NULL::INTEGER AS aps_class_id,
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
        """,
        'teacher_workload': """
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
                    (t.id <> ({teacher_first_id})
                     OR COALESCE(s.force_assistant, FALSE)) AS is_assistant,
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
        """,
    }
    return queries[view_name].format(
        period_minutes=_PERIOD_MINUTES_EXPR,
        week_weight=_WEEK_WEIGHT_EXPR,
        teacher_first_id=_TEACHER_FIRST_ID_EXPR,
    )


class ASCTTFlatRow(models.Model):
    """Read-only SQL view providing one row per teacher per card/supervision.

    Designed for Odoo pivot-table workload analysis.  Mirrors the CSV export
    produced by the legacy Python script (Day, Period, Period Length in Minutes,
    Week, Single Teacher, Class, Is Assistant, Subject Name) and adds APEX links.
    """

    _name = 'asctt.flat.row'
    _description = 'aSc Timetable Flat Row (Pivot)'
    _auto = False
    _rec_name = 'subject_name'
    _order = 'day, period_id, teacher_id'

    # ── Core timetable fields ──────────────────────────────────────────────────
    day = fields.Integer(string='Day (1=Mon)', readonly=True)
    day_name = fields.Selection([
        ('Monday',    'Monday'),
        ('Tuesday',   'Tuesday'),
        ('Wednesday', 'Wednesday'),
        ('Thursday',  'Thursday'),
        ('Friday',    'Friday'),
        ('Unknown',   'Unknown'),
    ], string='Day', readonly=True)
    period_id = fields.Many2one('asctt.period', string='Period', readonly=True)
    period_length_minutes = fields.Integer(string='Period Length (min)', readonly=True)
    week_weight = fields.Float(string='Week Weight', digits=(3, 2), readonly=True,
                               help='1.0 = every week, 0.5 = alternating week')
    weighted_minutes = fields.Float(
        string='Weighted Minutes', digits=(7, 2), readonly=True,
        help='period_length_minutes × week_weight — use this as the pivot measure '
             'so that alternate-week lessons contribute half their minutes per week.',
    )

    # ── Teacher ────────────────────────────────────────────────────────────────
    teacher_id = fields.Many2one('asctt.teacher', string='aSc Teacher', readonly=True)
    aps_teacher_id = fields.Many2one('aps.teacher', string='APEX Teacher', readonly=True)

    # ── Class / Subject ────────────────────────────────────────────────────────
    class_id = fields.Many2one('asctt.class', string='aSc Class', readonly=True)
    aps_class_id = fields.Many2one('aps.class', string='APEX Class', readonly=True)
    subject_name = fields.Char(string='Subject', readonly=True)

    # ── Flags ──────────────────────────────────────────────────────────────────
    is_assistant = fields.Boolean(string='Is Assistant', readonly=True)
    is_supervision = fields.Boolean(string='Is Supervision', readonly=True)

    # ── Source links (nullable) ────────────────────────────────────────────────
    card_id = fields.Many2one('asctt.card', string='Card', readonly=True)
    supervision_id = fields.Many2one(
        'asctt.classroom.supervision', string='Supervision', readonly=True)

    # ── SQL view definition ────────────────────────────────────────────────────

    def init(self):
        # Keep this view's SQL beside the related teacher-workload view above.
        self.env.cr.execute("DROP VIEW IF EXISTS asctt_flat_row CASCADE")
        self.env.cr.execute(get_timetable_view_query('flat_row'))
