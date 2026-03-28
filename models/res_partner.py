from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Ensure gender field exists (it's standard in Odoo)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender')

    # Redefine to change labels
    is_parent = fields.Boolean("Parent")
    is_student = fields.Boolean("Student")
    # Add new field
    is_teacher = fields.Boolean("Teacher")

    student_count = fields.Integer(compute='_compute_student_count', string='Student Count')
    submission_ids = fields.One2many('aps.resource.submission', 'student_id', string='Submissions')

    def _compute_student_count(self):
        for rec in self:
            if rec.is_student:
                student = self.env['op.student'].search([('partner_id', '=', rec.id)], limit=1)
                rec.student_count = 1 if student else 0
            else:
                rec.student_count = 0

    def action_open_student(self):
        student = self.env['op.student'].search([('partner_id', '=', self.id)], limit=1)
        if student:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'op.student',
                'res_id': student.id,
                'view_mode': 'form',
            }

    def write(self, vals):
        res = super().write(vals)
        gender_map = {'male': 'm', 'female': 'f', 'other': 'o'}

        for partner in self:

            user = partner.user_ids[:1]
            student = self.env['op.student'].search([('partner_id', '=', partner.id)], limit=1)
            employee = None if not user else self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            faculty = None if not employee else self.env['op.faculty'].search([('emp_id', '=', employee.id)], limit=1)
                            
            if 'gender' in vals:
                # Sync to student
                if student:
                    student.write({'gender': gender_map.get(vals['gender'], 'm')})
                # Sync to employee
                if employee:
                    employee.write({'gender': vals['gender']})
                # Sync to faculty
                if faculty:
                    faculty.write({'gender': partner.gender})

            if 'is_student' in vals:
                category = self.env['res.partner.category'].search([('name', '=', 'Student')], limit=1)
                if not category:
                    category = self.env['res.partner.category'].create({'name': 'Student'})
                
                if vals['is_student']:
                    # Add Student category and create student record
                    if category.id not in partner.category_id.ids:
                        partner.category_id = [(4, category.id)]
                    # Check if student record exists for this partner
                    student = self.env['op.student'].search([('partner_id', '=', partner.id)], limit=1)
                    if not student:
                        student = self.env['op.student'].create({
                            'partner_id': partner.id,
                            'gender': gender_map.get(partner.gender, 'o'),
                        })
                        # Trigger onchange to populate fields
                        student._onchange_partner_id()
                else:
                    # Remove Student category and delete student record
                    if category.id in partner.category_id.ids:
                        partner.category_id = [(3, category.id)]
                    # Delete associated student record
                    student = self.env['op.student'].search([('partner_id', '=', partner.id)], limit=1)
                    if student:
                        student.unlink()

            if 'is_teacher' in vals:
                category = self.env['res.partner.category'].search([('name', '=', 'Teacher')], limit=1)
                if not category:
                    category = self.env['res.partner.category'].create({'name': 'Teacher'})
                
                if vals['is_teacher']:
                    # Add Teacher category and create faculty record
                    if category.id not in partner.category_id.ids:
                        partner.category_id = [(4, category.id)]
                    # Check if faculty record exists for this partner
                    if not faculty and employee:
                        faculty = self.env['op.faculty'].create({
                            'first_name': employee.name,
                            'emp_id': employee.id,
                            'gender': partner.gender,
                            'partner_id': employee.user_id.partner_id.id if employee.user_id else (employee.address_home_id.id if employee.address_home_id else False),
                            'phone': employee.work_phone or employee.mobile_phone,
                            'mobile': employee.mobile_phone or (employee.user_id.partner_id.mobile if employee.user_id and employee.user_id.partner_id else False),
                            'email': employee.work_email,
                            'birth_date': employee.birthday if employee.birthday else "2000-01-01"

                        })
                        # Trigger onchange to populate fields if applicable
                        if hasattr(faculty, '_onchange_partner_id'):
                            faculty._onchange_partner_id()
                else:
                    # Remove Teacher category and delete faculty record
                    if category.id in partner.category_id.ids:
                        partner.category_id = [(3, category.id)]
                    # Delete associated faculty record
                    faculty = self.env['op.faculty'].search([('partner_id', '=', partner.id)], limit=1)
                    if faculty:
                        faculty.unlink()

        return res

    @api.model
    def bulk_update_profile_images(self, updates):
        """Bulk-update partner profile images.

        :param updates: list of dicts with 'id' (int) and 'image_1920' (base64 str)
        """
        partner_ids = [item['id'] for item in updates]
        partners = self.browse(partner_ids)
        image_map = {item['id']: item['image_1920'] for item in updates}
        for partner in partners:
            partner.write({'image_1920': image_map[partner.id]})

                