from odoo import api, fields, models


class APSAwardVoteRound(models.Model):
    _name = 'aps.award.vote.round'
    _description = 'Award Vote Round'
    _order = 'datetime_start desc, id desc'

    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    datetime_start = fields.Datetime(string='Start', required=True)
    datetime_end = fields.Datetime(string='End', required=True)
    status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('open', 'Open'),
            ('closed', 'Closed'),
            ('finalised', 'Finalised'),
        ],
        string='Status',
        default='draft',
        required=True,
    )

    # JSON fields for flexible configuration
    ## The eligible_voters field can be a list of partner IDs, a domain for selecting partners, or a more complex structure depending on the needs of the voting process. The same applies to eligible_candidates and rules.
    eligible_voters = fields.Json(string='Eligible Voters')
    eligible_candidates = fields.Json(string='Eligible Candidates')
    rules = fields.Json(string='Rules')
    result_summary = fields.Json(string='Result Summary')

    # Computed vote statistics
    votes_cast = fields.Integer(
        string='Votes Cast',
        compute='_compute_vote_stats',
        store=True,
    )
    active_voter_count = fields.Integer(
        string='Active Voter Count',
        compute='_compute_vote_stats',
        store=True,
    )
    total_voter_count = fields.Integer(
        string='Total Voter Count',
        compute='_compute_total_voter_count',
        store=True,
    )

    # Round managers
    round_manager_ids = fields.Many2many(
        'res.partner',
        'aps_award_vote_round_manager_rel',
        'round_id',
        'partner_id',
        string='Round Managers',
    )

    # Related votes
    vote_ids = fields.One2many(
        'aps.award.vote',
        'vote_round_id',
        string='Votes',
    )

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'datetime_start', 'status')
    def _compute_display_name(self):
        for rec in self:
            if rec.datetime_start:
                rec.display_name = f"{rec.name} ({rec.datetime_start.strftime('%Y-%m-%d')})"
            else:
                rec.display_name = rec.name or ''

    @api.depends('vote_ids', 'vote_ids.state')
    def _compute_vote_stats(self):
        for rec in self:
            votes = rec.vote_ids
            rec.votes_cast = len(votes.filtered(lambda v: v.state in ('submitted', 'closed')))
            rec.active_voter_count = len(votes.mapped('voter_partner_id'))

    @api.depends('eligible_voters')
    def _compute_total_voter_count(self):
        for rec in self:
            if isinstance(rec.eligible_voters, list):
                rec.total_voter_count = len(rec.eligible_voters)
            elif isinstance(rec.eligible_voters, dict):
                rec.total_voter_count = rec.eligible_voters.get('count', 0)
            else:
                rec.total_voter_count = 0

    def action_open(self):
        self.ensure_one()
        self.status = 'open'

    def action_close(self):
        self.ensure_one()
        self.status = 'closed'

    def action_finalise(self):
        self.ensure_one()
        self.status = 'finalised'

    def action_reset_draft(self):
        self.ensure_one()
        self.status = 'draft'
