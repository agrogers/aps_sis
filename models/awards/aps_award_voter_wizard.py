from odoo import api, fields, models


class APSAwardVoterWizard(models.TransientModel):
    _name = 'aps.award.voter.wizard'
    _description = 'Add People Voters Wizard'

    vote_round_id = fields.Many2one(
        'aps.award.vote.round',
        string='Vote Round',
        required=True,
        ondelete='cascade',
    )
    partner_ids = fields.Many2many(
        'res.partner',
        'aps_award_voter_wizard_partner_rel',
        'wizard_id',
        'partner_id',
        string='People',
    )

    def action_confirm(self):
        self.ensure_one()
        round_rec = self.vote_round_id
        existing = list(round_rec.eligible_voters or [])
        # Merge new IDs with existing, preserving order and deduplicating
        merged = list(dict.fromkeys(existing + self.partner_ids.ids))
        round_rec.eligible_voters = merged
        return {'type': 'ir.actions.act_window_close'}
