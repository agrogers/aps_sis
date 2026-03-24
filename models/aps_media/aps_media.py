from odoo import api, fields, models


class ApsMediaType(models.Model):
    """Defines the type of media item (e.g. Avatar, Card, Wallpaper).
    Default stock management values are stored here and inherited by new media
    items of this type.
    """

    _name = 'aps.media.type'
    _description = 'Media Type'
    _order = 'name'

    name = fields.Char(
        string='Type Name',
        required=True,
        help='Name of the media type, e.g. Avatar, Card, Wallpaper.',
    )
    icon = fields.Image(
        string='Type Icon',
        max_width=256,
        max_height=256,
        help='An image that visually represents this media type.',
    )
    cost = fields.Integer(
        string='Default Cost',
        help='Default point cost applied to new media items of this type.',
    )
    stock_resupply_qty = fields.Integer(
        string='Default Resupply Quantity',
        help='Default number of items to add when stock falls to the minimum threshold.',
    )
    stock_resupply_delay = fields.Integer(
        string='Default Resupply Delay (days)',
        help='Default number of days between resupply events for this type.',
    )
    stock_max = fields.Integer(
        string='Default Max Stock',
        help='Default maximum number of items to hold in stock for this type.',
    )
    stock_min = fields.Integer(
        string='Default Min Stock',
        help='Default minimum stock level that triggers a resupply for this type.',
    )

    media_ids = fields.One2many(
        'aps.media',
        'type_id',
        string='Media Items',
        readonly=True,
    )
    media_count = fields.Integer(
        string='Media Items',
        compute='_compute_media_count',
    )

    @api.depends('media_ids')
    def _compute_media_count(self):
        counts = self.env['aps.media'].read_group(
            [('type_id', 'in', self.ids)],
            ['type_id'],
            ['type_id'],
        )
        count_map = {r['type_id'][0]: r['type_id_count'] for r in counts}
        for rec in self:
            rec.media_count = count_map.get(rec.id, 0)


class ApsMediaCollection(models.Model):
    """A named collection that groups related media items together.
    For example, a seasonal theme or artist series.
    """

    _name = 'aps.media.collection'
    _description = 'Media Collection'
    _order = 'name'

    name = fields.Char(
        string='Collection Name',
        required=True,
        help='Name of the collection that groups related media items.',
    )
    media_ids = fields.One2many(
        'aps.media',
        'collection_id',
        string='Media Items',
        readonly=True,
    )
    media_count = fields.Integer(
        string='Media Items',
        compute='_compute_media_count',
    )

    @api.depends('media_ids')
    def _compute_media_count(self):
        counts = self.env['aps.media'].read_group(
            [('collection_id', 'in', self.ids)],
            ['collection_id'],
            ['collection_id'],
        )
        count_map = {r['collection_id'][0]: r['collection_id_count'] for r in counts}
        for rec in self:
            rec.media_count = count_map.get(rec.id, 0)


class ApsMediaCategory(models.Model):
    """Tag-style category that can be applied to media items.
    A single media item may belong to multiple categories.
    """

    _name = 'aps.media.category'
    _description = 'Media Category'
    _order = 'name'

    name = fields.Char(
        string='Category Name',
        required=True,
        help='Category label used to tag and filter media items.',
    )


