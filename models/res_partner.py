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

    submission_ids = fields.One2many('aps.resource.submission', 'student_id', string='Submissions')

    def write(self, vals):
        res = super().write(vals)

        for partner in self:
            if 'is_student' in vals:
                category = self.env['res.partner.category'].search([('name', '=', 'Student')], limit=1)
                if not category:
                    category = self.env['res.partner.category'].create({'name': 'Student'})
                if vals['is_student']:
                    if category.id not in partner.category_id.ids:
                        partner.category_id = [(4, category.id)]
                else:
                    if category.id in partner.category_id.ids:
                        partner.category_id = [(3, category.id)]

            if 'is_teacher' in vals:
                category = self.env['res.partner.category'].search([('name', '=', 'Teacher')], limit=1)
                if not category:
                    category = self.env['res.partner.category'].create({'name': 'Teacher'})
                if vals['is_teacher']:
                    if category.id not in partner.category_id.ids:
                        partner.category_id = [(4, category.id)]
                else:
                    if category.id in partner.category_id.ids:
                        partner.category_id = [(3, category.id)]

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

                