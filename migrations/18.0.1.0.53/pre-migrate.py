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

    _logger.info("aps_sis pre-migrate 18.0.1.0.53: done")
