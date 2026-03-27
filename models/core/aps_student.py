from odoo import fields, models, api


class APSStudent(models.Model):
    _name = 'aps.student'
    _description = 'Student'
    _order = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner',
        string='Student',
        required=True,
        ondelete='cascade',
    )
    roll = fields.Char(string='Roll Number', size=20)
    level_id = fields.Many2one(
        'aps.level',
        string='Level',
        ondelete='set null',
    )
    home_class_id = fields.Many2one(
        'aps.class',
        string='Home Class',
        ondelete='set null',
        help='Automatically set from enrollments whose subject category is tagged as a Home Class.',
    )

    def _recompute_home_class(self):
        """Find the first enrolled class whose subject category has a home-class tag."""
        home_class_tag_names = {'Home Class', 'Pastoral Care Subject'}
        for rec in self:
            home_class = self.env['aps.class']
            for enrollment in rec.enrollment_ids.filtered(lambda e: e.state == 'enrolled'):
                category = enrollment.home_class_id.subject_id.category_id
                if category and any(t.name in home_class_tag_names for t in category.tag_ids):
                    home_class = enrollment.home_class_id
                    break
            if rec.home_class_id != home_class:
                rec.home_class_id = home_class

    active = fields.Boolean(default=True, string='Active')
    enrollment_ids = fields.One2many('aps.student.class', 'student_id', string='Class Enrollments')

    @api.depends('partner_id', 'roll')
    def _compute_display_name(self):
        for rec in self:
            name = rec.partner_id.name or ''
            rec.display_name = f"{name} ({rec.roll})" if rec.roll else name

    _sql_constraints = [
        ('partner_uniq', 'unique(partner_id)', 'A student record already exists for this partner!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.partner_id and not rec.partner_id.is_student:
                rec.partner_id.with_context(skip_student_sync=True).is_student = True
        return records

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
