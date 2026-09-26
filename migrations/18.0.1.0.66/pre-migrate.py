"""Preserve student enrolment status keys before converting the field to Many2one."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aps_student' AND column_name = 'enrolment_status'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aps_student' AND column_name = 'enrolment_status_legacy'
    """)
    if cr.fetchone():
        return

    cr.execute(
        "ALTER TABLE aps_student RENAME COLUMN enrolment_status TO enrolment_status_legacy"
    )