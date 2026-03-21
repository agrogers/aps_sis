import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ApsAvatarBulkUploadLine(models.TransientModel):
    _name = 'aps.avatar.bulk.upload.line'
    _description = 'Avatar Bulk Upload Line'

    wizard_id = fields.Many2one('aps.avatar.bulk.upload', string='Wizard', required=True, ondelete='cascade')
    name = fields.Char(string='Name', required=True)
    image = fields.Image(string='Avatar Image', required=True, max_width=512, max_height=512)
    category_id = fields.Many2one('aps.avatar.category', string='Category')


class ApsAvatarBulkUpload(models.TransientModel):
    _name = 'aps.avatar.bulk.upload'
    _description = 'Avatar Bulk Upload'

    category_id = fields.Many2one(
        'aps.avatar.category',
        string='Default Category',
        help='This category will be applied to all uploaded avatars unless overridden per line.',
    )
    line_ids = fields.One2many('aps.avatar.bulk.upload.line', 'wizard_id', string='Avatars to Upload')

    def action_upload(self):
        self.ensure_one()
        created_avatars = self.env['aps.avatar']
        for line in self.line_ids:
            category = line.category_id or self.category_id
            created_avatars |= self.env['aps.avatar'].create({
                'name': line.name,
                'image': line.image,
                'category_id': category.id if category else False,
            })
        if len(created_avatars) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'aps.avatar',
                'res_id': created_avatars.id,
                'view_mode': 'form',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Uploaded Avatars',
            'res_model': 'aps.avatar',
            'domain': [('id', 'in', created_avatars.ids)],
            'view_mode': 'list,form',
        }
