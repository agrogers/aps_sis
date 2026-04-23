from odoo import SUPERUSER_ID, api
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Reset aps_resources.has_answer = 'yes_notes' to 'no'.

    The 'yes_notes' selection option is being removed from the has_answer field.
    Any records still carrying that value must be reset to 'no' before the ORM
    loads — otherwise Odoo will log warnings about invalid selection values.
    """
    cr.execute("""
        SELECT COUNT(*)
        FROM aps_resources
        WHERE has_answer = 'yes_notes'
    """)
    count = cr.fetchone()[0]
    if count:
        cr.execute("""
            UPDATE aps_resources
            SET has_answer = 'no'
            WHERE has_answer = 'yes_notes'
        """)
        _logger.info(
            "Migration 18.0.1.0.43: reset %d aps_resources record(s) "
            "from has_answer='yes_notes' to 'no'.",
            count,
        )
    else:
        _logger.info(
            "Migration 18.0.1.0.43: no aps_resources records had "
            "has_answer='yes_notes'; nothing to do."
        )
