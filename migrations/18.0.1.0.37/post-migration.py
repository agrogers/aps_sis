"""Post-migration: restore out_of_marks data and backfill any NULLs from resource.

Steps:
  1. Copy preserved values from the backup column into the new regular column.
  2. For any remaining NULLs (shouldn't happen, but safety net), fill from the
     linked resource's marks field via the task relationship.
  3. Drop the temporary backup column.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Check if the backup column exists
    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'aps_resource_submission'
          AND column_name = '_out_of_marks_backup'
    """)
    if cr.fetchone():
        _logger.info("post-migration: restoring out_of_marks from backup column")
        cr.execute("""
            UPDATE aps_resource_submission
            SET out_of_marks = _out_of_marks_backup
            WHERE _out_of_marks_backup IS NOT NULL
        """)
        updated = cr.rowcount
        _logger.info("post-migration: restored %d rows from backup", updated)

        # Drop the backup column
        cr.execute("""
            ALTER TABLE aps_resource_submission
            DROP COLUMN _out_of_marks_backup
        """)
        _logger.info("post-migration: dropped _out_of_marks_backup column")

    # Backfill any NULLs from the linked resource's marks
    cr.execute("""
        UPDATE aps_resource_submission sub
        SET out_of_marks = r.marks
        FROM aps_resource_task t
        JOIN aps_resources r ON r.id = t.resource_id
        WHERE sub.task_id = t.id
          AND (sub.out_of_marks IS NULL OR sub.out_of_marks = 0)
          AND r.marks IS NOT NULL
          AND r.marks != 0
    """)
    backfilled = cr.rowcount
    if backfilled:
        _logger.info("post-migration: backfilled out_of_marks for %d rows from resource", backfilled)
