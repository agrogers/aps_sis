from odoo import api, fields, models


class APSEvent(models.Model):
    _name = 'aps.event'
    _description = 'Event'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    icon = fields.Image(string='Icon', max_width=128, max_height=128)
    color = fields.Integer(string='Color')
    active = fields.Boolean(string='Active', default=True)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.name or ''