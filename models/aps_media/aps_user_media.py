from odoo import api, fields, models


class ApsUserMedia(models.Model):
    """Records the relationship between a partner (user) and a media item they
    own, wish to own or have sold. Tracks the price paid, current status and
    intended use.
    """

    _name = 'aps.user.media'
    _description = 'User Media'
    _rec_name = 'display_name'
    _order = 'partner_id, media_id'

    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        ondelete='cascade',
        help='The partner (user) who owns or is interested in this media item.',
    )
    media_id = fields.Many2one(
        'aps.media',
        string='Media Item',
        required=True,
        ondelete='restrict',
        help='The media item associated with this record.',
    )
    cost = fields.Integer(
        string='Cost Paid (points)',
        help=(
            'Point cost recorded at purchase time. When the item is later sold '
            'the difference between the sale price and this cost value reflects '
            'the profit or loss (positive difference = profit, negative = loss).'
        ),
    )
    status = fields.Selection(
        selection=[
            ('wishlist', 'Wish List'),
            ('purchased', 'Purchased'),
            ('for_sale', 'For Sale'),
            ('sold', 'Sold'),
            ('unavailable', 'Unavailable'),
        ],
        string='Status',
        help='Current ownership status of this item for the partner.',
    )
    use_as = fields.Selection(
        selection=[
            ('avatar', 'Avatar'),
            ('wallpaper', 'Wallpaper'),
            ('card_back', 'Card Back'),
        ],
        string='Use As',
        help=(
            'Some media can serve multiple purposes. '
            'Select how this partner wants to use the item.'
        ),
    )
    sell_price = fields.Integer(
        string='Asking Price (points)',
        help='Number of points the partner is asking for when selling this item.',
    )
    date_purchased = fields.Date(
        string='Date Purchased',
        help='Date on which the partner purchased this item.',
    )

    @api.depends('partner_id.display_name', 'media_id.display_name', 'status')
    def _compute_display_name(self):
        status_labels = dict(self._fields['status'].selection)
        for rec in self:
            partner_name = rec.partner_id.display_name or 'Unknown Partner'
            media_name = rec.media_id.display_name or 'Unknown Media'
            status_name = status_labels.get(rec.status)
            if status_name:
                rec.display_name = f'{partner_name} - {media_name} ({status_name})'
            else:
                rec.display_name = f'{partner_name} - {media_name}'
