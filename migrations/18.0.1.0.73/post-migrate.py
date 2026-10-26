import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrated = {}
    for model_name in ('res.users', 'aps.student'):
        model = env[model_name]
        last_id = 0
        count = 0
        while True:
            records = model.search([
                ('id', '>', last_id),
                ('avatar_id', '!=', False),
            ], order='id', limit=500)
            if not records:
                break
            for record in records:
                last_id = record.id
                image = record.avatar_id.image
                if image and not record.avatar_image:
                    record.avatar_image = image
                    count += 1
            records.flush_recordset(['avatar_image'])
        migrated[model_name] = count
    _logger.info(
        'Copied existing APS avatar images into standalone profile fields: %s',
        migrated,
    )
