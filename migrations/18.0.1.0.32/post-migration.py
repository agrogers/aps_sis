from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Set auto_score flag correctly for pre-existing records.

    New records default to auto_score=True, but existing records that already
    have a manually entered score or answer should be marked as manually set
    (auto_score=False).

    Rule: auto_score = False when score is non-zero (not the sentinel -0.01 or 0).
    Answer is now also protected by auto_score, so we additionally set it to
    False when an answer is present (to avoid overwriting existing answers).
    """
    # Mark existing records as manually scored/answered when they have real values.
    # -0.01 is the sentinel value used to mean "score not set" (see sentinel_zero in the model).
    # '<p><br></p>' is the empty HTML that Odoo's rich-text editor writes for a blank field.
    cr.execute("""
        UPDATE aps_resource_submission
        SET auto_score = FALSE
        WHERE (
            (score IS NOT NULL AND score != 0 AND score != -0.01)
            OR (answer IS NOT NULL AND answer != '' AND answer != '<p><br></p>')
        )
        AND auto_score = TRUE
    """)
