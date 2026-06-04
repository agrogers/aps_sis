from odoo import api, fields, models


class APSPartnerVotingTokenWizard(models.TransientModel):
    _name = 'aps.partner.voting.token.wizard'
    _description = 'Partner Voting Token Wizard'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True, readonly=True)
    token_masked = fields.Char(string='Token (Masked)', compute='_compute_token_fields', readonly=True)
    token_value = fields.Char(string='Token', compute='_compute_token_fields', readonly=True)
    dashboard_url = fields.Char(string='Awards Dashboard URL', compute='_compute_token_fields', readonly=True)

    @api.depends('partner_id')
    def _compute_token_fields(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        for rec in self:
            token = rec.partner_id.sudo()._get_or_create_access_token() if rec.partner_id else ''
            rec.token_value = token
            if not token:
                rec.token_masked = ''
                rec.dashboard_url = ''
            elif len(token) <= 8:
                rec.token_masked = '*' * len(token)
                rec.dashboard_url = f"{base_url}/awards/vote/{token}"
            else:
                rec.token_masked = f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"
                rec.dashboard_url = f"{base_url}/awards/vote/{token}"

    def action_reset_token(self):
        self.ensure_one()
        self.partner_id.sudo().action_reset_access_token()
        self.invalidate_recordset()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Voting Access Token',
            'res_model': 'aps.partner.voting.token.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
