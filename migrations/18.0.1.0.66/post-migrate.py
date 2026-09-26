"""Map legacy student enrolment status keys to configurable status records."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aps_student' AND column_name = 'enrolment_status_legacy'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        SELECT id FROM aps_student_enrolment_status
        WHERE code = 'enrolled'
        LIMIT 1
    """)
    enrolled_status = cr.fetchone()
    if not enrolled_status:
        raise RuntimeError('The Enrolled student status record is missing.')

    cr.execute("""
        UPDATE aps_student AS student
        SET enrolment_status = status.id
        FROM aps_student_enrolment_status AS status
        WHERE status.code = CASE
            WHEN student.enrolment_status_legacy = 'finished' THEN 'completed'
            ELSE student.enrolment_status_legacy
        END
    """)
    cr.execute("""
        UPDATE aps_student
        SET enrolment_status = %s
        WHERE enrolment_status IS NULL
    """, enrolled_status)
    cr.execute("ALTER TABLE aps_student ALTER COLUMN enrolment_status SET NOT NULL")
    cr.execute("ALTER TABLE aps_student DROP COLUMN enrolment_status_legacy")