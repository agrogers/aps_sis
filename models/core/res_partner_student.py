from odoo import fields, models, api


class ResPartnerStudent(models.Model):
    _inherit = 'res.partner'

    aps_student_count = fields.Integer(
        compute='_compute_aps_student_count',
        string='APS Student Records',
    )

    def _compute_aps_student_count(self):
        Student = self.env['aps.student'].with_context(active_test=False)
        for rec in self:
            rec.aps_student_count = Student.search_count([('partner_id', '=', rec.id)])

    def action_open_aps_student(self):
        self.ensure_one()
        student = self.env['aps.student'].with_context(active_test=False).search(
            [('partner_id', '=', self.id)], limit=1
        )
        if not student:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': 'Student',
            'res_model': 'aps.student',
            'res_id': student.id,
            'view_mode': 'form',
        }

    def _get_aps_level_for_partner(self):
        """Find the first matching aps.level whose tag_ids intersect with this partner's tags."""
        self.ensure_one()
        if not self.category_id:
            return self.env['aps.level']
        return self.env['aps.level'].search(
            [('tag_ids', 'in', self.category_id.ids)],
            limit=1,
            order='sequence',
        )

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get('skip_student_sync'):
            return result
        Student = self.env['aps.student'].with_context(active_test=False)
        if 'is_student' in vals:
            for partner in self:
                existing = Student.search([('partner_id', '=', partner.id)], limit=1)
                if partner.is_student:
                    level = partner._get_aps_level_for_partner()
                    if existing:
                        write_vals = {}
                        if not existing.active:
                            write_vals['active'] = True
                        if level and existing.level_id != level:
                            write_vals['level_id'] = level.id
                        if write_vals:
                            existing.with_context(skip_student_sync=True).write(write_vals)
                    else:
                        new_vals = {'partner_id': partner.id}
                        if level:
                            new_vals['level_id'] = level.id
                        Student.with_context(skip_student_sync=True).create(new_vals)
                else:
                    if existing and existing.active:
                        existing.with_context(skip_student_sync=True).active = False
        elif 'category_id' in vals:
            # Tags changed — re-sync level for active student records
            for partner in self:
                existing = Student.search([('partner_id', '=', partner.id)], limit=1)
                if existing and existing.active:
                    level = partner._get_aps_level_for_partner()
                    existing.with_context(skip_student_sync=True).level_id = level.id if level else False
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_student_sync'):
            Student = self.env['aps.student'].with_context(active_test=False)
            for record in records:
                if record.is_student:
                    existing = Student.search([('partner_id', '=', record.id)], limit=1)
                    if not existing:
                        level = record._get_aps_level_for_partner()
                        new_vals = {'partner_id': record.id}
                        if level:
                            new_vals['level_id'] = level.id
                        Student.with_context(skip_student_sync=True).create(new_vals)
        return records
