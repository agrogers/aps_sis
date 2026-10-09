from odoo import api, fields, models


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

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or f'Media Collection {rec.id}'

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
