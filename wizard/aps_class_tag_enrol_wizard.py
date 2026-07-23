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
    result_message = fields.Html(readonly=True)
    has_result = fields.Boolean(default=False)

    @api.onchange('tag_ids', 'academic_year_id')
    def _onchange_tags(self):
        """Compute classes whose tag_ids intersect with the selected tags."""
        for rec in self:
            if rec.tag_ids and rec.academic_year_id:
                rec.matching_class_ids = self.env['aps.class'].search([
                    ('tag_ids', 'in', rec.tag_ids.ids),
                    ('academic_year_id', '=', rec.academic_year_id.id),
                ])
            else:
                rec.matching_class_ids = [(5, 0, 0)]

    def action_execute(self):
        self.ensure_one()
        if not self.tag_ids:
            raise UserError(_("Please select at least one tag."))
        if not self.matching_class_ids:
            raise UserError(_("No classes match the selected tags for this academic year."))

        tag_names = self.tag_ids.mapped('name')

        # Find partners (students) whose category names match the tag names
        PartnerCategory = self.env['res.partner.category']
        matching_categories = PartnerCategory.search([('name', 'in', tag_names)])
        if not matching_categories:
            raise UserError(_(
                "No partner categories found matching tag names: %s",
                ', '.join(tag_names),
            ))

        # Find all partners who are students AND have at least one matching category
        Student = self.env['aps.student']
        students = Student.search([
            ('partner_id.category_id', 'in', matching_categories.ids),
        ])

        if not students:
            raise UserError(_(
                "No students found with partner categories matching: %s",
                ', '.join(tag_names),
            ))

        # Build a mapping: partner_id -> student record
        student_by_partner = {s.partner_id.id: s for s in students}

        enrolled_count = 0
        already_enrolled_count = 0
        no_student_count = 0
        class_lines = []

        Enrollment = self.env['aps.student.class']

        for cls in self.matching_class_ids:
            # Find partners whose categories intersect with THIS class's tags by name
            cls_tag_names = cls.tag_ids.mapped('name')
            matching_partner_cats = PartnerCategory.search([('name', 'in', cls_tag_names)])
            if not matching_partner_cats:
                class_lines.append(f"<li><b>{cls.display_name}</b> — no matching partner tags</li>")
                continue

            # Partners that have at least one matching category
            domain = [('category_id', 'in', matching_partner_cats.ids)]
            if not self.env.context.get('enrol_all_partners'):
                domain.append(('is_student', '=', True))

            partners = self.env['res.partner'].search(domain)

            cls_enrolled = 0
            cls_skipped = 0
            for partner in partners:
                student = student_by_partner.get(partner.id)
                if not student:
                    no_student_count += 1
                    continue

                existing = Enrollment.search([
                    ('student_id', '=', student.id),
                    ('home_class_id', '=', cls.id),
                ], limit=1)
                if existing:
                    already_enrolled_count += 1
                    cls_skipped += 1
                    continue

                Enrollment.create({
                    'student_id': student.id,
                    'home_class_id': cls.id,
                    'start_date': self.academic_year_id.start_date,
                    'end_date': self.academic_year_id.end_date,
                })
                enrolled_count += 1
                cls_enrolled += 1

            class_lines.append(
                f"<li><b>{cls.display_name}</b> — {cls_enrolled} enrolled"
                + (f", {cls_skipped} already enrolled" if cls_skipped else "")
                + f" ({len(partners)} partners found)</li>"
            )

        summary = (
            f"<b>{enrolled_count}</b> student(s) enrolled across "
            f"{len(self.matching_class_ids)} class(es)."
        )
        if already_enrolled_count:
            summary += f"<br/><b>{already_enrolled_count}</b> already enrolled (skipped)."
        if no_student_count:
            summary += f"<br/><b>{no_student_count}</b> partner(s) had no APS student record (skipped)."

        self.result_message = f"<p>{summary}</p><ul>{''.join(class_lines)}</ul>"
        self.has_result = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aps.class.tag.enrol.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }