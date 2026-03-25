def migrate(cr, version):
    """Create aps_avatar_category and aps_avatar tables, and add avatar_id to op_student."""
    cr.execute("""
        CREATE TABLE IF NOT EXISTS aps_avatar_category (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            create_uid INTEGER,
            create_date TIMESTAMP WITHOUT TIME ZONE,
            write_uid INTEGER,
            write_date TIMESTAMP WITHOUT TIME ZONE
        )
    """)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS aps_avatar (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            image BYTEA,
            category_id INTEGER REFERENCES aps_avatar_category(id),
            create_uid INTEGER,
            create_date TIMESTAMP WITHOUT TIME ZONE,
            write_uid INTEGER,
            write_date TIMESTAMP WITHOUT TIME ZONE
        )
    """)
    cr.execute("""
        ALTER TABLE op_student
            ADD COLUMN IF NOT EXISTS avatar_id INTEGER REFERENCES aps_avatar(id)
    """)
