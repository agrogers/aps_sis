"""
Post-migration: copy Many2many subject relationships from openeducat tables to new aps_sis tables.
Runs AFTER the ORM has updated the database schema (new relation tables now exist).

Copies:
1. aps_resources subject M2M: aps_resources_op_subject_rel -> aps_resources_aps_subject_rel
2. aps_resource_submission subject M2M: op subject rel -> aps subject rel
"""
import logging

_logger = logging.getLogger(__name__)


def _get_subject_name_map(cr):
    """Returns dict: op_subject.id -> aps_subject.id (matched by name)."""
    cr.execute("""
        SELECT op.id AS op_id, s.id AS aps_id
        FROM op_subject op
        JOIN aps_subject s ON LOWER(s.name->>'en_US') = LOWER(op.name::text)
    """)
    return {row[0]: row[1] for row in cr.fetchall()}


def _copy_m2m(cr, old_table, new_table, record_col, old_subject_col, new_subject_col, subject_map):
    """Copy rows from old M2M table to new, remapping subject IDs."""
    cr.execute(f"SELECT {record_col}, {old_subject_col} FROM {old_table}")
    rows = cr.fetchall()
    inserted = 0
    for rec_id, op_subj_id in rows:
        aps_subj_id = subject_map.get(op_subj_id)
        if aps_subj_id is None:
            continue
        cr.execute(
            f"INSERT INTO {new_table} ({record_col}, {new_subject_col}) "
            f"VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (rec_id, aps_subj_id),
        )
        inserted += 1
    return inserted


def migrate(cr, version):
    if not version:
        return  # fresh install

    _logger.info("aps_sis post-migrate 18.0.1.0.53: copying subject M2M relations")

    subject_map = _get_subject_name_map(cr)
    _logger.info("aps_sis post-migrate: mapped %d op_subject -> aps_subject", len(subject_map))

    if not subject_map:
        _logger.warning("aps_sis post-migrate: no subject mapping found, skipping M2M copy")
        return

    # 1. Copy aps_resources subjects M2M
    # Old table: aps_resources_op_subject_rel (aps_resources_id, op_subject_id)
    # New table: aps_resources_aps_subject_rel (aps_resources_id, aps_subject_id)
    cr.execute("SELECT to_regclass('aps_resources_op_subject_rel')")
    if cr.fetchone()[0]:
        cr.execute("SELECT to_regclass('aps_resources_aps_subject_rel')")
        if cr.fetchone()[0]:
            n = _copy_m2m(
                cr,
                "aps_resources_op_subject_rel",
                "aps_resources_aps_subject_rel",
                "aps_resources_id",
                "op_subject_id",
                "aps_subject_id",
                subject_map,
            )
            _logger.info("aps_sis post-migrate: copied %d rows for aps_resources subjects", n)
        else:
            _logger.warning("aps_sis post-migrate: new table aps_resources_aps_subject_rel not found")
    else:
        _logger.info("aps_sis post-migrate: old table aps_resources_op_subject_rel not found, skipping")

    # 2. Copy aps_resource_submission subjects M2M
    # Old: aps_resource_submission_op_subject_rel (aps_resource_submission_id, op_subject_id)
    # New: aps_resource_submission_aps_subject_rel (aps_resource_submission_id, aps_subject_id)
    cr.execute("SELECT to_regclass('aps_resource_submission_op_subject_rel')")
    if cr.fetchone()[0]:
        cr.execute("SELECT to_regclass('aps_resource_submission_aps_subject_rel')")
        if cr.fetchone()[0]:
            n = _copy_m2m(
                cr,
                "aps_resource_submission_op_subject_rel",
                "aps_resource_submission_aps_subject_rel",
                "aps_resource_submission_id",
                "op_subject_id",
                "aps_subject_id",
                subject_map,
            )
            _logger.info("aps_sis post-migrate: copied %d rows for submission subjects", n)
        else:
            _logger.warning("aps_sis post-migrate: new table aps_resource_submission_aps_subject_rel not found")
    else:
        _logger.info("aps_sis post-migrate: old table aps_resource_submission_op_subject_rel not found, skipping")

    # 3. Copy avatar_id from op_student to aps_student.
    # NOTE: avatar_id is a new column on aps_student added in this migration;
    # it only exists after the ORM runs, so it must be copied here, not in pre-migrate.
    cr.execute("""
        UPDATE aps_student AS s
        SET avatar_id = op.avatar_id
        FROM op_student AS op
        WHERE op.partner_id = s.partner_id
          AND op.avatar_id IS NOT NULL
    """)
    _logger.info("aps_sis post-migrate: copied avatar_id from op_student to aps_student")

    _logger.info("aps_sis post-migrate 18.0.1.0.53: done")
