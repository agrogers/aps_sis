from odoo import api, fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    show_all_courses = fields.Boolean('Show All Courses', default=False)
    course_detail_ids_filtered = fields.One2many('op.student.course', compute='_compute_course_detail_ids_filtered', string='Course Details')

    @api.depends('course_detail_ids', 'course_detail_ids.state', 'show_all_courses')
    def _compute_course_detail_ids_filtered(self):
        for student in self:
            if student.show_all_courses:
                student.course_detail_ids_filtered = student.course_detail_ids
            else:
                student.course_detail_ids_filtered = student.course_detail_ids.filtered(lambda c: c.state == 'running')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and self.partner_id.display_name != "False False":
            partner = self.partner_id
            # Populate from partner only if fields are empty
            if not self.first_name and partner.name:
                self.first_name = partner.name
            if not self.email:
                self.email = partner.email
            if not self.phone:
                self.phone = partner.phone
            if not self.mobile:
                self.mobile = partner.mobile
            # Add other fields as needed
            if not self.birth_date:
                self.birth_date = partner.birthdate if hasattr(partner, 'birthdate') else False
            gender_map = {'male': 'm', 'female': 'f', 'other': 'o'}
            self.gender = gender_map.get(partner.gender, False) if hasattr(partner, 'gender') and partner.gender else False