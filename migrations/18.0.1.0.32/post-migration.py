from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Set auto_score and auto_answer flags correctly for pre-existing records.

    New records default to auto_score=True and auto_answer=True, but existing
    records that already have a manually entered score or answer should be
    marked as manually set (auto_score=False / auto_answer=False).

    Rules:
    - auto_score = False  when score is non-zero (not the sentinel -0.01 or 0)
    - auto_answer = False when answer is present (not NULL/empty/blank HTML)
    """
    # Mark existing records as manually scored when they have a real score value
    cr.execute("""
        UPDATE aps_resource_submission
        SET auto_score = FALSE
        WHERE score IS NOT NULL
          AND score != 0
          AND score != -0.01
          AND auto_score = TRUE
    """)

    # Mark existing records as manually answered when they have a non-empty answer
    cr.execute("""
        UPDATE aps_resource_submission
        SET auto_answer = FALSE
        WHERE answer IS NOT NULL
          AND answer != ''
          AND answer != '<p><br></p>'
          AND auto_answer = TRUE
    """)
