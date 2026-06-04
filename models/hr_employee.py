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
        # Update faculty mobile if employee mobile changed
        if 'mobile_phone' in vals or 'work_phone' in vals:
            teacher_records = self.env['aps.teacher'].search([('emp_id', 'in', self.ids)])
            for teacher in teacher_records:
                if teacher.emp_id.id in self.ids:
                    teacher.partner_id.mobile = teacher.emp_id.mobile_phone or teacher.emp_id.work_phone
                    
        return res