from odoo import api, fields, models


class ApsUserMediaSettings(models.Model):
    """Stores per-partner preferences for the media feature, such as whether
    custom wallpapers and card backs are enabled and which collections can be
    used for each purpose.
    """

    _name = 'aps.user.media.settings'
    _description = 'User Media Settings'
    _rec_name = 'partner_id'

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
    wallpaper_quad = fields.Boolean(
        string='Show 4 Icons as Wallpaper',
        help='When enabled, four randomly chosen media images are tiled in a 2×2 grid as the wallpaper instead of a single image.',
    )
    wallpaper_refresh_minutes = fields.Integer(
        string='Wallpaper Refresh (minutes)',
        default=0,
        help='Automatically change the wallpaper image every N minutes. Set to 0 to disable auto-refresh.',
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
        compute='_compute_points_available',
        inverse='_inverse_points_available',
        help=(
            'Points available is determined by the total points the partner has '
            'accumulated minus the points spent purchasing media items.'
        ),
    )

    @api.depends('partner_id')
    def _compute_points_available(self):
        users = self.env['res.users'].search([('partner_id', 'in', self.mapped('partner_id').ids)])
        balance_by_partner = {}
        for user in users:
            # Prefer the first matched user; in normal setups partner<->user is 1:1.
            balance_by_partner.setdefault(user.partner_id.id, user.points_balance or 0)

        for rec in self:
            rec.points_available = balance_by_partner.get(rec.partner_id.id, 0)

    def _inverse_points_available(self):
        for rec in self:
            if not rec.partner_id:
                continue
            user = self.env['res.users'].search([('partner_id', '=', rec.partner_id.id)], limit=1)
            if user:
                user.write({'points_balance': rec.points_available or 0})

    _sql_constraints = [
        (
            'partner_unique',
            'UNIQUE(partner_id)',
            'Media settings must be unique per partner.',
        ),
    ]

    @api.depends('partner_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            partner_name = rec.partner_id.display_name or 'Unknown Partner'
            rec.display_name = f'{partner_name} Media Settings'

    @api.model
    def get_wallpaper_data(self):
        """Return wallpaper configuration for the current user.

        Returns a dict with ``enabled`` (bool) and, when enabled, a list of
        ``media_ids`` whose images are eligible for use as the background
        wallpaper.
        """
        partner = self.env.user.partner_id
        settings = self.search([('partner_id', '=', partner.id)], limit=1)

        if not settings or not settings.enable_wallpaper:
            return {'enabled': False}

        # Owned media items for this partner
        user_media = self.env['aps.user.media'].search([
            ('partner_id', '=', partner.id),
            ('status', 'in', ['purchased', 'for_sale']),
        ])
        media = user_media.mapped('media_id')

        # Restrict to wallpaper collections when specified (and icons
        # are not allowed as wallpapers).
        if settings.wallpaper_collection_ids and not settings.use_icons_as_wallpaper:
            media = media.filtered(
                lambda media_item: media_item.collection_id in settings.wallpaper_collection_ids
            )

        if not media:
            return {'enabled': False}

        return {
            'enabled': True,
            'media_ids': media.ids,
            'mode': 'quad' if settings.wallpaper_quad else 'single',
            'refresh_minutes': settings.wallpaper_refresh_minutes or 0,
        }
