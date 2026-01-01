from odoo import api, fields, models


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    last_name = fields.Char(required=False)

    @api.onchange('emp_id')
    def _onchange_emp_id(self):
        if self.emp_id:
            employee = self.emp_id
            # Populate from employee only if fields are empty
            if not self.first_name:
                self.first_name = employee.name
            if not self.partner_id:
                self.partner_id = employee.user_id.partner_id.id if employee.user_id else (employee.address_home_id.id if employee.address_home_id else False)
            if not self.gender:
                self.gender = employee.gender
            if not self.birth_date:
                self.birth_date = employee.birthday
            # Add other fields as needed, e.g., phone, email, etc.
            if not self.phone:
                self.phone = employee.work_phone or employee.mobile_phone
            if not self.mobile:
                self.mobile = employee.mobile_phone or (employee.user_id.partner_id.mobile if employee.user_id and employee.user_id.partner_id else False)
            if not self.email:
                self.email = employee.work_email
            # If there are other faculty-specific fields, map them here
