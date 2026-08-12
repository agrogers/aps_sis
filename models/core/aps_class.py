from odoo import fields, models, api


class APSClass(models.Model):
    _name = 'aps.class'
    _description = 'Class'
    _order = 'name'

    identifier = fields.Char(
        string='Identifier',
        size=10,
        required=False,
        help='Short code for this class section, e.g. A, B, 1, 2',
    )
    subject_id = fields.Many2one(
        'aps.subject',
        string='Subject',
        ondelete='restrict',
    )
    code = fields.Char(
        string='Code',
        compute='_compute_code_name',
        store=True,
        readonly=False,
        help='Defaults to subject code + identifier',
    )
    name = fields.Char(
        string='Name',
        compute='_compute_code_name',
        store=True,
        readonly=False,
        required=True,
        help='Defaults to subject name + identifier',
    )
    academic_year_id = fields.Many2one(
        'aps.academic.year',
        string='Academic Year',
        ondelete='set null',
        default=lambda self: self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        ),
    )
    teacher_ids = fields.Many2many(
        'res.partner',
        relation='aps_class_teacher_rel',
        column1='class_id',
        column2='partner_id',
        string='Teachers',
        domain=[('is_teacher', '=', True)],
    )
    assistant_teacher_ids = fields.Many2many(
        'res.partner',
        relation='aps_class_assistant_teacher_rel',
        column1='class_id',
        column2='partner_id',
        string='Assistant Teachers',
        domain=[('is_teacher', '=', True)],
    )
    active = fields.Boolean(default=True, string='Active')
    enrollment_ids = fields.One2many('aps.student.class', 'class_id', string='Enrolled Students')
    tag_ids = fields.Many2many(
        'aps.class.tag',
        relation='aps_class_tag_rel',
        column1='class_id',
        column2='tag_id',
        string='Tags',
    )
    enrollment_count = fields.Integer(
        string='Students',
        compute='_compute_enrollment_count',
        store=True,
    )

    def action_view_enrollments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Enrolled Students',
            'res_model': 'aps.student.class',
            'view_mode': 'list,form',
            'domain': [('class_id', '=', self.id)],
            'context': {'default_class_id': self.id},
        }

    @api.depends('enrollment_ids')
    def _compute_enrollment_count(self):
        for rec in self:
            rec.enrollment_count = len(rec.enrollment_ids)

    @api.depends('subject_id', 'subject_id.code', 'subject_id.name', 'identifier')
    def _compute_code_name(self):
        for rec in self:
            if rec.subject_id:
                rec.code = f"{rec.subject_id.code or ''}{rec.identifier if rec.identifier else ''}".strip()
                rec.name = f"{rec.subject_id.name} {rec.identifier if rec.identifier else ''}".strip()
            else:
                rec.code = False
                rec.name = False

    @api.depends('name', 'academic_year_id.short_name', 'academic_year_id')
    def _compute_display_name(self):
        for rec in self:
            name = rec.code or rec.name or ''
            if rec.academic_year_id:
                name = f"{name} [{rec.academic_year_id.short_name or rec.academic_year_id.name}]"
            rec.display_name = name

    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        if name:
            args = [('code', operator, name)] + args
        return super()._name_search(name='', args=args, operator=operator, limit=limit, name_get_uid=name_get_uid)

    copy_students_from_class_id = fields.Many2one(
        'aps.class',
        string='Copy Students From',
        help='Select a class to copy enrolled students into this class.',
    )
    copy_from_aca_year_id = fields.Many2one(
        'aps.academic.year',
        string='Filter by Academic Year',
        help='Filter the class list by academic year. Leave empty to show all classes.',
    )
    copy_students_preview_ids = fields.Many2many(
        'res.partner',
        string='Students to Copy',
        compute='_compute_copy_students_preview',
        help='Students enrolled in the selected source class.',
    )

    @api.depends('copy_students_from_class_id')
    def _compute_copy_students_preview(self):
        for rec in self:
            if rec.copy_students_from_class_id:
                rec.copy_students_preview_ids = (
                    rec.copy_students_from_class_id.enrollment_ids.mapped('student_id.partner_id')
                )
            else:
                rec.copy_students_preview_ids = [(5, 0, 0)]

    @api.onchange('copy_from_aca_year_id', 'copy_students_from_class_id')
    def _onchange_copy_from_aca_year_id(self):
        """Clear the selected class if it no longer matches the selected academic year."""
        if self.copy_students_from_class_id and self.copy_from_aca_year_id:
            if self.copy_students_from_class_id.academic_year_id != self.copy_from_aca_year_id:
                self.copy_students_from_class_id = False

    def action_copy_students(self):
        self.ensure_one()
        if not self.copy_students_from_class_id:
            return
        source = self.copy_students_from_class_id
        Enrollment = self.env['aps.student.class']
        for enrollment in source.enrollment_ids:
            existing = Enrollment.with_context(active_test=False).search([
                ('student_id', '=', enrollment.student_id.id),
                ('class_id', '=', self.id),
            ], limit=1)
            if existing:
                if not existing.active:
                    existing.write({'active': True})
            else:
                Enrollment.create({
                    'student_id': enrollment.student_id.id,
                    'class_id': self.id,
                })
        self.copy_students_from_class_id = False
