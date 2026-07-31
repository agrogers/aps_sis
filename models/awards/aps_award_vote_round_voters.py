from odoo import api, fields, models


class APSAwardVoteRoundVoters(models.AbstractModel):
    _name = 'aps.award.vote.round.mixin.voters'
    _description = 'Eligible Voters Mixin'
    _auto = False

    # JSON field for flexible configuration
    # eligible_voters stores a dict: {"partner_ids": [...], "level_ids": [...], "subject_category_ids": [...], "department_ids": [...]}
    # Backward-compat: also accepts a plain list (treated as partner_ids)
    eligible_voters = fields.Json(string='Eligible Voters')

    # Eligible Voters tab — visibility toggles (stored so they persist with the round config)
    voter_show_staff = fields.Boolean(string='People', default=False)
    voter_show_levels = fields.Boolean(string='Levels', default=False)
    voter_show_categories = fields.Boolean(string='Subject Categories', default=False)
    voter_show_departments = fields.Boolean(string='Departments', default=False)

    # Sub-toggles: which person types are included when levels/categories are set
    voter_levels_include_teachers = fields.Boolean(string='Teachers', default=True)
    voter_levels_include_students = fields.Boolean(string='Students', default=True)
    voter_categories_include_teachers = fields.Boolean(string='Teachers', default=True)
    voter_categories_include_students = fields.Boolean(string='Students', default=False)

    # Virtual Many2many fields backed by the eligible_voters JSON dict (no DB relation tables)
    eligible_voter_partner_ids = fields.Many2many(
        'res.partner',
        string='People',
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
    eligible_voter_department_ids = fields.Many2many(
        'hr.department',
        string='Voter Departments',
        compute='_compute_eligible_voter_departments',
        inverse='_inverse_eligible_voter_departments',
    )

    # ── Helpers ──────────────────────────────────────────────────────────────

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

    # ── Compute / Inverse methods ────────────────────────────────────────────

    @api.depends('eligible_voters')
    def _compute_eligible_voter_ids(self):
        for rec in self:
            ids = rec._get_voters_dict().get('partner_ids', [])
            rec.eligible_voter_partner_ids = self.env['res.partner'].browse(ids).exists().sorted('name')

    def _inverse_eligible_voter_ids(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['partner_ids'] = rec.eligible_voter_partner_ids.ids
            rec._set_voters_dict(data)

    @api.depends('eligible_voters')
    def _compute_eligible_voter_levels(self):
        for rec in self:
            ids = rec._get_voters_dict().get('level_ids', [])
            rec.eligible_voter_level_ids = self.env['aps.level'].browse(ids).exists().sorted('name')

    def _inverse_eligible_voter_levels(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['level_ids'] = rec.eligible_voter_level_ids.ids
            rec._set_voters_dict(data)

    @api.depends('eligible_voters')
    def _compute_eligible_voter_categories(self):
        for rec in self:
            ids = rec._get_voters_dict().get('subject_category_ids', [])
            rec.eligible_voter_category_ids = self.env['aps.subject.category'].browse(ids).exists().sorted('name')

    def _inverse_eligible_voter_categories(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['subject_category_ids'] = rec.eligible_voter_category_ids.ids
            rec._set_voters_dict(data)

    @api.depends('eligible_voters')
    def _compute_eligible_voter_departments(self):
        for rec in self:
            ids = rec._get_voters_dict().get('department_ids', [])
            rec.eligible_voter_department_ids = self.env['hr.department'].browse(ids).exists().sorted('name')

    def _inverse_eligible_voter_departments(self):
        for rec in self:
            data = rec._get_voters_dict()
            data['department_ids'] = rec.eligible_voter_department_ids.ids
            rec._set_voters_dict(data)

    @api.depends('eligible_voters')
    def _compute_total_voter_count(self):
        for rec in self:
            data = rec._get_voters_dict()
            rec.total_voter_count = len(data.get('partner_ids', []))

    def _collect_eligible_voter_partners(self):
        """Return a set of res.partner IDs for all voters eligible in this round.

        Sources:
          1. Explicit partners listed in eligible_voters["partner_ids"] (staff or students).
          2. Teachers and assistant teachers of classes whose subject matches
             ALL specified levels AND subject categories (if both sets are non-empty).
             If only levels or only categories are specified, classes must match
             the non-empty constraint only.
          3. Students whose level_id matches the specified levels (when level_ids are set).
          4. Active employees in the specified departments.
        """
        self.ensure_one()
        voters_dict = self._get_voters_dict()
        partner_ids = set(voters_dict.get('partner_ids', []))

        level_ids = self.eligible_voter_level_ids.ids if self.voter_show_levels else []
        category_ids = self.eligible_voter_category_ids.ids if self.voter_show_categories else []

        # Teachers from classes matching levels and/or categories (controlled by sub-toggles)
        if (level_ids and self.voter_levels_include_teachers) or \
                (category_ids and self.voter_categories_include_teachers):
            domain = []
            if level_ids and self.voter_levels_include_teachers:
                domain.append(('subject_id.level_id', 'in', level_ids))
            if category_ids and self.voter_categories_include_teachers:
                domain.append(('subject_id.category_id', 'in', category_ids))
            if domain:
                classes = self.env['aps.class'].search(domain)
                for cls in classes:
                    partner_ids.update(cls.teacher_ids.ids)
                    partner_ids.update(cls.assistant_teacher_ids.ids)

        # Students whose level matches the voter levels
        if level_ids and self.voter_levels_include_students:
            students = self.env['aps.student'].search([
                ('level_id', 'in', level_ids),
                ('active', '=', True),
            ])
            for s in students:
                if s.partner_id:
                    partner_ids.add(s.partner_id.id)

        # Students enrolled in classes with matching subject categories
        if category_ids and self.voter_categories_include_students:
            cat_classes = self.env['aps.class'].search([
                ('subject_id.category_id', 'in', category_ids),
            ])
            enrollments = self.env['aps.student.class'].search([
                ('home_class_id', 'in', cat_classes.ids),
                ('active', '=', True),
            ])
            for enr in enrollments:
                if enr.student_id and enr.student_id.partner_id:
                    partner_ids.add(enr.student_id.partner_id.id)

        if self.voter_show_departments:
            department_ids = self.eligible_voter_department_ids.ids
            if department_ids:
                employees = self.env['hr.employee'].search([
                    ('department_id', 'in', department_ids),
                    ('active', '=', True),
                ])
                for emp in employees:
                    if emp.user_id and emp.user_id.partner_id:
                        partner_ids.add(emp.user_id.partner_id.id)

        return partner_ids