"""
Pre-migration 18.0.1.0.56: convert is_favourite from a global stored boolean
to a per-user Many2many relationship (aps_resource_favourite_user_rel).

The old aps_resources.is_favourite column is no longer used by the ORM (the
field is now computed).  The new relation table is created automatically by
the ORM during the upgrade.

Because the old flag was global (not user-specific) it is not possible to
determine which user originally set it, so the historical favourite flags are
not migrated.  Users will need to re-mark their own favourites after upgrading.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — ORM creates tables on init

    _logger.info(
        "aps_sis pre-migrate 18.0.1.0.56: is_favourite is now per-user; "
        "old global flags are not migrated"
    )
