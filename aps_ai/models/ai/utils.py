import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _exception_to_text(exc):
    if isinstance(exc, UserError):
        return getattr(exc, 'args', [False])[0] or str(exc)
    return str(exc)


def _build_notification_action(title, message, notification_type='info', sticky=False, next_action=None):
    params = {
        'title': title,
        'message': message,
        'type': notification_type,
        'sticky': sticky,
    }
    if next_action:
        params['next'] = next_action
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': params,
    }


def _format_test_failure_message(model_display_name, error_text):
    message = _('%s: %s') % (model_display_name, error_text)
    normalized_error = (error_text or '').lower()
    if 'empty completion' in normalized_error or 'did not return the final answer' in normalized_error:
        message = _(
            '%s\n\nOpen AI > Logs and inspect the newest Connection Test entry for this model. '
            'The raw response is stored in Response Body.'
        ) % message
    return message


def _chain_notification_actions(actions):
    next_action = False
    for action in reversed(actions):
        params = dict(action.get('params') or {})
        if next_action:
            params['next'] = next_action
        next_action = {
            'type': action.get('type'),
            'tag': action.get('tag'),
            'params': params,
        }
    return next_action or {'type': 'ir.actions.client', 'tag': 'reload'}
