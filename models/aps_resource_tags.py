from odoo import models, fields

class ResourceTags(models.Model):
    _name = 'aps.resource.tags'
    _description = 'APEX Resource Tags'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index')