from odoo import fields, models


class APSClassTag(models.Model):
    _name = 'aps.class.tag'
    _description = 'Class Tag'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index')