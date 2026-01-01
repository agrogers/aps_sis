from odoo import models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def write(self, vals):
        res = super().write(vals)
        # Update faculty mobile if employee mobile changed
        if 'mobile_phone' in vals or 'work_phone' in vals:
            faculty_records = self.env['op.faculty'].search([('emp_id', 'in', self.ids)])
            for faculty in faculty_records:
                if faculty.emp_id.id in self.ids:
                    faculty.mobile = faculty.emp_id.mobile_phone or faculty.emp_id.work_phone
        return res