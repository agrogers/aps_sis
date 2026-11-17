from odoo import fields, models


class APSSubjectTag(models.Model):
    _name = 'aps.subject.tag'
    _description = 'Subject Tag'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index', default=0)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tag name must be unique!'),
    ]
