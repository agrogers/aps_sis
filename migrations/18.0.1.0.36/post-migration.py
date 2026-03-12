import uuid
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Ensure every aps.resources record has a unique share_token.

    When the share_token column was first added via _auto_init, Odoo may have
    evaluated the default lambda once and written the same UUID to all
    pre-existing rows.  That causes the public share controller (which does
    search([('share_token','=',token)], limit=1)) to always resolve to the
    first record in the table.

    This migration assigns a fresh, unique UUID to:
      - rows that have no token (NULL / empty)
      - rows whose token is a duplicate of another row's token
    """
    # Fix NULL / empty tokens
    cr.execute("SELECT id FROM aps_resources WHERE share_token IS NULL OR share_token = ''")
    rows = cr.fetchall()
    for (record_id,) in rows:
        cr.execute(
            "UPDATE aps_resources SET share_token = %s WHERE id = %s",
            [str(uuid.uuid4()), record_id],
        )

    # Fix duplicate tokens: keep the lowest-id record's token, regenerate for
    # all later duplicates so each token is globally unique.
    cr.execute("""
        SELECT id
        FROM (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY share_token ORDER BY id) AS rn
            FROM aps_resources
            WHERE share_token IS NOT NULL AND share_token != ''
        ) sub
        WHERE rn > 1
    """)
    dup_ids = [row[0] for row in cr.fetchall()]
    for record_id in dup_ids:
        cr.execute(
            "UPDATE aps_resources SET share_token = %s WHERE id = %s",
            [str(uuid.uuid4()), record_id],
        )
