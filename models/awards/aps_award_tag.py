from odoo import fields, models


class APSAwardTag(models.Model):
    _name = 'aps.award.tag'
    _description = 'Award Tag'
    _order = 'name'

    name = fields.Char(string='Name', required=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tag name must be unique!'),
    ]
