def migrate(cr, version):
    """Add auto_assign columns to aps_resources if they don't exist yet."""
    cr.execute("""
        ALTER TABLE aps_resources
            ADD COLUMN IF NOT EXISTS auto_assign BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS auto_assign_date DATE,
            ADD COLUMN IF NOT EXISTS auto_assign_end_date DATE,
            ADD COLUMN IF NOT EXISTS auto_assign_frequency INTEGER DEFAULT 7,
            ADD COLUMN IF NOT EXISTS auto_assign_time FLOAT DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS auto_assign_all_students BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS auto_assign_notify_student BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS auto_assign_custom_name VARCHAR,
            ADD COLUMN IF NOT EXISTS auto_assign_log TEXT
    """)
