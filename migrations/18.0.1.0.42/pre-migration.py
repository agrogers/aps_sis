from odoo import SUPERUSER_ID, api
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Pre-create avatar_id column on res_users before ORM loads.

    res.users is queried very early during module loading (session checks etc.).
    If the column doesn't exist yet the query crashes before aps_sis's schema
    migration has a chance to run.
    """
    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'res_users' AND column_name = 'avatar_id'
    """)
    if not cr.fetchone():
        _logger.info("Pre-creating res_users.avatar_id column")
        cr.execute("ALTER TABLE res_users ADD COLUMN avatar_id INTEGER")
