from odoo import api, fields, models


class APSAwardVoteRoundCandidates(models.AbstractModel):
    _name = 'aps.award.vote.round.mixin.candidates'
    _description = 'Eligible / Ineligible Candidates Mixin'
    _auto = False

    # eligible_candidates stores a dict: {"level_ids": [...], "subject_category_ids": [...], "student_ids": [...], "department_ids": [...]}
    eligible_candidates = fields.Json(string='Eligible Candidates')

    # Eligible Candidates tab — visibility toggles
    candidate_show_levels = fields.Boolean(string='Levels', default=False)
    candidate_show_categories = fields.Boolean(string='Subject Categories', default=False)
    candidate_show_students = fields.Boolean(string='Students', default=False)
    candidate_show_departments = fields.Boolean(string='Departments', default=False)

    # Sub-toggles: which person types are included when levels/categories are set
    candidate_levels_include_teachers = fields.Boolean(string='Teachers', default=False)
    candidate_levels_include_students = fields.Boolean(string='Students', default=True)
    candidate_categories_include_teachers = fields.Boolean(string='Teachers', default=False)
    candidate_categories_include_students = fields.Boolean(string='Students', default=True)

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
    eligible_candidate_department_ids = fields.Many2many(
        'hr.department',
        string='Eligible Departments',
        compute='_compute_eligible_candidate_departments',
        inverse='_inverse_eligible_candidate_departments',
    )

    # ineligible_candidates stores a dict: {"exclude_voter": bool, "partner_ids": [...]}
    ineligible_candidates = fields.Json(string='Ineligible Candidates')

    # Virtual fields backed by the ineligible_candidates JSON dict
    ineligible_candidate_exclude_voter = fields.Boolean(
        string='Exclude the Voter',
        compute='_compute_ineligible_candidate_exclude_voter',
        inverse='_inverse_ineligible_candidate_exclude_voter',
    )
    ineligible_candidate_partner_ids = fields.Many2many(
        'res.partner',
        string='Excluded People',
        compute='_compute_ineligible_candidate_partners',
        inverse='_inverse_ineligible_candidate_partners',
    )
    ineligible_show_people = fields.Boolean(string='People', default=False)

    # ── Eligible Candidates helpers ──────────────────────────────────────────

    def _get_candidates_dict(self):
        """Return the eligible_candidates value as a dict, never None."""
        self.ensure_one()
        c = self.eligible_candidates
        return dict(c) if isinstance(c, dict) else {}

    def _set_candidates_dict(self, data):
        self.ensure_one()
        self.eligible_candidates = data

    # ── Eligible Candidates compute / inverse ────────────────────────────────

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_levels(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('level_ids', [])
            rec.eligible_candidate_level_ids = self.env['aps.level'].browse(ids).exists().sorted('name')

    def _inverse_eligible_candidate_levels(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['level_ids'] = rec.eligible_candidate_level_ids.ids
            rec._set_candidates_dict(data)

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_categories(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('subject_category_ids', [])
            rec.eligible_candidate_category_ids = self.env['aps.subject.category'].browse(ids).exists().sorted('name')

    def _inverse_eligible_candidate_categories(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['subject_category_ids'] = rec.eligible_candidate_category_ids.ids
            rec._set_candidates_dict(data)

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_students(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('student_ids', [])
            rec.eligible_candidate_student_ids = self.env['aps.student'].browse(ids).exists().sorted('name')

    def _inverse_eligible_candidate_students(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['student_ids'] = rec.eligible_candidate_student_ids.ids
            rec._set_candidates_dict(data)

    @api.depends('eligible_candidates')
    def _compute_eligible_candidate_departments(self):
        for rec in self:
            ids = rec._get_candidates_dict().get('department_ids', [])
            rec.eligible_candidate_department_ids = self.env['hr.department'].browse(ids).exists().sorted('name')

    def _inverse_eligible_candidate_departments(self):
        for rec in self:
            data = rec._get_candidates_dict()
            data['department_ids'] = rec.eligible_candidate_department_ids.ids
            rec._set_candidates_dict(data)

    # ── Ineligible Candidates helpers ────────────────────────────────────────

    def _get_ineligible_dict(self):
        """Return the ineligible_candidates value as a dict, never None."""
        self.ensure_one()
        c = self.ineligible_candidates
        return dict(c) if isinstance(c, dict) else {}

    def _set_ineligible_dict(self, data):
        self.ensure_one()
        self.ineligible_candidates = data

    # ── Ineligible Candidates compute / inverse ──────────────────────────────

    @api.depends('ineligible_candidates')
    def _compute_ineligible_candidate_exclude_voter(self):
        for rec in self:
            rec.ineligible_candidate_exclude_voter = bool(
                rec._get_ineligible_dict().get('exclude_voter', False)
            )

    def _inverse_ineligible_candidate_exclude_voter(self):
        for rec in self:
            data = rec._get_ineligible_dict()
            data['exclude_voter'] = rec.ineligible_candidate_exclude_voter
            rec._set_ineligible_dict(data)

    @api.depends('ineligible_candidates')
    def _compute_ineligible_candidate_partners(self):
        for rec in self:
            ids = rec._get_ineligible_dict().get('partner_ids', [])
            rec.ineligible_candidate_partner_ids = self.env['res.partner'].browse(ids).exists()

    def _inverse_ineligible_candidate_partners(self):
        for rec in self:
            data = rec._get_ineligible_dict()
            data['partner_ids'] = rec.ineligible_candidate_partner_ids.ids
            rec._set_ineligible_dict(data)

    # ── Convenience ─────────────────────────────────────────────────────────

    def action_copy_voter_config_to_candidates(self):
        """Copy eligible voter levels, subject categories and departments to the eligible candidates lists."""
        self.ensure_one()
        self.eligible_candidate_level_ids = self.eligible_voter_level_ids
        self.eligible_candidate_category_ids = self.eligible_voter_category_ids
        self.eligible_candidate_department_ids = self.eligible_voter_department_ids