from odoo import api, fields, models


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    last_name = fields.Char(required=False)
    birth_date = fields.Date(required=False, default="2000-01-01")

    def _compute_full_name(self):
        """Compute the full name from first, middle, and last names."""
        fname = self.first_name or ""
        mname = self.middle_name or ""
        lname = self.last_name or ""
        return " ".join(filter(None, [fname, mname, lname])) or "New"

    @api.model_create_multi
    def create(self, vals_list):
        """Ensure name is properly computed on create."""
        for vals in vals_list:
            # Compute name from name parts if not explicitly provided
            if 'name' not in vals or not vals.get('name'):
                fname = vals.get('first_name') or ""
                mname = vals.get('middle_name') or ""
                lname = vals.get('last_name') or ""
                vals['name'] = " ".join(filter(None, [fname, mname, lname])) or "New"
        return super().create(vals_list)

    def write(self, vals):
        """Ensure name is recomputed when name parts change."""
        result = super().write(vals)
        # If any name part changed, recompute name
        if any(field in vals for field in ('first_name', 'middle_name', 'last_name')):
            for record in self:
                new_name = record._compute_full_name()
                if record.name != new_name:
                    # Use SQL to avoid recursion
                    self.env.cr.execute(
                        "UPDATE res_partner SET name = %s WHERE id = %s",
                        (new_name, record.partner_id.id)
                    )
                    record.partner_id.invalidate_recordset(['name'])
        return result

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
