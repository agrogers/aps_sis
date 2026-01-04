from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    """Hook to conditionally create fees-related views only if fees module is installed"""
    # Check if fees module is installed
    if env['ir.module.module'].search([('name', '=', 'openeducat_fees'), ('state', '=', 'installed')]):
        # Create the view records for making fees_term_id optional
        env['ir.ui.view'].create({
            'name': 'op.course.list.fees.optional.aps',
            'model': 'op.course',
            'inherit_id': env.ref('openeducat_fees.view_op_course_tree_pt_inherit').id,
            'priority': 20,
            'arch': '''
                <xpath expr="//field[@name='fees_term_id']" position="attributes">
                    <attribute name="required">0</attribute>
                    <attribute name="optional">hide</attribute>
                </xpath>
            '''
        })

        env['ir.ui.view'].create({
            'name': 'op.course.form.fees.optional.aps',
            'model': 'op.course',
            'inherit_id': env.ref('openeducat_fees.view_op_course_form_pt_inherit').id,
            'priority': 20,
            'arch': '''
                <xpath expr="//field[@name='fees_term_id']" position="attributes">
                    <attribute name="required">0</attribute>
                </xpath>
            '''
        })