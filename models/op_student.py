from odoo import api, fields, models


class OpStudent(models.Model):
    _inherit = 'op.student'

    show_all_courses = fields.Boolean('Show All Courses', default=False)
    avatar_id = fields.Many2one(
        'aps.avatar',
        string='Avatar',
        help='Select an avatar image to display on this student\'s profile.',
    )
    course_detail_ids_filtered = fields.One2many('op.student.course', compute='_compute_course_detail_ids_filtered', string='Course Details')

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

class OpStudentCourse(models.Model):
    _inherit = "op.student.course"

    def copy(self, default=None):
        if default is None:
            default = {}
        default['student_id'] = False  # Reset student_id to allow duplication
        default['roll_number'] = False  # Reset roll_number to allow duplication
        return super(OpStudentCourse, self).copy(default)