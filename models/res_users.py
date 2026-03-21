from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    avatar_id = fields.Many2one(
        'aps.avatar',
        string='Avatar',
    )
    avatar_image = fields.Image(
        related='avatar_id.image',
        string='Avatar Image',
        readonly=True,
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['avatar_id', 'avatar_image']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['avatar_id']
