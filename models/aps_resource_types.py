from odoo import models, fields


class APSResourceType(models.Model):
    _name = 'aps.resource.types'
    _description = 'APEX Resource Type'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    icon = fields.Image(
        string='Icon',
        max_width=64,
        max_height=64,
        help='Icon for the resource type (e.g., for visual identification in lists)'
    )
    color = fields.Char(string='Color', help='CSS color for the ribbon (e.g., #17a2b8, red, rgb(0,128,0))')
    resource_ids = fields.One2many('aps.resources', 'type_id', string='Resources')
