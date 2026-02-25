def migrate(cr, version):
    """
    Post-migration: Clean up old field metadata to prevent errors during module update.
    The field type change from Selection to Boolean is handled automatically by Odoo,
    but we need to ensure the old selection values don't cause issues.
    """
    if not version:
        return
    
    # Delete old selection field metadata that might cause conflicts
    # This is safer than trying to alter the column type directly
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id IN (
            SELECT id FROM ir_model_fields
            WHERE name = 'has_notes'
            AND model_id IN (
                SELECT id FROM ir_model 
                WHERE model IN ('aps.assign.details', 'aps.assign.students.wizard')
            )
        )
    """)

