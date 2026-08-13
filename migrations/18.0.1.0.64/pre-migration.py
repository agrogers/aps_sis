"""Migrate school-calendar level applicability to many-to-many levels."""


def migrate(cr, version):
    cr.execute("""
        CREATE TABLE IF NOT EXISTS aps_school_calendar_level_rel (
            calendar_id integer NOT NULL REFERENCES aps_school_calendar(id) ON DELETE CASCADE,
            level_id integer NOT NULL REFERENCES aps_level(id) ON DELETE CASCADE,
            UNIQUE(calendar_id, level_id)
        )
    """)

    cr.execute("""
        INSERT INTO aps_school_calendar_level_rel (calendar_id, level_id)
        SELECT c.id, c.applies_to_level_id
        FROM aps_school_calendar c
        JOIN aps_level l ON l.id = c.applies_to_level_id
        WHERE c.applies_to_level_id IS NOT NULL
        ON CONFLICT (calendar_id, level_id) DO NOTHING
    """)

    cr.execute("""
        DROP INDEX IF EXISTS aps_school_calendar_applies_to_level_id_index
    """)
    cr.execute("ALTER TABLE aps_school_calendar DROP COLUMN IF EXISTS applies_to_level_id")
