from odoo import fields, models


class APSEthnicity(models.Model):
    _name = 'aps.ethnicity'
    _description = 'Ethnicity'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_ethnicity_name', 'unique(name)', 'Ethnicity name must be unique.'),
    ]
