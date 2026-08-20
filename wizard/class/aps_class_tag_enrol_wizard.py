from odoo import api, fields, models, _
from odoo.exceptions import UserError


class APSClassTagEnrolWizard(models.TransientModel):
    _name = 'aps.class.tag.enrol.wizard'
    _description = 'Auto-Enrol Students by Tag'

    academic_year_id = fields.Many2one(
        'aps.academic.year',
        string='Academic Year',
        required=True,
        default=lambda self: self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        ),
    )
    tag_ids = fields.Many2many(
        'aps.class.tag',
        relation='aps_class_tag_enrol_wizard_tag_rel',
        column1='wizard_id',
        column2='tag_id',
        string='Tags',
        required=True,
    )
    matching_class_ids = fields.Many2many(
        'aps.class',
        relation='aps_class_tag_enrol_wizard_matching_class_rel',
        column1='wizard_id',
        column2='class_id',
        string='Matching Classes',
        readonly=True,
    )
    also_remove_students = fields.Boolean(
        string='Also Remove Students',
        default=True,
        help=(
            'Remove active enrolments when the student no longer matches the '
            'class tags. Enrolments shorter than 30 days are deleted; older '
            'enrolments are withdrawn.'
        ),
    )
    result_message = fields.Html(readonly=True)
    has_result = fields.Boolean(default=False)

    def _get_matching_classes(self):
        self.ensure_one()
        if not self.tag_ids or not self.academic_year_id:
            return self.env['aps.class']
        return self.env['aps.class'].search([
            ('tag_ids', 'in', self.tag_ids.ids),
            ('academic_year_id', '=', self.academic_year_id.id),
        ])

    @api.onchange('tag_ids', 'academic_year_id')
    def _onchange_tags(self):
        """Compute classes whose tag_ids intersect with the selected tags."""
        for rec in self:
            rec.matching_class_ids = rec._get_matching_classes()

    def _remove_non_matching_enrolments(self, cls, matching_partner_ids, enrollment_model):
        """Remove active enrolled students who no longer match a class's tags."""
        today = fields.Date.today()
        candidates = enrollment_model.search([
            ('class_id', '=', cls.id),
            ('active', '=', True),
            ('state', '=', 'enrolled'),
        ])
        removed_count = 0
        withdrawn_count = 0
        skipped_count = 0

        for enrollment in candidates:
            partner = enrollment.student_id.partner_id
            if partner.id in matching_partner_ids:
                continue
            if not enrollment.start_date:
                skipped_count += 1
                continue

            duration_days = (today - enrollment.start_date).days
            if duration_days < 30:
                enrollment.unlink()
                removed_count += 1
            else:
                enrollment.action_withdraw()
                withdrawn_count += 1

        return removed_count, withdrawn_count, skipped_count

    def action_execute(self):
        self.ensure_one()
        if not self.tag_ids:
            raise UserError(_("Please select at least one tag."))

        # Recompute this on the server.  The displayed value is populated by
        # onchange, but readonly many2many values are not guaranteed to be
        # written back to a transient record before an object button is called.
        matching_classes = self._get_matching_classes()
        if not matching_classes:
            raise UserError(_("No classes match the selected tags for this academic year."))

        tag_names = self.tag_ids.mapped('name')

        # Find partners (students) whose category names match the tag names
        PartnerCategory = self.env['res.partner.category']
        matching_categories = PartnerCategory.search([('name', 'in', tag_names)])
        if not matching_categories and not self.also_remove_students:
            raise UserError(_(
                "No partner categories found matching tag names: %s",
                ', '.join(tag_names),
            ))

        # Find all partners who are students AND have at least one matching category
        Student = self.env['aps.student']
        students = Student.search([
            ('partner_id.category_id', 'in', matching_categories.ids),
        ])

        if not students and not self.also_remove_students:
            raise UserError(_(
                "No students found with partner categories matching: %s",
                ', '.join(tag_names),
            ))

        # Build a mapping: partner_id -> student record
        student_by_partner = {s.partner_id.id: s for s in students}

        enrolled_count = 0
        already_enrolled_count = 0
        no_student_count = 0
        removed_count = 0
        withdrawn_count = 0
        removal_skipped_count = 0
        class_lines = []

        Enrollment = self.env['aps.student.class']

        for cls in matching_classes:
            # Find partners whose categories intersect with THIS class's tags by name
            cls_tag_names = cls.tag_ids.mapped('name')
            matching_partner_cats = PartnerCategory.search([('name', 'in', cls_tag_names)])
            matching_partner_ids = set()
            if matching_partner_cats:
                matching_partner_ids = set(
                    self.env['res.partner'].search([
                        ('category_id', 'in', matching_partner_cats.ids),
                        ('is_student', '=', True),
                    ]).ids
                )

            # Partners that have at least one matching category
            domain = [('category_id', 'in', matching_partner_cats.ids)]
            if not self.env.context.get('enrol_all_partners'):
                domain.append(('is_student', '=', True))

            partners = (
                self.env['res.partner'].search(domain)
                if matching_partner_cats
                else self.env['res.partner']
            )

            cls_enrolled = 0
            cls_skipped = 0
            for partner in partners:
                student = student_by_partner.get(partner.id)
                if not student:
                    no_student_count += 1
                    continue

                existing = Enrollment.search([
                    ('student_id', '=', student.id),
                    ('class_id', '=', cls.id),
                ], limit=1)
                if existing:
                    already_enrolled_count += 1
                    cls_skipped += 1
                    continue

                Enrollment.create({
                    'student_id': student.id,
                    'class_id': cls.id,
                    'start_date': self.academic_year_id.start_date,
                    'end_date': self.academic_year_id.end_date,
                })
                enrolled_count += 1
                cls_enrolled += 1

            cls_removed = cls_withdrawn = cls_removal_skipped = 0
            if self.also_remove_students:
                (
                    cls_removed,
                    cls_withdrawn,
                    cls_removal_skipped,
                ) = self._remove_non_matching_enrolments(
                    cls,
                    matching_partner_ids,
                    Enrollment,
                )
                removed_count += cls_removed
                withdrawn_count += cls_withdrawn
                removal_skipped_count += cls_removal_skipped

            class_lines.append(
                f"<li><b>{cls.display_name}</b> — {cls_enrolled} enrolled"
                + (f", {cls_skipped} already enrolled" if cls_skipped else "")
                + (f", {cls_removed} deleted" if cls_removed else "")
                + (f", {cls_withdrawn} withdrawn" if cls_withdrawn else "")
                + (f", {cls_removal_skipped} missing start date (skipped)"
                   if cls_removal_skipped else "")
                + f" ({len(partners)} partners found)</li>"
            )

        summary = (
            f"<b>{enrolled_count}</b> student(s) enrolled across "
            f"{len(matching_classes)} class(es)."
        )
        if already_enrolled_count:
            summary += f"<br/><b>{already_enrolled_count}</b> already enrolled (skipped)."
        if no_student_count:
            summary += f"<br/><b>{no_student_count}</b> partner(s) had no APS student record (skipped)."
        if self.also_remove_students:
            summary += f"<br/><b>{removed_count}</b> enrolment(s) deleted (under 30 days)."
            summary += f"<br/><b>{withdrawn_count}</b> enrolment(s) withdrawn (30 days or more)."
            if removal_skipped_count:
                summary += (
                    f"<br/><b>{removal_skipped_count}</b> enrolment(s) had no start date "
                    "(skipped)."
                )

        self.result_message = f"<p>{summary}</p><ul>{''.join(class_lines)}</ul>"
        self.has_result = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aps.class.tag.enrol.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }