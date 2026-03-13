"""Pre-migration: preserve out_of_marks data when converting from related to regular field.

When a stored related field is changed to a regular field, Odoo may drop and
recreate the column, losing all existing data.  To prevent this we:
  1. Rename the column to a temporary name before Odoo touches the schema.
  2. The post-migration will copy the data back after the new column is created.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Check if column exists (it should, since it was stored)
    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'aps_resource_submission'
          AND column_name = 'out_of_marks'
    """)
    if cr.fetchone():
        _logger.info("pre-migration: renaming out_of_marks → _out_of_marks_backup")
        cr.execute("""
            ALTER TABLE aps_resource_submission
            RENAME COLUMN out_of_marks TO _out_of_marks_backup
        """)
    else:
        _logger.info("pre-migration: out_of_marks column not found, nothing to backup")
