def migrate(cr, version):
    """
    Remove all selection values for the has_question field on aps.assign.students.wizard.
    This is safe for upgrades and works regardless of the field_id value.
    """
    if not version:
        return

    # Get the model id for aps.assign.students.wizard
    cr.execute("""
        SELECT id FROM ir_model WHERE model = %s
    """, ('aps.assign.students.wizard',))
    model_row = cr.fetchone()
    if not model_row:
        return
    model_id = model_row[0]

    # Get the field id for has_question on that model
    cr.execute("""
        SELECT id FROM ir_model_fields
        WHERE model_id = %s AND name = %s
    """, (model_id, 'has_question'))
    field_row = cr.fetchone()
    if not field_row:
        return
    field_id = field_row[0]

    # Delete all selection values for that field
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id = %s
    """, (field_id,))

    # Get the field id for has_answer on that model
    cr.execute("""
        SELECT id FROM ir_model_fields
        WHERE model_id = %s AND name = %s
    """, (model_id, 'has_answer'))
    field_row = cr.fetchone()
    if not field_row:
        return
    field_id = field_row[0]

    # Delete all selection values for that field
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id = %s
    """, (field_id,))    

    #################################################

    # Get the model id for aps.resource.submission
    cr.execute("""
        SELECT id FROM ir_model WHERE model = %s
    """, ('aps.resource.submission',))
    model_row = cr.fetchone()
    if not model_row:
        return
    model_id = model_row[0]

    # Get the field id for has_question on that model
    cr.execute("""
        SELECT id FROM ir_model_fields
        WHERE model_id = %s AND name = %s
    """, (model_id, 'has_question'))
    field_row = cr.fetchone()
    if not field_row:
        return
    field_id = field_row[0]

    # Delete all selection values for that field
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id = %s
    """, (field_id,))

    # Get the field id for has_answer on that model
    cr.execute("""
        SELECT id FROM ir_model_fields
        WHERE model_id = %s AND name = %s
    """, (model_id, 'has_answer'))
    field_row = cr.fetchone()
    if not field_row:
        return
    field_id = field_row[0]

    # Delete all selection values for that field
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id = %s
    """, (field_id,))  
