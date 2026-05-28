"""
Pre-migration: remap foreign keys from openeducat_core models to aps_sis core models.
Runs BEFORE the ORM updates the database schema.

Remaps:
1. aps_resource_submission.assigned_by: op_faculty.id -> aps_teacher.id (matched via emp_id)
2. aps_submission_reviewed_by_rel.faculty_id: op_faculty.id -> aps_teacher.id
3. aps_submission_review_request_rel.faculty_id: op_faculty.id -> aps_teacher.id
4. aps_student.avatar_id: copy from op_student.avatar_id matched via partner_id
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install, no migration needed

    _logger.info("aps_sis pre-migrate 18.0.1.0.53: remapping openeducat FK references")

    # 1. Build op_faculty.id -> aps_teacher.id mapping (via shared partner_id).
    # NOTE: aps_teacher.emp_id is a new column added in this migration — it does not
    # exist yet when pre-migrate runs, so we match via partner_id instead.
    cr.execute("""
        SELECT f.id AS op_id, t.id AS aps_id
        FROM op_faculty f
        JOIN aps_teacher t ON t.partner_id = f.partner_id
        WHERE f.partner_id IS NOT NULL
    """)
    faculty_map = {row[0]: row[1] for row in cr.fetchall()}
    _logger.info("aps_sis pre-migrate: mapped %d op_faculty -> aps_teacher", len(faculty_map))

    if faculty_map:
        # 2. Remap aps_resource_submission.assigned_by
        for op_id, aps_id in faculty_map.items():
            cr.execute(
                "UPDATE aps_resource_submission SET assigned_by = %s WHERE assigned_by = %s",
                (aps_id, op_id),
            )

        # 3. Remap aps_submission_reviewed_by_rel.faculty_id
        for op_id, aps_id in faculty_map.items():
            cr.execute(
                "UPDATE aps_submission_reviewed_by_rel SET faculty_id = %s WHERE faculty_id = %s",
                (aps_id, op_id),
            )

        # 4. Remap aps_submission_review_request_rel.faculty_id
        for op_id, aps_id in faculty_map.items():
            cr.execute(
                "UPDATE aps_submission_review_request_rel SET faculty_id = %s WHERE faculty_id = %s",
                (aps_id, op_id),
            )

    # 5. Remap aps_time_tracking.subject_id
    _remap_time_tracking_subjects(cr)

    # 6. Remap aps_class.subject_id (single M2O column)
    _remap_subject_column(cr, 'aps_class', 'subject_id', nullable=True)

    # 7. Remap aps_student_certificate.subject_id (single M2O column, nullable)
    _remap_subject_column(cr, 'aps_student_certificate', 'subject_id', nullable=True)

    _logger.info("aps_sis pre-migrate 18.0.1.0.53: done")


def _remap_time_tracking_subjects(cr):
    """Remap aps_time_tracking.subject_id from op_subject.id -> aps_subject.id.

    aps_time_tracking.subject_id previously stored op_subject primary keys.
    After the table swap, it must reference aps_subject.  Match by name.
    Rows whose op_subject has no aps_subject counterpart are NULLed out
    (the field is required on the ORM side but the constraint is applied after
    pre-migrate, so NULLing here lets Odoo proceed; those rows will need
    manual cleanup after upgrade).
    """
    # Drop the existing FK constraint that still points to op_subject so we can
    # freely update subject_id values to aps_subject IDs.  Odoo will re-create
    # the correct FK (pointing to aps_subject) after the migration completes.
    cr.execute("""
        ALTER TABLE aps_time_tracking
        DROP CONSTRAINT IF EXISTS aps_time_tracking_subject_id_fkey
    """)
    _logger.info("aps_sis pre-migrate: dropped aps_time_tracking_subject_id_fkey")

    # Build op_subject.id -> aps_subject.id via name match
    cr.execute("""
        SELECT op.id AS op_id, s.id AS aps_id
        FROM op_subject op
        JOIN aps_subject s ON LOWER(s.name->>'en_US') = LOWER(op.name::text)
    """)
    subject_map = {row[0]: row[1] for row in cr.fetchall()}
    _logger.info(
        "aps_sis pre-migrate: subject map contains %d entries", len(subject_map)
    )

    if not subject_map:
        _logger.warning(
            "aps_sis pre-migrate: no op_subject -> aps_subject mapping found; "
            "nulling all aps_time_tracking.subject_id values to unblock FK"
        )
        cr.execute("UPDATE aps_time_tracking SET subject_id = NULL")
        return

    # Remap matched rows
    for op_id, aps_id in subject_map.items():
        cr.execute(
            "UPDATE aps_time_tracking SET subject_id = %s WHERE subject_id = %s",
            (aps_id, op_id),
        )

    # NULL out any remaining unmapped subject_ids (orphaned op_subject refs)
    cr.execute("""
        UPDATE aps_time_tracking
        SET subject_id = NULL
        WHERE subject_id NOT IN (SELECT id FROM aps_subject)
          AND subject_id IS NOT NULL
    """)
    cr.execute("SELECT COUNT(*) FROM aps_time_tracking WHERE subject_id IS NULL")
    nulled = cr.fetchone()[0]
    if nulled:
        _logger.warning(
            "aps_sis pre-migrate: %d aps_time_tracking rows could not be remapped "
            "(op_subject had no matching aps_subject) — subject_id set to NULL",
            nulled,
        )


def _remap_subject_column(cr, table, column, nullable=True):
    """Generic helper: remap a single Many2one subject_id column from op_subject IDs
    to aps_subject IDs, matching by name.  Safe to call even if the table/column
    doesn't exist yet or has no rows pointing to op_subject.

    Args:
        cr: database cursor
        table: DB table name (e.g. 'aps_class')
        column: column name (e.g. 'subject_id')
        nullable: if True, orphaned rows are set to NULL; if False they are left
                  (caller is responsible for cleanup).
    """
    # Check the table exists before touching it
    cr.execute("SELECT to_regclass(%s)", (table,))
    if cr.fetchone()[0] is None:
        _logger.info("aps_sis pre-migrate: table %s not found, skipping %s remap", table, column)
        return

    # Drop any FK constraint pointing to op_subject so we can freely rewrite the values
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
            "aps_sis pre-migrate: no op_subject -> aps_subject mapping for %s.%s", table, column
        )
        return

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
        "aps_sis pre-migrate: %s.%s remapped — %d rows now reference aps_subject",
        table, column, mapped,
    )
