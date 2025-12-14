from odoo import models, fields


class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'APS Resource'

    url = fields.Char(string='URL', required=True)
    description = fields.Text(string='Description')
    type_id = fields.Many2one('aps.resource.types', string='Type', ondelete='set null')
