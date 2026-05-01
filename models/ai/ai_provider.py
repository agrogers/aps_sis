import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .utils import (
    _build_notification_action,
    _chain_notification_actions,
    _exception_to_text,
    _format_test_failure_message,
)

_logger = logging.getLogger(__name__)


class APSAIProvider(models.Model):
    _name = 'aps.ai.provider'
    _description = 'APEX AI Provider'
    _order = 'priority desc, name, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(default=True, help='If disabled, this provider will not be used for AI calls.')
    priority = fields.Integer(default=10)
    api_base_url = fields.Char(required=True, help='Base URL of the AI router/provider.')
    chat_completions_path = fields.Char(
        default='/chat/completions',
        required=True,
        help='Relative path used for OpenAI-compatible chat completion calls.',
    )
    api_key = fields.Char(help='API key used to authenticate against the AI router/provider.')
    api_key_header = fields.Char(default='Authorization', required=True)
    api_key_prefix = fields.Char(default='Bearer ')
    timeout_seconds = fields.Integer(default=90, required=True)
    notes = fields.Text()
    model_ids = fields.One2many('aps.ai.model', 'provider_id', string='Models')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'api_base_url')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.name or record.api_base_url or ''

    def action_test_connection(self):
        self.ensure_one()
        models_to_test = self.model_ids.filtered(lambda rec: rec.enabled).sorted(lambda rec: (-rec.priority, rec.id))
        if not models_to_test:
            raise UserError(_('Add at least one enabled AI model to this provider before testing it.'))

        notifications = []

        for model in models_to_test:
            try:
                result = model._run_connection_test()
                notifications.append(_build_notification_action(
                    _('AI Test Passed'),
                    _('Model: %s. Prompt tokens: %s. Completion tokens: %s. Estimated cost: %s') % (
                        model.display_name,
                        result['prompt_tokens'],
                        result['completion_tokens'],
                        f"{result['estimated_cost']:.6f}",
                    ),
                    notification_type='success',
                    sticky=False,
                ))
            except Exception as exc:
                notifications.append(_build_notification_action(
                    _('AI Test Failed'),
                    _format_test_failure_message(model.display_name, _exception_to_text(exc)),
                    notification_type='warning',
                    sticky=True,
                ))

        return _chain_notification_actions(notifications)
