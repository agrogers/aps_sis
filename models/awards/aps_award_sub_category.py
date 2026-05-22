from odoo import fields, models


class APSAwardSubCategory(models.Model):
    _name = 'aps.award.sub.category'
    _description = 'Award Sub-Category'
    _order = 'sequence, name'

    category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(string='Name', required=True)
    description = fields.Char(string='Description')
    sequence = fields.Integer(string='Sequence', default=10)
