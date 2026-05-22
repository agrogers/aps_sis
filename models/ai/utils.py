import logging
import threading

from odoo import _, api
from odoo.exceptions import UserError
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


def _run_ai_background_job(db_name, run_id, user_id, context=None):
    try:
        db_registry = Registry(db_name)
        with db_registry.cursor() as cr:
            env = api.Environment(cr, user_id, context or {})
            run = env['aps.ai.run'].sudo().browse(run_id)
            if run.exists():
                run._process_background()
    except Exception:
        _logger.exception('Background AI run %s crashed unexpectedly', run_id)


def _exception_to_text(exc):
    if isinstance(exc, UserError):
        return getattr(exc, 'args', [False])[0] or str(exc)
    return str(exc)
