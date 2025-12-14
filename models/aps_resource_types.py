from odoo import models, fields


class APSResourceType(models.Model):
    _name = 'aps.resource.types'
    _description = 'APS Resource Type'

    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    resource_ids = fields.One2many('aps.resources', 'type_id', string='Resources')
