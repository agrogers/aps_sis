from odoo import fields, models, api
from odoo.osv import expression


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
    team_id = fields.Many2one(
        'aps.team',
        string='Team',
        ondelete='set null',
        tracking=True,
        help='Team assigned to this student for team-based scoring and competitions.',
    )
    team_color = fields.Char(
        related='team_id.color',
        string='Team Color',
        readonly=True,
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
    enrollment_ids = fields.One2many('aps.student.class', 'student_id', string='Class Enrollments')

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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.partner_id and not rec.partner_id.is_student:
                rec.partner_id.with_context(skip_student_sync=True).is_student = True
            if rec.partner_id and 'team_id' in rec._fields and rec.team_id:
                rec._sync_partner_team_tags()
        return records

    def _sync_partner_team_tags(self):
        """Make the student's team tags on the contact match ``team_id``.

        Team tags are additive. Existing contact tags are always preserved;
        selecting a team only adds that team's tags to the contact.
        """
        for student in self:
            if not student.partner_id:
                continue
            current_tag_ids = set(student.partner_id.category_id.ids)
            selected_tag_ids = set(student.team_id.tag_ids.ids) if student.team_id else set()
            new_tag_ids = current_tag_ids | selected_tag_ids
            if new_tag_ids != current_tag_ids:
                student.partner_id.with_context(
                    skip_student_sync=True,
                    skip_student_team_tag_sync=True,
                ).write({'category_id': [(6, 0, list(new_tag_ids))]})

    @api.model
    def cron_sync_team_tags(self):
        """Ensure student teams and their contact tags are synchronized.

        Existing student teams remain authoritative. A missing team is filled
        from the first team matching the partner's tags, while team tags are
        then added to the contact without removing any existing tags.
        """
        students = self.sudo().with_context(active_test=False).search([
            ('partner_id', '!=', False),
        ])
        for student in students:
            if not student.team_id and hasattr(student.partner_id, '_get_aps_team_for_partner'):
                team = student.partner_id._get_aps_team_for_partner()
                if team:
                    student.with_context(skip_student_team_tag_sync=True).write({
                        'team_id': team.id,
                    })
            student._sync_partner_team_tags()
        return True

    def write(self, vals):
        result = super().write(vals)
        if 'team_id' in vals and not self.env.context.get('skip_student_team_tag_sync'):
            self._sync_partner_team_tags()
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
