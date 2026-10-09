from odoo import api, fields, models


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

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or f'Media Category {rec.id}'
