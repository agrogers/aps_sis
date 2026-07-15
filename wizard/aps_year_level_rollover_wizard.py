from odoo import _, fields, models
from odoo.exceptions import UserError


class APSYearLevelRolloverWizard(models.TransientModel):
    _name = 'aps.year.level.rollover.wizard'
    _description = 'Roll Students to Next Academic Level'

    partner_ids = fields.Many2many(
        'res.partner',
        relation='aps_year_level_rollover_wizard_partner_rel',
        column1='wizard_id',
        column2='partner_id',
        string='Students',
        domain=[('is_student', '=', True)],
        required=True,
    )
    result_message = fields.Html(readonly=True)
    has_result = fields.Boolean(default=False)

    def _next_level_map(self):
        levels = self.env['aps.level'].search([], order='sequence, name, id')
        next_map = {}
        for idx, level in enumerate(levels):
            next_map[level.id] = levels[idx + 1] if idx + 1 < len(levels) else self.env['aps.level']
        return next_map

    def action_apply(self):
        self.ensure_one()
        if not self.partner_ids:
            raise UserError(_('Please select at least one student.'))

        students = self.env['aps.student'].search([
            ('partner_id', 'in', self.partner_ids.ids),
            ('active', '=', True),
        ])
        student_by_partner = {student.partner_id.id: student for student in students}
        next_map = self._next_level_map()

        selected_students = []
        skipped_lines = []

        for partner in self.partner_ids:
            student = student_by_partner.get(partner.id)
            if not student:
                skipped_lines.append(
                    f'<li><b>{partner.display_name}</b> - no active APS student record.</li>'
                )
                continue
            if not student.level_id:
                skipped_lines.append(
                    f'<li><b>{partner.display_name}</b> - no current academic level.</li>'
                )
                continue
            next_level = next_map.get(student.level_id.id)
            if not next_level:
                skipped_lines.append(
                    f'<li><b>{partner.display_name}</b> - already at highest level '
                    f'(<em>{student.level_id.display_name}</em>).</li>'
                )
                continue
            selected_students.append(student)

        # Process oldest to youngest by descending sequence.
        selected_students.sort(key=lambda s: (s.level_id.sequence, s.level_id.id), reverse=True)

        promoted = 0
        promoted_lines = []

        for student in selected_students:
            partner = student.partner_id
            current_level = student.level_id
            next_level = next_map[current_level.id]

            old_tag_ids = set(current_level.tag_ids.ids)
            new_tag_ids = set(next_level.tag_ids.ids)
            partner_tag_ids = set(partner.category_id.ids)

            updated_partner_tags = (partner_tag_ids - old_tag_ids) | new_tag_ids

            partner.write({'category_id': [(6, 0, sorted(updated_partner_tags))]})
            student.with_context(skip_student_sync=True).write({'level_id': next_level.id})

            promoted += 1
            promoted_lines.append(
                f'<li><b>{partner.display_name}</b>: '
                f'<em>{current_level.display_name}</em> -&gt; '
                f'<em>{next_level.display_name}</em></li>'
            )

        summary_lines = [
            f'<p><b>{promoted}</b> student(s) promoted.</p>',
            f'<p><b>{len(skipped_lines)}</b> student(s) skipped.</p>',
        ]
        if promoted_lines:
            summary_lines.append('<p><strong>Promoted</strong></p><ul>' + ''.join(promoted_lines) + '</ul>')
        if skipped_lines:
            summary_lines.append('<p><strong>Skipped</strong></p><ul>' + ''.join(skipped_lines) + '</ul>')

        self.result_message = ''.join(summary_lines)
        self.has_result = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aps.year.level.rollover.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
