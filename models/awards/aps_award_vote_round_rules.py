from odoo import api, fields, models


class APSAwardVoteRoundRules(models.AbstractModel):
    _name = 'aps.award.vote.round.mixin.rules'
    _description = 'Vote Round Rules Mixin'
    _auto = False

    rules = fields.Json(string='Rules')

    # Virtual fields backed by the rules JSON dict
    rule_limit_votes = fields.Boolean(
        string='Limit Votes',
        compute='_compute_rule_limit_votes',
        inverse='_inverse_rule_limit_votes',
    )
    rule_limit_votes_count = fields.Integer(
        string='Max Votes Per Voter',
        compute='_compute_rule_limit_votes_count',
        inverse='_inverse_rule_limit_votes_count',
    )
    rule_show_times_awarded = fields.Boolean(
        string='Show Times Awarded column',
        compute='_compute_rule_show_times_awarded',
        inverse='_inverse_rule_show_times_awarded',
    )
    rule_show_last_awarded = fields.Boolean(
        string='Show Last Awarded column',
        compute='_compute_rule_show_last_awarded',
        inverse='_inverse_rule_show_last_awarded',
    )
    rule_show_level_dept = fields.Boolean(
        string='Show Level / Department column',
        compute='_compute_rule_show_level_dept',
        inverse='_inverse_rule_show_level_dept',
    )
    rule_limit_candidates_to_own_students = fields.Selection(
        selection=[
            ('no', 'No – show all eligible candidates'),
            ('yes', 'Yes – show only the voter\'s own students'),
            ('optional', 'Optional – voter can toggle between their students and all candidates'),
        ],
        string='Limit Candidates to Own Students',
        compute='_compute_rule_limit_candidates_to_own_students',
        inverse='_inverse_rule_limit_candidates_to_own_students',
    )
    rule_allow_no_vote = fields.Boolean(
        string='Allow "No Vote" Submission',
        compute='_compute_rule_allow_no_vote',
        inverse='_inverse_rule_allow_no_vote',
        help='When enabled, voters can submit without selecting any recipient (abstain).',
    )
    rule_send_reminder_email = fields.Boolean(
        string='Send Voting Reminder Emails',
        compute='_compute_rule_send_reminder_email',
        inverse='_inverse_rule_send_reminder_email',
        help='When enabled, the "APEX Voting Reminder" scheduled action will send reminder emails to staff with open votes in this round.',
    )
    rule_limit_to_voter_year_level = fields.Boolean(
        string='Limit Candidates to Voter\'s Year Level',
        compute='_compute_rule_limit_to_voter_year_level',
        inverse='_inverse_rule_limit_to_voter_year_level',
        help='When enabled, candidates are restricted to the same year level(s) as the voter. '
             'For student voters this is their level; for teacher voters these are the levels they teach.',
    )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_rules_dict(self):
        """Return the rules value as a dict, never None."""
        self.ensure_one()
        r = self.rules
        return dict(r) if isinstance(r, dict) else {}

    def _set_rules_dict(self, data):
        self.ensure_one()
        self.rules = data

    # ── Compute / Inverse methods ────────────────────────────────────────────

    @api.depends('rules')
    def _compute_rule_limit_votes(self):
        for rec in self:
            rec.rule_limit_votes = bool(rec._get_rules_dict().get('limit_votes', False))

    def _inverse_rule_limit_votes(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['limit_votes'] = rec.rule_limit_votes
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_limit_votes_count(self):
        for rec in self:
            rec.rule_limit_votes_count = int(rec._get_rules_dict().get('limit_votes_count') or 1)

    def _inverse_rule_limit_votes_count(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['limit_votes_count'] = rec.rule_limit_votes_count
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_show_times_awarded(self):
        for rec in self:
            rec.rule_show_times_awarded = rec._get_rules_dict().get('show_times_awarded', True)

    def _inverse_rule_show_times_awarded(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['show_times_awarded'] = rec.rule_show_times_awarded
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_show_last_awarded(self):
        for rec in self:
            rec.rule_show_last_awarded = rec._get_rules_dict().get('show_last_awarded', True)

    def _inverse_rule_show_last_awarded(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['show_last_awarded'] = rec.rule_show_last_awarded
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_show_level_dept(self):
        for rec in self:
            rec.rule_show_level_dept = rec._get_rules_dict().get('show_level_dept', True)

    def _inverse_rule_show_level_dept(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['show_level_dept'] = rec.rule_show_level_dept
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_limit_candidates_to_own_students(self):
        for rec in self:
            rec.rule_limit_candidates_to_own_students = (
                rec._get_rules_dict().get('limit_candidates_to_own_students') or 'no'
            )

    def _inverse_rule_limit_candidates_to_own_students(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['limit_candidates_to_own_students'] = rec.rule_limit_candidates_to_own_students or 'no'
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_allow_no_vote(self):
        for rec in self:
            rec.rule_allow_no_vote = bool(rec._get_rules_dict().get('allow_no_vote'))

    def _inverse_rule_allow_no_vote(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['allow_no_vote'] = rec.rule_allow_no_vote
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_send_reminder_email(self):
        for rec in self:
            rec.rule_send_reminder_email = bool(rec._get_rules_dict().get('send_reminder_email'))

    def _inverse_rule_send_reminder_email(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['send_reminder_email'] = rec.rule_send_reminder_email
            rec._set_rules_dict(data)

    @api.depends('rules')
    def _compute_rule_limit_to_voter_year_level(self):
        for rec in self:
            rec.rule_limit_to_voter_year_level = bool(
                rec._get_rules_dict().get('limit_to_voter_year_level', False)
            )

    def _inverse_rule_limit_to_voter_year_level(self):
        for rec in self:
            data = rec._get_rules_dict()
            data['limit_to_voter_year_level'] = rec.rule_limit_to_voter_year_level
            rec._set_rules_dict(data)