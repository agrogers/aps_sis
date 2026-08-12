from odoo import fields, models, api


class APSStudent(models.Model):
    _name = 'aps.student'
    _description = 'Student'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'partner_id'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner',
        string='Student',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    roll = fields.Char(string='Roll Number', size=20, tracking=True)
    level_id = fields.Many2one(
        'aps.level',
        string='Level',
        ondelete='set null',
        tracking=True,
        help='Current level of the student. This is automatically set from the level of the home class, if any.'
    )
    home_class_id = fields.Many2one(
        'aps.class',
        string='Home Class',
        ondelete='set null',
        tracking=True,
        help='Automatically set from enrollments whose subject category is tagged as a Home Class.',
    )
    # @api.model
    # def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
    #     """Search by partner name or roll number so that the Many2one dropdown filters correctly."""
    #     args = list(args or [])
    #     if name:
    #         domain = [
    #             '|',
    #             ('partner_id', operator, name),
    #             ('roll', operator, name),
    #         ]
    #         args = expression.AND([args, domain])
    #     return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    def _recompute_home_class(self):
        """Find the first enrolled class whose subject category has a home-class tag,
        and sync the student's level_id from it."""
        home_class_tag_names = {'Home Class', 'Pastoral Care Subject'}
        for rec in self:
            home_class = self.env['aps.class']
            for enrollment in rec.enrollment_ids.filtered(lambda e: e.state == 'enrolled'):
                category = enrollment.class_id.subject_id.category_id
                if category and any(t.name in home_class_tag_names for t in category.tag_ids):
                    home_class = enrollment.class_id
                    break
            if rec.home_class_id != home_class:
                rec.home_class_id = home_class
            # Sync level from the home class's subject level
            if home_class and home_class.subject_id.level_id:
                if rec.level_id != home_class.subject_id.level_id:
                    rec.level_id = home_class.subject_id.level_id

    active = fields.Boolean(default=True, string='Active')
    avatar_id = fields.Many2one('aps.avatar', string='Profile Avatar', ondelete='set null')
    image_128 = fields.Image(related='partner_id.image_128', string='Photo', readonly=True)
    birthday = fields.Date(
        related='partner_id.birthday',
        string='Date of Birth',
        store=True,
        readonly=True,
        help='Date of birth inherited from the linked partner.',
    )
    enrollment_ids = fields.One2many('aps.student.class', 'student_id', string='Class Enrollments')
    enrollment_count = fields.Integer(string='Classes', compute='_compute_enrollment_count')

    @api.depends('enrollment_ids')
    def _compute_enrollment_count(self):
        for student in self:
            student.enrollment_count = len(student.enrollment_ids)

    def action_view_enrollments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Class Enrollments',
            'res_model': 'aps.student.class',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def _get_cohort_keys(self):
        """Return all cohort keys for the student, e.g. ['Y10 in 25/26', 'Y11 in 26/27'].

        Each key is built from the level short name and academic year short name
        of an enrolled home class (a class whose subject category has a
        'Home Class' or 'Pastoral Care Subject' tag).
        """
        self.ensure_one()
        home_class_tag_names = {'Home Class', 'Pastoral Care Subject'}
        keys = []
        for enrollment in self.enrollment_ids.filtered(lambda e: e.state == 'enrolled'):
            category = enrollment.class_id.subject_id.category_id
            if not category or not any(t.name in home_class_tag_names for t in category.tag_ids):
                continue
            level_short = enrollment.class_id.subject_id.level_id.short_name or ''
            year_short = enrollment.class_id.academic_year_id.short_name or ''
            if level_short and year_short:
                keys.append(f"{level_short} in {year_short}")
        return keys

    @api.depends('partner_id', 'roll')
    def _compute_display_name(self):
        for rec in self:
            name = rec.partner_id.name or ''
            rec.display_name = f"{name} ({rec.roll})" if rec.roll else name

    _sql_constraints = [
        ('partner_uniq', 'unique(partner_id)', 'A student record already exists for this partner!'),
    ]

    def write(self, vals):
        result = super().write(vals)
        if 'active' in vals or 'partner_id' in vals:
            for rec in self.with_context(active_test=False):
                if rec.partner_id:
                    expected = rec.active
                    if rec.partner_id.is_student != expected:
                        rec.partner_id.with_context(skip_student_sync=True).is_student = expected
        return result

    def unlink(self):
        partners = self.mapped('partner_id')
        result = super().unlink()
        for partner in partners:
            remaining = self.env['aps.student'].with_context(active_test=False).search_count(
                [('partner_id', '=', partner.id)]
            )
            if not remaining and partner.is_student:
                partner.with_context(skip_student_sync=True).is_student = False
        return result

    def action_populate_from_contacts(self):
        """Create/restore student records for all partners with is_student=True,
        and sync their level from matching partner tags."""
        Student = self.env['aps.student'].with_context(active_test=False)
        partners = self.env['res.partner'].search([('is_student', '=', True)])
        created = 0
        reactivated = 0
        level_updated = 0
        for partner in partners:
            level = partner._get_aps_level_for_partner() if hasattr(partner, '_get_aps_level_for_partner') else self.env['aps.level']
            existing = Student.search([('partner_id', '=', partner.id)], limit=1)
            if existing:
                write_vals = {}
                if not existing.active:
                    write_vals['active'] = True
                    reactivated += 1
                if level and existing.level_id != level:
                    write_vals['level_id'] = level.id
                    level_updated += 1
                if write_vals:
                    existing.with_context(skip_student_sync=True).write(write_vals)
            else:
                new_vals = {'partner_id': partner.id}
                if level:
                    new_vals['level_id'] = level.id
                Student.with_context(skip_student_sync=True).create(new_vals)
                created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Students Populated',
                'message': (
                    f'{created} new record(s) created, '
                    f'{reactivated} reactivated, '
                    f'{level_updated} level(s) updated.'
                ),
                'type': 'success',
                'sticky': False,
            },
        }
