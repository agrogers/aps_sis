import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class APSAICallLog(models.Model):
    _name = 'aps.ai.call.log'
    _description = 'APEX AI Call Log'
    _order = 'create_date desc, id desc'

    state = fields.Selection(
        [('success', 'Success'), ('error', 'Error')],
        required=True,
        readonly=True,
    )
    request_type = fields.Selection(
        [('connection_test', 'Connection Test'), ('submission_feedback', 'Submission Feedback')],
        required=True,
        readonly=True,
    )
    user_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    provider_id = fields.Many2one('aps.ai.provider', readonly=True, ondelete='set null')
    model_id = fields.Many2one('aps.ai.model', readonly=True, ondelete='set null')
    model_key = fields.Char(readonly=True)
    endpoint = fields.Char(readonly=True)
    related_model = fields.Char(readonly=True)
    related_res_id = fields.Integer(readonly=True)
    related_display_name = fields.Char(readonly=True)
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    estimated_cost = fields.Float(readonly=True, digits=(16, 6))
    duration_ms = fields.Integer(readonly=True)
    request_payload = fields.Text(readonly=True)
    response_body = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('request_type', 'model_id.display_name', 'create_date', 'state')
    def _compute_display_name(self):
        request_type_labels = dict(self._fields['request_type'].selection)
        state_labels = dict(self._fields['state'].selection)
        for record in self:
            type_label = request_type_labels.get(record.request_type, record.request_type or _('Unknown'))
            state_label = state_labels.get(record.state, record.state or _('Unknown'))
            model_label = record.model_id.display_name or record.model_key or _('No Model')
            created = fields.Datetime.to_string(record.create_date) if record.create_date else ''
            record.display_name = '%s - %s - %s%s' % (
                type_label,
                model_label,
                state_label,
                (' - %s' % created) if created else '',
            )
