from odoo import fields, models


class ApsPromptPreviewWizard(models.TransientModel):
    _name = 'aps.prompt.preview.wizard'
    _description = 'AI Prompt Preview'

    prompt_text = fields.Text(string='Compiled Prompt', readonly=True)
