from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Recompute task states from their submissions using the updated priority logic."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    tasks = env['aps.resource.task'].search([])
    tasks._update_state_from_submissions()
