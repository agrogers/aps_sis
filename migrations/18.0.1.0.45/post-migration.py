from odoo import SUPERUSER_ID, api
import logging

_logger = logging.getLogger(__name__)

SENTINEL = -0.01


def migrate(cr, version):
    """Back-fill score_alpha and out_of_marks_alpha from existing numeric fields.

    For records that already have a meaningful numeric score (i.e. not the
    sentinel -0.01), populate the new alpha Char fields so the new widget
    displays the correct value without requiring a manual re-entry.
    """
    # score → score_alpha
    cr.execute(
        """
        UPDATE aps_resource_submission
           SET score_alpha = CASE
                   WHEN score IS NULL OR ABS(score - %s) < 0.000001 THEN NULL
                   WHEN score = FLOOR(score) THEN TRIM(TO_CHAR(score, 'FM999999999999990'))
                   ELSE TRIM(TO_CHAR(score, 'FM999999999999990.099'))
               END
         WHERE score_alpha IS NULL
        """,
        (SENTINEL,),
    )
    rows = cr.rowcount
    _logger.info("Migration 18.0.1.0.45: backfilled score_alpha for %d submission(s).", rows)

    # out_of_marks → out_of_marks_alpha
    cr.execute(
        """
        UPDATE aps_resource_submission
           SET out_of_marks_alpha = CASE
                   WHEN out_of_marks IS NULL OR ABS(out_of_marks - %s) < 0.000001 THEN NULL
                   WHEN out_of_marks = FLOOR(out_of_marks) THEN TRIM(TO_CHAR(out_of_marks, 'FM999999999999990'))
                   ELSE TRIM(TO_CHAR(out_of_marks, 'FM999999999999990.099'))
               END
         WHERE out_of_marks_alpha IS NULL
        """,
        (SENTINEL,),
    )
    rows = cr.rowcount
    _logger.info(
        "Migration 18.0.1.0.45: backfilled out_of_marks_alpha for %d submission(s).", rows
    )
