from odoo import api, SUPERUSER_ID

def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    records1 = env['aps.resources'].search([])
    records1._compute_subject_icons()
    records1._compute_type_icon()

    records2 = env['aps.resource.submission'].search([])
    records2._compute_subject_icons()
    records2._compute_type_icon()

    env.cr.commit()


