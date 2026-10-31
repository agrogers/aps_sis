import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    resources_model = env['aps.resources']
    last_id = 0
    count = 0

    while True:
        resources = resources_model.search([
            ('id', '>', last_id),
            ('type_id.name', 'ilike', 'Past Paper'),
        ], order='id', limit=500)
        if not resources:
            break

        last_id = resources[-1].id
        resources._compute_is_pearson_past_paper()
        resources.flush_recordset(['is_pearson_past_paper'])
        count += len(resources)

    _logger.info(
        'Recomputed is_pearson_past_paper for %s Past Paper resources.',
        count,
    )
