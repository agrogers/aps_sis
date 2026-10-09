import os

from odoo import api, fields, models
from odoo.exceptions import UserError


class ApsMedia(models.Model):
    """Represents a purchasable media item such as an avatar, card back or
    wallpaper. Stock quantities, pricing and availability are tracked here.
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
    def bulk_create_from_files(self, files, collection_id, category_ids, cost, stock_available, type_id=False):
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
        :param type_id: int or False — the ``aps.media.type`` to assign.
        :return: dict ``{'ids': [int, …], 'count': int}``
        """
        vals_list = []
        for idx, file_data in enumerate(files):
            fname = file_data.get('name', '')
            name = os.path.splitext(fname)[0] if fname else f'Media Item {idx + 1}'
            vals = {
                'name': name,
                'image': file_data.get('data', ''),
                'type_id': type_id or False,
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

    @api.depends('name', 'type_id.name')
    def _compute_display_name(self):
        for rec in self:
            if rec.type_id and rec.name:
                rec.display_name = f'{rec.name} ({rec.type_id.name})'
            else:
                rec.display_name = rec.name or f'Media Item {rec.id}'

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
        self.env.cr.execute(
            f'SELECT id FROM {self._table} WHERE id = %s FOR UPDATE',
            [self.id],
        )
        item = self.browse(self.id)
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
