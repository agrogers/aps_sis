def migrate(cr, version):
    """
    Pre-migration: Clean up the old Selection field metadata before the field type changes.
    This prevents errors when Odoo tries to process the field change from Selection to Boolean.
    """
    if not version:
        return
    
    # Delete old selection field metadata for aps.assign.details.has_notes
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id IN (
            SELECT id FROM ir_model_fields
            WHERE name = 'has_notes'
            AND model_id IN (
                SELECT id FROM ir_model WHERE model IN ('aps.assign.details', 'aps.assign.students.wizard')
            )
        )
    """)
