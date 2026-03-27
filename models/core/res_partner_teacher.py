from odoo import fields, models, api


class ResPartnerTeacher(models.Model):
    _inherit = 'res.partner'

    teacher_count = fields.Integer(
        compute='_compute_teacher_count',
        string='Teacher Records',
    )

    def _compute_teacher_count(self):
        Teacher = self.env['aps.teacher'].with_context(active_test=False)
        for rec in self:
            rec.teacher_count = Teacher.search_count([('partner_id', '=', rec.id)])

    def action_open_teacher(self):
        self.ensure_one()
        teacher = self.env['aps.teacher'].with_context(active_test=False).search(
            [('partner_id', '=', self.id)], limit=1
        )
        if not teacher:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': 'Teacher',
            'res_model': 'aps.teacher',
            'res_id': teacher.id,
            'view_mode': 'form',
        }

    def write(self, vals):
        result = super().write(vals)
        if 'is_teacher' in vals and not self.env.context.get('skip_teacher_sync'):
            Teacher = self.env['aps.teacher'].with_context(active_test=False)
            for partner in self:
                existing = Teacher.search([('partner_id', '=', partner.id)], limit=1)
                if partner.is_teacher:
                    if existing:
                        if not existing.active:
                            existing.with_context(skip_teacher_sync=True).active = True
                    else:
                        Teacher.with_context(skip_teacher_sync=True).create({'partner_id': partner.id})
                else:
                    if existing and existing.active:
                        existing.with_context(skip_teacher_sync=True).active = False
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_teacher_sync'):
            Teacher = self.env['aps.teacher'].with_context(active_test=False)
            for record in records:
                if record.is_teacher:
                    existing = Teacher.search([('partner_id', '=', record.id)], limit=1)
                    if not existing:
                        Teacher.with_context(skip_teacher_sync=True).create({'partner_id': record.id})
        return records
