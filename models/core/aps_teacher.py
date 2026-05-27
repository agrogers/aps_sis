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
        string='Teaching Load (min)',
        default=0,
        help='Total minutes allocated to teaching duties.',
    )
    non_teaching_load = fields.Integer(
        string='Non-Teaching Load (min)',
        default=0,
        help='Total minutes allocated to non-teaching duties (admin, pastoral, etc.).',
    )
    max_load = fields.Integer(
        string='Maximum Load (min)',
        default=0,
        help='Maximum total minutes a teacher can be allocated.',
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

        Queries ``asctt_flat_row`` and sums ``weighted_minutes`` per teacher,
        split into teaching vs supervision rows.  ``max_load`` is left
        unchanged — it is a manually-set cap.
        """
        if not self:
            return
        self.env.cr.execute("""
            SELECT
                aps_teacher_id,
                SUM(CASE WHEN NOT is_assistant THEN weighted_minutes ELSE 0 END) AS teaching_mins,
                SUM(CASE WHEN     is_assistant THEN weighted_minutes ELSE 0 END) AS non_teaching_mins
            FROM asctt_flat_row
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
            },
        }