class ApsMedia(models.Model):
    """Represents a purchasable media item such as an avatar, card back or
    wallpaper.  Stock quantities, pricing and availability are tracked here.
    """

    _name = 'aps.media'
    _description = 'Media Item'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        help='Display name of the media item.',
    )
    image = fields.Image(
        string='Image',
        max_width=1024,
        max_height=1024,
        help='Image stored in the Odoo filestore. Displayed to users when browsing or using the item.',
    )
    type_id = fields.Many2one(
        'aps.media.type',
        string='Type',
        ondelete='restrict',
        help='The type of this media item (e.g. Avatar, Card, Wallpaper).',
    )
    collection_id = fields.Many2one(
        'aps.media.collection',
        string='Collection',
        ondelete='restrict',
        help='The collection this item belongs to, such as a seasonal theme or artist series.',
    )
    category_ids = fields.Many2many(
        'aps.media.category',
        string='Categories',
        help='Tag-style categories the item belongs to, used for filtering and discovery.',
    )

    # ── Pricing ──────────────────────────────────────────────────────────────
    cost = fields.Integer(
        string='Cost (points)',
        help='Point cost to purchase this item.',
    )

    # ── Stock management ─────────────────────────────────────────────────────
    stock_available = fields.Integer(
        string='Stock Available',
        help='Current number of copies available for purchase.',
    )
    stock_resupply_qty = fields.Integer(
        string='Resupply Quantity',
        default=1,
        help='Number of items to add when stock falls to the minimum threshold.',
    )
    stock_resupply_delay = fields.Integer(
        string='Resupply Delay (days)',
        default=7,
        help='Number of days after the last sale before this item is resupplied.',
    )
    stock_max = fields.Integer(
        string='Max Stock',
        default=1,
        help='Maximum number of copies to hold in stock at any time.',
    )
    stock_min = fields.Integer(
        string='Min Stock',
        default=0,
        help='Minimum stock level. When reached (and the resupply delay is satisfied) the item is restocked.',
    )

    # ── History / audit ───────────────────────────────────────────────────────
    history = fields.Text(
        string='History',
        help='Chronological log of cost changes and resupply activity for this item.',
    )

    # ── Availability dates ────────────────────────────────────────────────────
    date_available = fields.Date(
        string='Available From',
        default=fields.Date.today,
        help='Date from which this item is available for purchase. Defaults to today.',
    )
    date_unavailable = fields.Date(
        string='Available Until',
        help='Date after which this item is no longer available for purchase. Leave blank for no end date.',
    )

    # ── Sales tracking ────────────────────────────────────────────────────────
    qty_sold = fields.Integer(
        string='Quantity Sold',
        help='Total number of copies sold to date.',
    )
    date_sold = fields.Date(
        string='Last Sold',
        help='Date on which the most recent copy was sold.',
    )

    # ── Reverse relation ──────────────────────────────────────────────────────
    user_media_ids = fields.One2many(
        'aps.user.media',
        'media_id',
        string='Owner Records',
        readonly=True,
    )


class ApsUserMedia(models.Model):
    """Records the relationship between a partner (user) and a media item they
    own, wish to own or have sold.  Tracks the price paid, current status and
    intended use.
    """

    _name = 'aps.user.media'
    _description = 'User Media'
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


class ApsUserMediaSettings(models.Model):
    """Stores per-partner preferences for the media feature, such as whether
    custom wallpapers and card backs are enabled and which collections can be
    used for each purpose.
    """

    _name = 'aps.user.media.settings'
    _description = 'User Media Settings'

    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        ondelete='cascade',
        help='The partner these media settings belong to.',
    )

    # ── Wallpaper settings ────────────────────────────────────────────────────
    enable_wallpaper = fields.Boolean(
        string='Enable Custom Wallpaper',
        help='Allow this partner to use media items as custom interface wallpapers.',
    )
    use_icons_as_wallpaper = fields.Boolean(
        string='Use Icons as Wallpaper',
        help='When enabled, icon-type media items may also be used as wallpapers.',
    )
    wallpaper_collection_ids = fields.Many2many(
        'aps.media.collection',
        'aps_user_media_settings_wallpaper_collection_rel',
        'settings_id',
        'collection_id',
        string='Wallpaper Collections',
        help='Collections whose items are eligible to be used as wallpapers for this partner.',
    )

    # ── Card settings ─────────────────────────────────────────────────────────
    enable_cards = fields.Boolean(
        string='Enable Custom Card Backs',
        help='Allow this partner to use media items as custom card backs.',
    )
    use_icons_as_cards = fields.Boolean(
        string='Use Icons as Card Backs',
        help='When enabled, icon-type media items may also be used as card backs.',
    )
    card_collection_ids = fields.Many2many(
        'aps.media.collection',
        'aps_user_media_settings_card_collection_rel',
        'settings_id',
        'collection_id',
        string='Card Back Collections',
        help='Collections whose items are eligible to be used as card backs for this partner.',
    )

    # ── Points ────────────────────────────────────────────────────────────────
    points_available = fields.Integer(
        string='Points Available',
        help=(
            'Points available is determined by the total points the partner has '
            'accumulated minus the points spent purchasing media items.'
        ),
    )

    _sql_constraints = [
        (
            'partner_unique',
            'UNIQUE(partner_id)',
            'Media settings must be unique per partner.',
        ),
    ]
