from odoo import api, fields, models


class APSAwardVotingSet(models.Model):
    _name = 'aps.award.voting.set'
    _description = 'Award Voting Set'
    _order = 'sequence, name'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Name', required=True)
    icon = fields.Image(string='Icon', max_width=256, max_height=256)
    color = fields.Char(string='Color', default='#5c1ea8')
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')

    round_ids = fields.Many2many(
        'aps.award.vote.round',
        'aps_vote_round_voting_set_rel',
        'voting_set_id',
        'round_id',
        string='Rounds',
    )

    vote_ids = fields.Many2many(
        'aps.award.vote',
        compute='_compute_vote_ids',
        string='Votes',
        help='All votes cast across rounds belonging to this voting set.',
    )

    @api.depends('round_ids')
    def _compute_vote_ids(self):
        all_round_ids = set()
        for rec in self:
            all_round_ids.update(rec.round_ids.ids)
        all_votes = self.env['aps.award.vote'].search(
            [('vote_round_id', 'in', list(all_round_ids))]
        ) if all_round_ids else self.env['aps.award.vote']
        for rec in self:
            rec.vote_ids = all_votes.filtered(
                lambda v: v.vote_round_id.id in rec.round_ids.ids
            )
