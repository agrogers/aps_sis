from odoo import api, fields, models


class APSAwardVoteRound(models.Model):
    _name = 'aps.award.vote.round'
    _description = 'Award Vote Round'
    _order = 'datetime_start desc, id desc'

    name = fields.Char(string='Name', required=True)

    description = fields.Text(string='Description')
    short_description = fields.Text(string='Short Description')
    image = fields.Image(string='Image')

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

    recurring_days = fields.Integer(
        string='Recur Every (days)',
        default=0,
        help='If set to a positive number, a new round will automatically be scheduled this many days after the current round ends. Set to 0 to disable auto-rescheduling.',
    )

    award_category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        ondelete='restrict',
    )
    award_sub_category_id = fields.Many2one(
        'aps.award.sub.category',
        string='Award Sub-Category',
        ondelete='restrict',
        domain="[('category_id', '=', award_category_id)]",
    )
    academic_week_id = fields.Many2one(
        'aps.academic.week',
        string='Academic Week',
        ondelete='restrict',
    )

    # JSON fields for flexible configuration
    # eligible_voters stores a dict: {"partner_ids": [...], "level_ids": [...], "subject_category_ids": [...]}
    # Backward-compat: also accepts a plain list (treated as partner_ids)
    eligible_voters = fields.Json(string='Eligible Voters')

    # Virtual Many2many fields backed by the eligible_voters JSON dict (no DB relation tables)
    eligible_voter_partner_ids = fields.Many2many(
        'res.partner',
        string='Staff Voters',
        compute='_compute_eligible_voter_ids',
        inverse='_inverse_eligible_voter_ids',
    )
    eligible_voter_level_ids = fields.Many2many(
        'aps.level',
        string='Voter Levels',
        compute='_compute_eligible_voter_levels',
        inverse='_inverse_eligible_voter_levels',
    )
    eligible_voter_category_ids = fields.Many2many(
        'aps.subject.category',
        string='Voter Subject Categories',
        compute='_compute_eligible_voter_categories',
        inverse='_inverse_eligible_voter_categories',
    )

    # eligible_candidates stores a dict: {"level_ids": [...], "subject_category_ids": [...], "student_ids": [...]}
    eligible_candidates = fields.Json(string='Eligible Candidates')

    # Virtual Many2many fields backed by the eligible_candidates JSON dict (no DB relation tables)
    eligible_candidate_level_ids = fields.Many2many(
        'aps.level',
        string='Eligible Levels',
        compute='_compute_eligible_candidate_levels',
        inverse='_inverse_eligible_candidate_levels',
    )
    eligible_candidate_category_ids = fields.Many2many(
        'aps.subject.category',
        string='Eligible Subject Categories',
        compute='_compute_eligible_candidate_categories',
        inverse='_inverse_eligible_candidate_categories',
    )
    eligible_candidate_student_ids = fields.Many2many(
        'aps.student',
        string='Eligible Students',
        compute='_compute_eligible_candidate_students',
        inverse='_inverse_eligible_candidate_students',
    )

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
            data = rec._get_voters_dict()
            rec.total_voter_count = len(data.get('partner_ids', []))

    def _get_voters_dict(self):
        """Return eligible_voters as a dict, handling legacy flat-list format."""
        self.ensure_one()
        v = self.eligible_voters
        if isinstance(v, list):
            return {'partner_ids': v}
        return dict(v) if isinstance(v, dict) else {}

    def _set_voters_dict(self, data):
        self.ensure_one()
        self.eligible_voters = data

    @api.depends('eligible_voters')
    def _compute_eligible_voter_ids(self):
        for rec in self:
            ids = rec._get_voters_dict().get('partner_ids', [])
            rec.eligible_voter_partner_ids = self.env['res.partner'].browse(ids).exists()

    def _inverse_eligible_voter_ids(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['partner_ids'] = rec.eligible_voter_partner_ids.ids
            rec._set_voters_dict(data)

    @api.depends('eligible_voters')
    def _compute_eligible_voter_levels(self):
        for rec in self:
            ids = rec._get_voters_dict().get('level_ids', [])
            rec.eligible_voter_level_ids = self.env['aps.level'].browse(ids).exists()

    def _inverse_eligible_voter_levels(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['level_ids'] = rec.eligible_voter_level_ids.ids
            rec._set_voters_dict(data)

    @api.depends('eligible_voters')
    def _compute_eligible_voter_categories(self):
        for rec in self:
            ids = rec._get_voters_dict().get('subject_category_ids', [])
            rec.eligible_voter_category_ids = self.env['aps.subject.category'].browse(ids).exists()

    def _inverse_eligible_voter_categories(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['subject_category_ids'] = rec.eligible_voter_category_ids.ids
            rec._set_voters_dict(data)

    # ── Eligible Candidates helpers ──────────────────────────────────────────

    def _get_candidates_dict(self):
        """Return the eligible_candidates value as a dict, never None."""
        self.ensure_one()
        c = self.eligible_candidates
        return dict(c) if isinstance(c, dict) else {}

    def _set_candidates_dict(self, data):
        self.ensure_one()
        self.eligible_candidates = data

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_levels(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('level_ids', [])
            rec.eligible_candidate_level_ids = self.env['aps.level'].browse(ids).exists()

    def _inverse_eligible_candidate_levels(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['level_ids'] = rec.eligible_candidate_level_ids.ids
            rec._set_candidates_dict(data)

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_categories(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('subject_category_ids', [])
            rec.eligible_candidate_category_ids = self.env['aps.subject.category'].browse(ids).exists()

    def _inverse_eligible_candidate_categories(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['subject_category_ids'] = rec.eligible_candidate_category_ids.ids
            rec._set_candidates_dict(data)

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_students(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('student_ids', [])
            rec.eligible_candidate_student_ids = self.env['aps.student'].browse(ids).exists()

    def _inverse_eligible_candidate_students(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['student_ids'] = rec.eligible_candidate_student_ids.ids
            rec._set_candidates_dict(data)

    def _collect_eligible_voter_partners(self):
        """Return a set of res.partner IDs for all voters eligible in this round.

        Sources:
          1. Explicit staff partners listed in eligible_voters["partner_ids"].
          2. Teachers and assistant teachers of classes whose subject matches
             ALL specified levels AND subject categories (if both sets are non-empty).
             If only levels or only categories are specified, classes must match
             the non-empty constraint only.
        """
        self.ensure_one()
        voters_dict = self._get_voters_dict()
        partner_ids = set(voters_dict.get('partner_ids', []))

        level_ids = self.eligible_voter_level_ids.ids
        category_ids = self.eligible_voter_category_ids.ids

        if level_ids or category_ids:
            domain = []
            if level_ids:
                domain.append(('subject_id.level_id', 'in', level_ids))
            if category_ids:
                domain.append(('subject_id.category_id', 'in', category_ids))
            classes = self.env['aps.class'].search(domain)
            for cls in classes:
                partner_ids.update(cls.teacher_ids.ids)
                partner_ids.update(cls.assistant_teacher_ids.ids)

        return partner_ids

    def action_open(self):
        self.ensure_one()

        # Resolve all eligible voter partners
        all_partner_ids = self._collect_eligible_voter_partners()

        # Skip partners who already have a ballot in this round
        existing_partner_ids = set(self.vote_ids.mapped('voter_partner_id').ids)
        new_partner_ids = all_partner_ids - existing_partner_ids

        if new_partner_ids:
            today = fields.Date.context_today(self)
            due_date = self.datetime_end.date() if self.datetime_end else False
            vals_list = [
                {
                    'vote_round_id': self.id,
                    'voter_partner_id': pid,
                    'state': 'open',
                    'open_date': today,
                    'due_date': due_date,
                    'award_category_id': self.award_category_id.id or False,
                    'award_sub_category_id': self.award_sub_category_id.id or False,
                    'academic_week_id': self.academic_week_id.id or False,
                }
                for pid in new_partner_ids
            ]
            self.env['aps.award.vote'].create(vals_list)

        self.status = 'open'

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', f"{self.name} (Copy)")
        default.setdefault('status', 'draft')
        return super().copy(default)

    def action_close(self):
        self.ensure_one()
        self.status = 'closed'

    def action_finalise(self):
        self.ensure_one()
        self.status = 'finalised'

    def action_reset_draft(self):
        self.ensure_one()
        self.status = 'draft'

    def action_copy_voter_config_to_candidates(self):
        """Copy eligible voter levels and subject categories to the eligible candidates lists."""
        self.ensure_one()
        self.eligible_candidate_level_ids = self.eligible_voter_level_ids
        self.eligible_candidate_category_ids = self.eligible_voter_category_ids
