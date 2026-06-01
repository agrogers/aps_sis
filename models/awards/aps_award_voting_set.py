from odoo import fields, models


class APSAwardVotingSet(models.Model):
    _name = 'aps.award.voting.set'
    _description = 'Award Voting Set'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    icon = fields.Char(string='Icon')
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')

    round_ids = fields.One2many(
        'aps.award.vote.round',
        'voting_set_id',
        string='Rounds',
    )

    vote_ids = fields.Many2many(
        'aps.award.vote',
        compute='_compute_vote_ids',
        string='Votes',
        help='All votes cast across rounds belonging to this voting set.',
    )

    def _compute_vote_ids(self):
        for rec in self:
            votes = self.env['aps.award.vote'].search(
                [('vote_round_id', 'in', rec.round_ids.ids)]
            )
            rec.vote_ids = votes
