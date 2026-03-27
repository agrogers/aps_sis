from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    avatar_id = fields.Many2one(
        'aps.avatar',
        string='Profile Avatar',
    )
    avatar_image = fields.Image(
        related='avatar_id.image',
        string='Avatar Image',
        readonly=True,
    )

    points_balance = fields.Integer(
        string='Points Balance',
        default=0,
        help='Current spendable points balance for this user. Used to purchase media items in the APEX Media shop.',
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['avatar_id', 'avatar_image', 'points_balance']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['avatar_id']
