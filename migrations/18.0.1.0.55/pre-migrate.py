"""
Pre-migration 18.0.1.0.55: add notes column to aps_student_class.

aps.student now inherits mail.thread and mail.activity.mixin (handled
automatically by Odoo's ORM during upgrade).  The notes column on
aps_student_class is added here so it is available before any data
migration steps that may reference it.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — ORM creates columns on init

    _logger.info("aps_sis pre-migrate 18.0.1.0.55: adding notes column to aps_student_class")

    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'aps_student_class'
          AND column_name = 'notes'
    """)
    if not cr.fetchone():
        cr.execute("ALTER TABLE aps_student_class ADD COLUMN notes text")
        _logger.info("aps_sis pre-migrate 18.0.1.0.55: notes column added")
    else:
        _logger.info("aps_sis pre-migrate 18.0.1.0.55: notes column already exists, skipping")
