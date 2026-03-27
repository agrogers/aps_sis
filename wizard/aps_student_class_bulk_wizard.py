from odoo import api, fields, models


class APSStudentClassBulkWizard(models.TransientModel):
    _name = 'aps.student.class.bulk.wizard'
    _description = 'Bulk Maintain Student Class Enrollments'

    academic_year_id = fields.Many2one(
        'aps.academic.year',
        string='Academic Year',
        default=lambda self: self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        ),
    )
    partner_ids = fields.Many2many(
        'res.partner',
        relation='aps_scbulk_partner_rel',
        column1='wizard_id',
        column2='partner_id',
        string='Students',
        domain=[('is_student', '=', True)],
    )
    class_ids = fields.Many2many(
        'aps.class',
        relation='aps_scbulk_class_rel',
        column1='wizard_id',
        column2='class_id',
        string='Classes',
    )
    operation = fields.Selection(
        [('add', 'Add Classes'), ('remove', 'Remove Classes')],
        default='add',
        required=True,
        string='Operation',
    )
    warning_message = fields.Html(compute='_compute_warning_message')
    has_warnings = fields.Boolean(compute='_compute_warning_message')

    @api.onchange('academic_year_id')
    def _onchange_academic_year_id(self):
        self.class_ids = [(5, 0, 0)]

    @api.depends('partner_ids', 'class_ids', 'operation')
    def _compute_warning_message(self):
        for rec in self:
            if rec.operation != 'add' or not rec.partner_ids or not rec.class_ids:
                rec.warning_message = False
                rec.has_warnings = False
                continue

            students = self.env['aps.student'].search(
                [('partner_id', 'in', rec.partner_ids.ids)]
            )
            student_by_partner = {s.partner_id.id: s for s in students}
            lines = []
            for partner in rec.partner_ids:
                student = student_by_partner.get(partner.id)
                if not student:
                    continue
                student_level = student.level_id
                if not student_level:
                    continue
                for cls in rec.class_ids:
                    class_level = cls.subject_id.level_id if cls.subject_id else False
                    if class_level and student_level != class_level:
                        lines.append(
                            f"<li>Student <b>{partner.name}</b> "
                            f"(Level: <em>{student_level.display_name}</em>) → "
                            f"Class <b>{cls.display_name}</b> "
                            f"(Level: <em>{class_level.display_name}</em>)</li>"
                        )

            if lines:
                rec.warning_message = (
                    '<p><strong>Level Mismatch Warning</strong> — the following '
                    'students will be added to classes outside their academic level:</p>'
                    '<ul>' + ''.join(lines) + '</ul>'
                )
                rec.has_warnings = True
            else:
                rec.warning_message = False
                rec.has_warnings = False

    def action_apply(self):
        self.ensure_one()
        if not self.partner_ids or not self.class_ids:
            return {'type': 'ir.actions.act_window_close'}

        students = self.env['aps.student'].search(
            [('partner_id', 'in', self.partner_ids.ids)]
        )

        if self.operation == 'add':
            Enrollment = self.env['aps.student.class']
            for student in students:
                for cls in self.class_ids:
                    existing = Enrollment.with_context(active_test=False).search(
                        [('student_id', '=', student.id), ('home_class_id', '=', cls.id)],
                        limit=1,
                    )
                    if existing:
                        if not existing.active:
                            existing.write({'active': True})
                    else:
                        Enrollment.create({
                            'student_id': student.id,
                            'home_class_id': cls.id,
                        })

        elif self.operation == 'remove':
            enrollments = self.env['aps.student.class'].search([
                ('student_id', 'in', students.ids),
                ('home_class_id', 'in', self.class_ids.ids),
            ])
            enrollments.write({'active': False})

        return {'type': 'ir.actions.act_window_close'}
