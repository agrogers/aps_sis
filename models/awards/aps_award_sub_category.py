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
    vote_points = fields.Float(
        string='Vote Points', default=0.0,
        help='Points awarded to the recipient when a vote is submitted in this sub-category.',
    )
    certificate_points = fields.Float(
        string='Certificate Points', default=0.0,
        help='Points awarded when a certificate is issued for this sub-category.',
    )
    description = fields.Char(string='Description')
    sequence = fields.Integer(string='Sequence', default=10)
