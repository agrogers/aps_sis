from odoo import api, fields, models


class APSLevel(models.Model):
    _name = 'aps.level'
    _description = 'Academic Level'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    short_name = fields.Char(string='Short Name', size=20)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')
    tag_ids = fields.Many2many(
        'res.partner.category',
        relation='aps_level_partner_category_rel',
        column1='level_id',
        column2='category_id',
        string='Tags',
    )

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'short_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.short_name or record.name or ''

    _sql_constraints = [
        ('unique_level_name', 'unique(name)', 'Academic Level name must be unique.'),
    ]
