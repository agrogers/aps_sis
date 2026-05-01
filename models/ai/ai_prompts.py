from odoo import api, fields, models


class APSAIPrompt(models.Model):
    _name = 'ai_prompts'
    _description = 'AI Prompt'
    _order = 'prompt_name, id'

    prompt_name = fields.Char(string='Prompt Name', required=True)
    prompt = fields.Text(string='Prompt', required=True)
    enabled = fields.Boolean(string='Enabled', default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)
    always_include = fields.Boolean(string='Always Include', default=False, help='If enabled, this prompt will always be included in AI calls for resources that use prompts, regardless of whether it is selected on the resource or not.')
    applies_to_ai_models = fields.Many2many('aps.ai.model', 'ai_model_prompt_rel', 'prompt_id', 'model_id', string='Applies to AI Models', help='Select the AI models this prompt applies to. If no models are selected, this prompt will be available for all models.')
    applies_to_db_models = fields.Many2many(
        'ir.model',
        'ai_prompt_ir_model_rel',
        'prompt_id',
        'ir_model_id',
        string='Applies to Database Models',
        help='Limit prompt usage to specific Odoo models (e.g. aps.resources, aps.resource.submission). Leave empty to allow all.',
    )

    @api.depends('prompt_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.prompt_name or ''
