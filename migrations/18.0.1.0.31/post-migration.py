from odoo import api, SUPERUSER_ID

def migrate(cr, version):
    """Recalculate submission stats and type_icon for all tasks."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    
    # Recompute submission_stats and type_icon for all tasks
    tasks = env['aps.resource.task'].search([])
    tasks._compute_submission_stats()
    tasks._compute_type_icon()
    
    env.cr.commit()
