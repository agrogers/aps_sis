from odoo import fields, models, api


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
        help='Total minutes allocated to teaching duties.',
    )
    non_teaching_load = fields.Integer(
        string='Non-Teaching Load (minutes)',
        default=0,
        help='Total minutes allocated to non-teaching duties (admin, pastoral, etc.).',
    )
    max_load = fields.Integer(
        string='Maximum Load (minutes)',
        default=0,
        help='Maximum total minutes a teacher can be allocated.',
    )
    max_non_teaching_load = fields.Integer(
        string='Maximum Non-Teaching Load (minutes)',
        default=0,
        help='Maximum non-teaching minutes a teacher can be allocated. For',
    )
    load_details = fields.Html(
        string='Load Details',
        help='Detailed breakdown of teaching and non-teaching load allocations.',
    )
    emp_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        ondelete='set null',
        help='Linked HR employee record.',
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
        readonly=True,
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

    def _compute_class_count(self):
        for rec in self:
            rec.class_count = len(rec.class_ids)

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
        rows = self.env['asctt.teacher.workload'].read_group(
            [('aps_teacher_id', '=', self.id)],
            ['weighted_minutes:sum'],
            ['subject_id', 'subject_name', 'is_assistant'],
            lazy=False,
        )
        subject_ids = {
            row['subject_id'][0]
            for row in rows
            if row.get('subject_id')
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
        subject_totals = {}
        for row in rows:
            subject = row.get('subject_name') or 'Unknown'
            subject_id = row['subject_id'][0] if row.get('subject_id') else False
            subject_key = (subject_id, subject)
            totals = subject_totals.setdefault(
                subject_key,
                {'lead': 0.0, 'assistant': 0.0},
            )
            workload_kind = 'assistant' if row.get('is_assistant') else 'lead'
            totals[workload_kind] += row.get('weighted_minutes', 0.0) or 0.0

        subjects = [
            {
                'name': name,
                'icon_url': category_icon_urls.get(subject_id, ''),
                'category_color': category_colors.get(subject_id, ''),
                'lead_minutes': round(totals['lead'], 2),
                'assistant_minutes': round(totals['assistant'], 2),
            }
            for (subject_id, name), totals in sorted(
                subject_totals.items(),
                key=lambda item: item[0][1].casefold(),
            )
        ]
        lead_total = round(sum(item['lead_minutes'] for item in subjects), 2)
        assistant_total = round(sum(item['assistant_minutes'] for item in subjects), 2)
        total_minutes = round(lead_total + assistant_total, 2)
        max_load = self.max_load or 0
        max_non_teaching_load = self.max_non_teaching_load or 0

        return {
            'teacher_name': self.display_name,
            'department_name': (
                self.emp_id.department_id.display_name
                if self.emp_id and self.emp_id.department_id
                else 'Not assigned'
            ),
            'subjects': subjects,
            'lead_total': lead_total,
            'assistant_total': assistant_total,
            'total_minutes': total_minutes,
            'max_load': max_load,
            'max_non_teaching_load': max_non_teaching_load,
            'remaining_minutes': max(max_load - lead_total, 0),
            'over_limit_minutes': max(total_minutes - max_load, 0),
        }

    def action_open_workload_profile(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_teacher_workload_profile',
            'params': {'teacher_id': self.id},
        }
