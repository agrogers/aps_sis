from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    env['ai_prompts'].sudo().ensure_default_targeted_feedback_prompt()
    _migrate_school_calendar_date_types(env)


def _migrate_school_calendar_date_types(env):
    """Remap legacy text date_type values to aps.calendar.date.type records.

    Runs after the data file has seeded the type records. Rows whose legacy
    value doesn't match a known code fall back to 'school_day'.
    """
    cr = env.cr
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aps_school_calendar'
          AND column_name = 'date_type_legacy'
    """)
    if not cr.fetchone():
        return  # nothing to migrate

    DateType = env['aps.calendar.date.type'].sudo()
    code_to_id = {t.code: t.id for t in DateType.search([])}
    fallback_id = code_to_id.get('school_day')

    cr.execute(
        "SELECT id, date_type_legacy FROM aps_school_calendar "
        "WHERE date_type_id IS NULL"
    )
    updates = []
    for row_id, legacy in cr.fetchall():
        updates.append((code_to_id.get(legacy, fallback_id), row_id))
    if updates:
        from psycopg2.extras import execute_values
        # Batch update via join on a temp table
        cr.execute("CREATE TEMP TABLE _legacy_map(id int, type_id int)")
        execute_values(
            cr,
            "INSERT INTO _legacy_map (id, type_id) VALUES %s",
            [(rid, tid) for tid, rid in updates],
        )
        cr.execute("""
            UPDATE aps_school_calendar c
            SET date_type_id = m.type_id
            FROM _legacy_map m
            WHERE c.id = m.id
        """)
        cr.execute("DROP TABLE _legacy_map")
    cr.execute("ALTER TABLE aps_school_calendar DROP COLUMN date_type_legacy")