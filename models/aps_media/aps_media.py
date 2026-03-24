import os

from odoo import api, fields, models
from odoo.exceptions import UserError


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
        store=True,
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

    def action_view_media(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} — Media Items',
            'res_model': 'aps.media',
            'view_mode': 'kanban,list,form',
            'domain': [('type_id', '=', self.id)],
        }


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
        store=True,
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

    def action_view_media(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} — Media Items',
            'res_model': 'aps.media',
            'view_mode': 'kanban,list,form',
            'domain': [('collection_id', '=', self.id)],
        }


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

    @api.model
    def bulk_create_from_files(self, files, collection_id, category_ids, cost, stock_available):
        """Create media item records from a list of image files.

        Called from the OWL MediaBulkUpload client action.

        :param files: list of dicts ``{'name': str, 'data': str}`` where
            *name* is the original filename and *data* is the base64-encoded
            image content (no data-URI prefix).
        :param collection_id: int or False — the collection to assign to each item.
            If ``-1`` a new collection is expected to have already been handled
            by the caller; pass ``False`` for no collection.
        :param category_ids: list of int — existing ``aps.media.category`` ids.
        :param cost: int — point cost to assign to each created item.
        :param stock_available: int — initial stock for each created item.
        :return: dict ``{'ids': [int, …], 'count': int}``
        """
        vals_list = []
        for idx, f in enumerate(files):
            fname = f.get('name', '')
            name = os.path.splitext(fname)[0] if fname else f'Media Item {idx + 1}'
            vals = {
                'name': name,
                'image': f.get('data', ''),
                'collection_id': collection_id or False,
                'cost': cost or 0,
                'stock_available': stock_available or 0,
            }
            if category_ids:
                vals['category_ids'] = [(6, 0, category_ids)]
            vals_list.append(vals)

        created = self.create(vals_list)
        return {'ids': created.ids, 'count': len(created)}

    @api.model
    def action_open_bulk_upload(self):
        """Return the client action for the Media Bulk Upload screen."""
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_media_bulk_upload',
            'name': 'Bulk Upload Media',
        }

    def action_buy(self):
        """Purchase this media item for the current user.

        Checks that:
        - The item is currently in stock.
        - The current user's partner has sufficient points balance.

        On success:
        - Creates or updates the ``aps.user.media`` record (status = purchased).
        - Decrements ``stock_available`` and the user's ``points_balance``.
        - Increments ``qty_sold`` and records the sale date.

        Returns a client-side notification action.
        """
        self.ensure_one()
        user = self.env.user
        partner = user.partner_id

        # Guard: stock check (with row-level lock to prevent overselling)
        item = self.with_for_update().browse(self.id)
        if item.stock_available <= 0:
            raise UserError(
                f'"{self.name}" is currently out of stock.'
            )

        # Guard: already owned
        existing = self.env['aps.user.media'].search([
            ('partner_id', '=', partner.id),
            ('media_id', '=', self.id),
            ('status', 'in', ['purchased', 'for_sale']),
        ], limit=1)
        if existing:
            raise UserError(
                f'You already own "{self.name}".'
            )

        # Guard: sufficient points
        if user.points_balance < self.cost:
            raise UserError(
                f'Insufficient points. "{self.name}" costs {self.cost} points '
                f'but you only have {user.points_balance}.'
            )

        today = fields.Date.today()

        # Create ownership record
        self.env['aps.user.media'].create({
            'partner_id': partner.id,
            'media_id': self.id,
            'cost': self.cost,
            'status': 'purchased',
            'date_purchased': today,
        })

        # Update item stock / sales counters
        self.write({
            'stock_available': self.stock_available - 1,
            'qty_sold': (self.qty_sold or 0) + 1,
            'date_sold': today,
        })

        # Deduct points from user via write() for proper ORM processing
        user.write({'points_balance': user.points_balance - self.cost})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Purchase Successful',
                'message': f'You purchased "{self.name}" for {self.cost} points.',
                'type': 'success',
                'sticky': False,
            },
        }


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
