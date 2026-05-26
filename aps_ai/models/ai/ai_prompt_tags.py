from odoo import fields, models


class APSAIPromptTag(models.Model):
    _name = 'ai.prompt.tag'
    _description = 'AI Prompt Tag'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    color = fields.Integer(string='Color')
