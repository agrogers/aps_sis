from odoo import fields, models, api

LOAD_PERCENTAGE_SENTINEL = -0.01


class APSTeacher(models.Model):
    _name = 'aps.teacher'
    _description = 'Teacher'
    _order = 'name'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        required=True,
        ondelete='cascade',
        index=True,
    )
    tutor_code = fields.Char(string='Tutor Code', size=20)
    active = fields.Boolean(default=True)

    # Workload allocation (minutes)
    teaching_load = fields.Integer(
        string='Teaching Load (minutes)',
        default=0,
        readonly=True,
        help='Calculated from the timetable.',
    )
    non_teaching_load = fields.Integer(
        string='Non-Teaching Load (minutes)',
        default=0,
        readonly=True,
        help='Calculated from the timetable.',
    )
    max_load = fields.Integer(
        string='Maximum Load (minutes)',
        default=0,
        help='Maximum total minutes a teacher can be allocated.',
    )
    teaching_load_fte = fields.Float(
        string='Teaching FTE',
        default=1.0,
        digits=(16, 2),
        help='Full-time equivalent used to scale the maximum teaching load.',
    )
    max_non_teaching_load = fields.Integer(
        string='Maximum Non-Teaching Load (minutes)',
        default=0,
        help='Maximum non-teaching minutes a teacher can be allocated. For',
    )
    non_teaching_load_fte = fields.Float(
        string='Non-Teaching FTE',
        default=1.0,
        digits=(16, 2),
        help='Full-time equivalent used to scale the maximum non-teaching load.',
    )
    teaching_load_percentage = fields.Float(
        string='Teaching Load %',
        compute='_compute_load_percentages',
        store=True,
        digits=(16, 2),
    )
    non_teaching_load_percentage = fields.Float(
        string='Non-Teaching Load %',
        compute='_compute_load_percentages',
        store=True,
        digits=(16, 2),
    )
    load_details = fields.Html(
        string='Load Details',
        help='Detailed breakdown of teaching and non-teaching load allocations.',
    )
    role_contract_id = fields.Many2one(
        'hr.contract',
        compute='_compute_role_contract_id',
        groups='hr.group_hr_user',
    )
    role_job1_id = fields.Many2one(
        'hr.job',
        related='role_contract_id.job_id',
        string='Job 1',
        groups='hr.group_hr_user',
    )
    role_fte1 = fields.Float(
        related='role_contract_id.fte1',
        string='FTE 1',
        groups='hr.group_hr_user',
    )
    role_department1_id = fields.Many2one(
        'hr.department',
        related='role_contract_id.department_id',
        string='Department 1',
        groups='hr.group_hr_user',
    )
    role_job2_id = fields.Many2one(
        'hr.job',
        related='role_contract_id.job2_id',
        string='Job 2',
        groups='hr.group_hr_user',
    )
    role_fte2 = fields.Float(
        related='role_contract_id.fte2',
        string='FTE 2',
        groups='hr.group_hr_user',
    )
    role_department2_id = fields.Many2one(
        'hr.department',
        related='role_contract_id.department2_id',
        string='Department 2',
        groups='hr.group_hr_user',
    )
    role_job3_id = fields.Many2one(
        'hr.job',
        related='role_contract_id.job3_id',
        string='Job 3',
        groups='hr.group_hr_user',
    )
    role_fte3 = fields.Float(
        related='role_contract_id.fte3',
        string='FTE 3',
        groups='hr.group_hr_user',
    )
    role_department3_id = fields.Many2one(
        'hr.department',
        related='role_contract_id.department3_id',
        string='Department 3',
        groups='hr.group_hr_user',
    )
    # Convenience related fields
    name = fields.Char(related='partner_id.name', string='Name', store=True)
    email = fields.Char(related='partner_id.email', string='Email')
    phone = fields.Char(related='partner_id.phone', string='Phone')
    image_128 = fields.Image(related='partner_id.image_128', string='Image')

    # Classes this teacher is assigned to (as teacher or assistant)
    class_ids = fields.One2many(
        'aps.class',
        compute='_compute_class_ids',
        string='Classes',
        readonly=False,
    )
    show_all_classes = fields.Boolean(
        compute='_compute_show_all_classes',
        inverse='_inverse_show_all_classes',
    )
    class_count = fields.Integer(string='Classes', compute='_compute_class_count')

    _sql_constraints = [
        ('partner_unique', 'UNIQUE(partner_id)', 'A teacher record already exists for this contact.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.partner_id and not rec.partner_id.is_teacher:
                rec.partner_id.with_context(skip_teacher_sync=True).is_teacher = True
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'active' in vals or 'partner_id' in vals:
            for rec in self.with_context(active_test=False):
                if rec.partner_id:
                    expected = rec.active
                    if rec.partner_id.is_teacher != expected:
                        rec.partner_id.with_context(skip_teacher_sync=True).is_teacher = expected
        return result

    def unlink(self):
        partners = self.mapped('partner_id')
        result = super().unlink()
        for partner in partners:
            remaining = self.env['aps.teacher'].with_context(active_test=False).search_count(
                [('partner_id', '=', partner.id)]
            )
            if not remaining and partner.is_teacher:
                partner.with_context(skip_teacher_sync=True).is_teacher = False
        return result

    @api.depends('partner_id', 'tutor_code')
    def _compute_display_name(self):
        for rec in self:
            name = rec.partner_id.name or ''
            if rec.tutor_code:
                name = f"[{rec.tutor_code}] {name}"
            rec.display_name = name

    @api.depends(
        'partner_id',
        'partner_id.employee_ids.contract_id',
        'partner_id.user_ids.employee_ids.contract_id',
    )
    def _compute_role_contract_id(self):
        for rec in self:
            employee = rec._get_linked_employee()
            rec.role_contract_id = employee.contract_id if employee else False

    def _get_linked_employee(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env['hr.employee']
        return self.env['hr.employee'].search([
            '|',
            ('work_contact_id', '=', self.partner_id.id),
            ('user_id.partner_id', '=', self.partner_id.id),
        ], limit=1)

    @api.depends('partner_id')
    def _compute_class_ids(self):
        for rec in self:
            if rec.partner_id:
                rec.class_ids = self.env['aps.class'].search([
                    '|',
                    ('teacher_ids', 'in', rec.partner_id.id),
                    ('assistant_teacher_ids', 'in', rec.partner_id.id),
                ])
            else:
                rec.class_ids = False

    def _compute_show_all_classes(self):
        for rec in self:
            rec.show_all_classes = False

    def _inverse_show_all_classes(self):
        return

    def _compute_class_count(self):
        for rec in self:
            rec.class_count = len(rec.class_ids)

    # Snapshot load fields invalidate percentages after timetable refreshes.
    @api.depends(
        'teaching_load',
        'max_load',
        'teaching_load_fte',
        'non_teaching_load',
        'max_non_teaching_load',
        'non_teaching_load_fte',
    )
    def _compute_load_percentages(self):
        """Store percentages from live timetable totals, not rounded snapshots."""
        timetable_totals = self._get_timetable_subject_totals()
        for rec in self:
            subject_totals = list(timetable_totals.get(rec.id, {}).values())
            teaching_load = round(
                sum(totals['lead_minutes'] for totals in subject_totals),
                2,
            )
            non_teaching_load = round(
                sum(totals['assistant_minutes'] for totals in subject_totals),
                2,
            )
            teaching_maximum = (rec.max_load or 0) * (rec.teaching_load_fte or 0.0)
            non_teaching_maximum = (
                (rec.max_non_teaching_load or 0) *
                (rec.non_teaching_load_fte or 0.0)
            )
            rec.teaching_load_percentage = (
                round(teaching_load / teaching_maximum * 100, 2)
                if teaching_maximum > 0
                else LOAD_PERCENTAGE_SENTINEL
            )
            rec.non_teaching_load_percentage = (
                round(non_teaching_load / non_teaching_maximum * 100, 2)
                if non_teaching_maximum > 0
                else LOAD_PERCENTAGE_SENTINEL
            )

    def _get_timetable_subject_totals(self):
        """Return rounded teaching and non-teaching minutes grouped by subject."""
        if not self:
            return {}

        rows = self.env['asctt.teacher.workload'].read_group(
            [('aps_teacher_id', 'in', self.ids)],
            ['weighted_minutes:sum'],
            ['aps_teacher_id', 'subject_id', 'subject_name', 'is_assistant'],
            lazy=False,
        )
        totals_by_subject = {}
        for row in rows:
            teacher = row.get('aps_teacher_id')
            if not teacher:
                continue
            teacher_id = teacher[0]
            subject = row.get('subject_id')
            subject_id = subject[0] if subject else False
            subject_name = row.get('subject_name') or 'Unknown'
            totals = totals_by_subject.setdefault(
                (teacher_id, subject_id, subject_name),
                {'lead': 0.0, 'assistant': 0.0},
            )
            workload_kind = 'assistant' if row.get('is_assistant') else 'lead'
            totals[workload_kind] += row.get('weighted_minutes', 0.0) or 0.0

        totals_by_teacher = {}
        for (teacher_id, subject_id, subject_name), totals in totals_by_subject.items():
            totals_by_teacher.setdefault(teacher_id, {})[
                (subject_id, subject_name)
            ] = {
                'lead_minutes': round(totals['lead'], 2),
                'assistant_minutes': round(totals['assistant'], 2),
            }
        return totals_by_teacher

    def action_view_classes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Classes',
            'res_model': 'aps.class',
            'view_mode': 'list,form',
            'domain': ['|', ('teacher_ids', 'in', self.partner_id.id),
                       ('assistant_teacher_ids', 'in', self.partner_id.id)],
        }

    def action_populate_from_contacts(self):
        """Create/restore teacher records for all partners with is_teacher=True."""
        Teacher = self.env['aps.teacher'].with_context(active_test=False)
        partners = self.env['res.partner'].search([('is_teacher', '=', True)])
        created = 0
        reactivated = 0
        for partner in partners:
            existing = Teacher.search([('partner_id', '=', partner.id)], limit=1)
            if existing:
                if not existing.active:
                    existing.active = True
                    reactivated += 1
            else:
                Teacher.create({'partner_id': partner.id})
                created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Teachers Populated',
                'message': f'{created} new record(s) created, {reactivated} reactivated.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _recompute_timetable_loads(self):
        """Recompute teaching_load and non_teaching_load from the live timetable.

        Queries ``asctt_teacher_workload`` and sums ``weighted_minutes`` per
        teacher, matching the Teacher Workload pivot's one-row-per-card
        semantics.  ``max_load`` is left unchanged — it is a manually-set cap.
        """
        if not self:
            return
        self.env.cr.execute("""
            SELECT
                aps_teacher_id,
                SUM(CASE WHEN NOT is_assistant THEN weighted_minutes ELSE 0 END) AS teaching_mins,
                SUM(CASE WHEN     is_assistant THEN weighted_minutes ELSE 0 END) AS non_teaching_mins
            FROM asctt_teacher_workload
            WHERE aps_teacher_id = ANY(%s)
            GROUP BY aps_teacher_id
        """, [self.ids])
        rows = {r[0]: (r[1], r[2]) for r in self.env.cr.fetchall()}
        for teacher in self:
            teaching, supervision = rows.get(teacher.id, (0.0, 0.0))
            teacher.teaching_load = round(teaching or 0)
            teacher.non_teaching_load = round(supervision or 0)

    def action_recompute_timetable_loads(self):
        """Button/action handler: recompute loads for the current recordset."""
        self._recompute_timetable_loads()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Loads Updated',
                'message': f'Teaching and supervision loads refreshed for {len(self)} teacher(s).',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            },
        }

    def get_timetable_workload_profile(self):
        """Return subject-level timetable minutes for the workload profile."""
        self.ensure_one()
        subject_totals = self._get_timetable_subject_totals().get(self.id, {})
        subject_ids = {
            subject_id
            for subject_id, _name in subject_totals
            if subject_id
        }
        subject_records = self.env['asctt.subject'].browse(list(subject_ids))
        category_icon_urls = {
            subject.id: (
                f"/web/image/aps.subject.category/{subject.aps_subject_category_id.id}/icon"
            )
            for subject in subject_records
            if subject.aps_subject_category_id and subject.aps_subject_category_id.icon
        }
        category_colors = {
            subject.id: subject.aps_subject_category_id.color_rgb or ''
            for subject in subject_records
            if subject.aps_subject_category_id
        }

        subjects = [
            {
                'name': name,
                'icon_url': category_icon_urls.get(subject_id, ''),
                'category_color': category_colors.get(subject_id, ''),
                'lead_minutes': totals['lead_minutes'],
                'assistant_minutes': totals['assistant_minutes'],
            }
            for (subject_id, name), totals in sorted(
                subject_totals.items(),
                key=lambda item: item[0][1].casefold(),
            )
        ]
        lead_total = round(sum(item['lead_minutes'] for item in subjects), 2)
        assistant_total = round(sum(item['assistant_minutes'] for item in subjects), 2)
        total_minutes = round(lead_total + assistant_total, 2)
        teaching_fte = self.teaching_load_fte or 0.0
        non_teaching_fte = self.non_teaching_load_fte or 0.0
        max_load = (self.max_load or 0) * teaching_fte
        max_non_teaching_load = (
            (self.max_non_teaching_load or 0) * non_teaching_fte
        )
        teaching_load_percentage = (
            round(lead_total / max_load * 100, 2)
            if max_load > 0
            else None
        )
        non_teaching_load_percentage = (
            round(assistant_total / max_non_teaching_load * 100, 2)
            if max_non_teaching_load > 0
            else None
        )
        employee = self._get_linked_employee()
        roles = []
        if self.env.user.has_group('hr.group_hr_user'):
            roles = [
                {
                    'label': 'Role 1',
                    'assigned': bool(self.role_job1_id),
                    'job': self.role_job1_id.display_name or 'Not assigned',
                    'department': (
                        self.role_department1_id.display_name or 'Not assigned'
                    ),
                    'fte': self.role_fte1 or 0.0,
                },
                {
                    'label': 'Role 2',
                    'assigned': bool(self.role_job2_id),
                    'job': self.role_job2_id.display_name or 'Not assigned',
                    'department': (
                        self.role_department2_id.display_name or 'Not assigned'
                    ),
                    'fte': self.role_fte2 or 0.0,
                },
                {
                    'label': 'Role 3',
                    'assigned': bool(self.role_job3_id),
                    'job': self.role_job3_id.display_name or 'Not assigned',
                    'department': (
                        self.role_department3_id.display_name or 'Not assigned'
                    ),
                    'fte': self.role_fte3 or 0.0,
                },
            ]

        return {
            'teacher_name': self.display_name,
            'department_name': (
                employee.department_id.display_name
                if employee and employee.department_id
                else 'Not assigned'
            ),
            'subjects': subjects,
            'lead_total': lead_total,
            'assistant_total': assistant_total,
            'total_minutes': total_minutes,
            'max_load': max_load,
            'max_non_teaching_load': max_non_teaching_load,
            'teaching_load_fte': teaching_fte,
            'non_teaching_load_fte': non_teaching_fte,
            'teaching_load_percentage': teaching_load_percentage,
            'non_teaching_load_percentage': non_teaching_load_percentage,
            'remaining_minutes': max(max_load - lead_total, 0),
            'over_limit_minutes': max(lead_total - max_load, 0),
            'roles': roles,
        }

    def action_open_workload_profile(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_teacher_workload_profile',
            'params': {'teacher_id': self.id},
        }
