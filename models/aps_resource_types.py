from odoo import models, fields


class APSResourceType(models.Model):
    _name = 'aps.resource.types'
    _description = 'APEX Resource Type'
    _order = 'sequence, name'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    icon = fields.Image(
        string='Icon',
        max_width=64,
        max_height=64,
        help='Icon for the resource type (e.g., for visual identification in lists)'
    )
    color = fields.Char(string='Color', help='CSS color for the ribbon (e.g., #17a2b8, red, rgb(0,128,0))')
    resource_ids = fields.One2many('aps.resources', 'type_id', string='Resources')
    url_keywords = fields.Char(string='URL Keywords', help='A comma separated list of words that will allow automatic linking of this type to a URL so it can be pre-selected when creating resources.')

    assessment = fields.Boolean(
        string='Assessment',
        default=True,
        help='Indicates if this resource type is an assessment (e.g., quiz, test, exam).'
    )
    