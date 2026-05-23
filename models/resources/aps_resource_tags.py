from odoo import models, fields

class ResourceTags(models.Model):
    _name = 'aps.resource.tags'
    _description = 'APEX Resource Tags'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index')
    color_hex = fields.Char(string='Hex Color', help='Hex colour used in hierarchy view (e.g. #FF5733)')
    use_in_hierarchy = fields.Boolean(string='Use in Hierarchy', default=False)
    color_applies_to_fill = fields.Boolean(string='Color Applies to Fill', default=True)
    color_applies_to_border = fields.Boolean(string='Color Applies to Border', default=True)