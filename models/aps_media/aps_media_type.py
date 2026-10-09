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
        store=True,
    )

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or f'Media Type {rec.id}'

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
