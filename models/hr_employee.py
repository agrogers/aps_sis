from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    access_token = fields.Char(
        string='Access Token',
        related='user_id.partner_id.access_token',
        readonly=True,
        store=False,
        groups='hr.group_hr_user',
    )

    def _get_or_create_access_token(self):
        self.ensure_one()
        partner = self.sudo().user_id.partner_id
        return partner._get_or_create_access_token() if partner else ''

    def action_reset_access_token(self):
        for rec in self:
            partner = rec.sudo().user_id.partner_id
            if partner:
                partner.action_reset_access_token()

    def write(self, vals):
        res = super().write(vals)
        if 'mobile_phone' in vals or 'work_phone' in vals:
            contact_ids = self.mapped('work_contact_id').ids + self.mapped('user_id.partner_id').ids
            teacher_records = self.env['aps.teacher'].search([
                ('partner_id', 'in', contact_ids),
            ])
            for teacher in teacher_records:
                employee = self.filtered(
                    lambda rec: teacher.partner_id in (
                        rec.work_contact_id | rec.user_id.partner_id
                    )
                )[:1]
                if employee:
                    teacher.partner_id.mobile = employee.mobile_phone or employee.work_phone

        return res