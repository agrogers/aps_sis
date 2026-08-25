"""Pre-migration for calendar date-type table conversion.

Preserves the legacy text column `date_type` as `date_type_legacy` so the
post-init hook can remap rows to the new aps.calendar.date.type records
before Odoo's schema sync would otherwise drop it.
"""


def migrate(cr, version):
    # Does the legacy column exist?
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aps_school_calendar' AND column_name = 'date_type'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aps_school_calendar'
          AND column_name = 'date_type_legacy'
    """)
    if cr.fetchone():
        return
    cr.execute(
        "ALTER TABLE aps_school_calendar RENAME COLUMN date_type TO date_type_legacy"
    )
