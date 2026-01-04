from odoo import models, fields


class APSResourceType(models.Model):
    _name = 'aps.resource.types'
    _description = 'APS Resource Type'
    _order = 'sequence, name'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    icon = fields.Binary(string='Icon', attachment=True)
    color = fields.Char(string='Color', help='CSS color for the ribbon (e.g., #17a2b8, red, rgb(0,128,0))')
    resource_ids = fields.One2many('aps.resources', 'type_id', string='Resources')
