import uuid
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    access_token = fields.Char(
        string='Access Token',
        copy=False,
        readonly=True,
        groups='hr.group_hr_user',
    )

    def _get_or_create_access_token(self):
        self.ensure_one()
        if not self.access_token:
            self.sudo().access_token = uuid.uuid4().hex
        return self.access_token

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('access_token'):
                vals['access_token'] = uuid.uuid4().hex
        return super().create(vals_list)

    def action_reset_access_token(self):
        for rec in self:
            rec.access_token = uuid.uuid4().hex

    def write(self, vals):
        res = super().write(vals)
        # Update faculty mobile if employee mobile changed
        if 'mobile_phone' in vals or 'work_phone' in vals:
            teacher_records = self.env['aps.teacher'].search([('emp_id', 'in', self.ids)])
            for teacher in teacher_records:
                if teacher.emp_id.id in self.ids:
                    teacher.partner_id.mobile = teacher.emp_id.mobile_phone or teacher.emp_id.work_phone
                    
        return res