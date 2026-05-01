from odoo import api, fields, models


class APSAIPrompt(models.Model):
    _name = 'ai_prompts'
    _description = 'AI Prompt'
    _order = 'sequence, id'

    _DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME = 'Targeted Feedback'
    _DEFAULT_TARGETED_FEEDBACK_PROMPT_SEQUENCE = 90
    _DEFAULT_TARGETED_FEEDBACK_PROMPT_TEXT = """
# LLM RESPONSE STRUCTURE
## JSON Format
Return ONLY valid JSON with these keys:
{"html": string,
 "feedback": [{"id": string, "text": string, "type": string|null, "justification": string}],
 "links": [{"feedback_id": string, "chunk_ids": string[]}],
 "score": number|null,
 "score_comment": string|null}.

## Data Structuring
- Ensure the following are included in the feedback items: "Point, Evidence, Explain, Link, Level 1, Level 2, Level 3, Level 4, Level 5"
- The html field must be an HTML fragment using tags such as <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.
- Each feedback.text value must be short and suitable for a small clickable chip, ideally 2 to 8 words.
- Choose a value for feedback.type from this closed set: ["success", "error", "info"] If the value is not in this list, the response is invalid.
- Each feedback.justification must be a concise 1–2 sentence explanation of why this feedback item was included.
- Use ONLY chunk IDs from the supplied Student Answer Chunks.
- Do NOT invent chunk IDs.
- Not every feedback item needs linked chunks.
- If you cannot determine a mark, set score to null and explain why in score_comment.
- After analyzing the student answer as a whole, analyse each chunk and assign it a "Level" according to the marking rubric. Link each chunk to a JSON feedback item, creating a new item only if it doesn't already exist. Format the item this way: "Level 1"

## General Guidance
For spelling, grammar, or word-choice issues, feedback.text must include the incorrect word in the format "Spelling: Mistake". Do not include words like "incorrect" or "error" or "misspelled".
Always try and include one positive feature of the answer with a feedback.type="success".
""".strip()

    sequence = fields.Integer(string='Sequence', default=10)
    prompt_name = fields.Char(string='Prompt Name', required=True)
    prompt = fields.Text(string='Prompt', required=True)
    enabled = fields.Boolean(string='Enabled', default=True)
    placeholder = fields.Boolean(string='Placeholder', default=False, help='These prompts provide a way to order the text that comes from the corresponding fields in the Resources and Submissions models.')
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

    @api.model
    def _get_default_targeted_feedback_prompt_values(self):
        resource_models = self.env['ir.model'].sudo().search([
            ('model', 'in', ['aps.resources', 'aps.resource.submission']),
        ])
        return {
            'prompt_name': self._DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME,
            'prompt': self._DEFAULT_TARGETED_FEEDBACK_PROMPT_TEXT,
            'sequence': self._DEFAULT_TARGETED_FEEDBACK_PROMPT_SEQUENCE,
            'enabled': True,
            'placeholder': True,
            'always_include': True,
            'applies_to_db_models': [(6, 0, resource_models.ids)],
        }

    @api.model
    def ensure_default_targeted_feedback_prompt(self):
        prompt = self.sudo().search([
            ('prompt_name', '=', self._DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME),
        ], order='sequence, id', limit=1)
        if prompt:
            return prompt
        return self.sudo().create(self._get_default_targeted_feedback_prompt_values())
