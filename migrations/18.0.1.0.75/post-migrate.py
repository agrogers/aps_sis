import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    teachers_model = env['aps.teacher']
    last_id = 0
    count = 0

    while True:
        teachers = teachers_model.search(
            [('id', '>', last_id)],
            order='id',
            limit=500,
        )
        if not teachers:
            break

        last_id = teachers[-1].id
        teachers._compute_load_percentages()
        teachers.flush_recordset([
            'teaching_load_percentage',
            'non_teaching_load_percentage',
        ])
        count += len(teachers)

    _logger.info(
        'Recomputed live timetable load percentages for %s teachers.',
        count,
    )
