from odoo import fields, models


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
        if 'is_student' in vals:
            category = self.env['res.partner.category'].search([('name', '=', 'Student')], limit=1)
            if not category:
                category = self.env['res.partner.category'].create({'name': 'Student'})
            
            if vals['is_student']:
                # Add Student category and create student record
                for partner in self:
                    if category.id not in partner.category_id.ids:
                        partner.category_id = [(4, category.id)]
                    # Check if student record exists for this partner
                    student = self.env['op.student'].search([('partner_id', '=', partner.id)], limit=1)
                    if not student:
                        student = self.env['op.student'].create({
                            'partner_id': partner.id,
                        })
                        # Trigger onchange to populate fields
                        student._onchange_partner_id()
            else:
                # Remove Student category and delete student record
                for partner in self:
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
                for partner in self:
                    if category.id not in partner.category_id.ids:
                        partner.category_id = [(4, category.id)]
            else:
                for partner in self:
                    if category.id in partner.category_id.ids:
                        partner.category_id = [(3, category.id)]
        return res