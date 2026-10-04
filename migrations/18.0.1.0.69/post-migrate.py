import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    records = env['aps.time.tracking'].search([])
    records._compute_is_outside_school_hours()
    records.flush_recordset(['is_outside_school_hours'])
    _logger.info(
        'Recomputed Outside School Hours for %s time-tracking entries.',
        len(records),
    )