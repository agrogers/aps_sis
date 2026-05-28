"""
Pre-migration 18.0.1.0.54: remap aps_class.subject_id and aps_student_certificate.subject_id
from op_subject IDs to aps_subject IDs.

These columns were missed in the 18.0.1.0.53 migration which performed the
openeducat (op.*) → aps_sis (aps.*) table swap.  As a result, aps_class records
had dangling op_subject IDs stored in subject_id, causing the Subject dropdown
in the Submit a Mark wizard to appear empty.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install

    _logger.info("aps_sis pre-migrate 18.0.1.0.54: remapping aps_class and aps_student_certificate subject_ids")

    _remap_subject_column(cr, 'aps_class', 'subject_id', nullable=True)
    _remap_subject_column(cr, 'aps_student_certificate', 'subject_id', nullable=True)

    _logger.info("aps_sis pre-migrate 18.0.1.0.54: done")


def _remap_subject_column(cr, table, column, nullable=True):
    """Remap a Many2one subject_id column from op_subject IDs to aps_subject IDs.

    Matches records by name (case-insensitive).  Orphaned rows (no matching
    aps_subject) are set to NULL when nullable=True.
    """
    # Check the table exists
    cr.execute("SELECT to_regclass(%s)", (table,))
    if cr.fetchone()[0] is None:
        _logger.info("aps_sis pre-migrate: table %s not found, skipping %s remap", table, column)
        return

    # Drop any FK constraint still pointing to op_subject
    cr.execute("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = %s::regclass
          AND contype = 'f'
          AND conname ILIKE %s
    """, (table, f'%{column}%'))
    fk_row = cr.fetchone()
    if fk_row:
        fk_name = fk_row[0]
        cr.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{fk_name}"')
        _logger.info("aps_sis pre-migrate: dropped FK %s on %s.%s", fk_name, table, column)

    # Build op_subject.id -> aps_subject.id mapping via name match
    cr.execute("""
        SELECT op.id AS op_id, s.id AS aps_id
        FROM op_subject op
        JOIN aps_subject s ON LOWER(s.name->>'en_US') = LOWER(op.name::text)
    """)
    subject_map = {row[0]: row[1] for row in cr.fetchall()}
    if not subject_map:
        _logger.warning(
            "aps_sis pre-migrate: no op_subject -> aps_subject mapping available for %s.%s",
            table, column,
        )
        return

    _logger.info(
        "aps_sis pre-migrate: remapping %s.%s using %d subject entries",
        table, column, len(subject_map),
    )

    for op_id, aps_id in subject_map.items():
        cr.execute(
            f"UPDATE {table} SET {column} = %s WHERE {column} = %s",
            (aps_id, op_id),
        )

    if nullable:
        # NULL out any values that are still old op_subject IDs (no match found)
        cr.execute(f"""
            UPDATE {table}
            SET {column} = NULL
            WHERE {column} NOT IN (SELECT id FROM aps_subject)
              AND {column} IS NOT NULL
        """)

    cr.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL")
    mapped = cr.fetchone()[0]
    _logger.info(
        "aps_sis pre-migrate: %s.%s done — %d rows now reference aps_subject",
        table, column, mapped,
    )
