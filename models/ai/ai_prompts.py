from odoo import api, fields, models


class APSAIPrompt(models.Model):
    _name = 'ai_prompts'
    _description = 'AI Prompt'
    _order = 'sequence, id'

    # The order of these sections determines the order in which prompts are combined and sent to the AI. For example, if a prompt is assigned to the "Additional Context" section, its text will be inserted into the combined prompt after all prompts assigned to the "System" section and before any prompts assigned to the "AI Instructions" section.
    _PROMPT_MESSAGE_SECTIONS = [
        ('system', 'System'),                               # <system> prompts are for high-level instructions that set the overall context and guidelines for the AI's analysis, such as the role it should play, the perspective it should take, and the general approach it should use when analyzing the student's answer. They are included for reference and should be used as part of the basis for analysis, as they provide important context for understanding how to approach the analysis and for ensuring that important details are not overlooked.
        ('additional_context', 'Additional Context'),       # <additional_context> is for any relevant context that doesn't fit into the other categories, such as background information, reminders about edge cases, or specific conventions to follow when analyzing the student's answer. It is included for reference and should be used as part of the basis for analysis, as it provides important context for understanding how to approach the analysis and for ensuring that important details are not overlooked.
        ('ai_instructions', '- NOT USED AI Instructions'),             
        ('notes', '- NOT USED Notes'),                                 # <notes> can be used for any additional information that doesn't fit into the other categories, such as reminders about how to handle edge cases, or specific conventions to follow when analyzing the student's answer. It is included for reference and should be used as part of the basis for analysis, as it provides important context for understanding how to approach the analysis and for ensuring that important details are not overlooked.
        ('score', 'Score'),                   # <maximum_mark> is the maximum mark available for the question, which can be used as a reference point for evaluating the student's answer and for providing feedback on how to improve it. It is included for reference and should be used as part of the basis for analysis, as it provides important context for understanding the marking criteria and for evaluating the relevance and correctness of the student's answer.
        ('maximum_mark', 'Maximum Mark'),                   # <maximum_mark> is the maximum mark available for the question, which can be used as a reference point for evaluating the student's answer and for providing feedback on how to improve it. It is included for reference and should be used as part of the basis for analysis, as it provides important context for understanding the marking criteria and for evaluating the relevance and correctness of the student's answer.
        ('model_answer', 'Model Answer'),                   # <model_answer> is the ideal answer to the question, which the student's answer will be compared against. It is included for reference and should be used as part of the basis for analysis, as it provides important context for understanding what a correct and complete answer looks like, and for evaluating the relevance and correctness of the student's answer.
        ('question', 'Question'),                           # <question> is the question or prompt that the student was responding to in their answer. It is included for reference and should be used as part of the basis for analysis, as it provides important context for understanding the student's answer and for evaluating its relevance and correctness.
        ('student_answer', 'Student Answer'),               # <student_answer> is the student's full answer, unchunked. It is included for reference and should not be used as the main basis for analysis - the chunked version of the student answer should be used for that. This is because the chunked version is more structured and easier for the AI to analyze, and because using the unchunked version for analysis can lead to issues with token limits and with the AI missing important details that are more easily identified in the chunked version.
        ('summary', 'Summary'),                             # <summary> Describes how to determine the summary. 
        ('summary_format', 'Summary Format'),               # <output_constraints> describe how to format the summary - how the answer should be written - formatting, paragraph structure, style, tone, etc.
        ('detailed_analysis', 'Detailed Analysis'),         # <detailed_analysis> Describes how to determine the detailed analysis. 
        ('detailed_analysis_format', 'Detailed Analysis Format'), # <output_constraints> describe how to format the detailed analysis - formatting, paragraph structure, style, tone, etc.
        ('results_table', 'Results Table'),                 # <results_table> Describes how to determine the results table. 
        ('results_table_format', 'Results Table Format'),   # <output_constraints> describe how to format the results table - formatting, paragraph structure, style, tone, etc.
        ('targeted_feedback', 'Targeted Feedback'),         # <targeted_feedback> Describes how to determine the targeted feedback. Plus 
        ('output_schema', 'Output Schema'),                 # <output_schema> what must be produiced  - JSON keys, structure rules, data types, etc.
        ('response_format', '- NOT USED Response Format -'),     # Don't use any more ##
    ]

    _DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME = 'Targeted Feedback'
    _DEFAULT_TARGETED_FEEDBACK_PROMPT_SEQUENCE = 90

    _DEFAULT_SPECIFIC_INSTRUCTIONS_PROMPT_NAME = 'Specific Instructions'
    _DEFAULT_SPECIFIC_INSTRUCTIONS_PROMPT_SEQUENCE = 5
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

    # Map message_section values to Odoo colour palette indices (0–11).
    _SECTION_COLORS = {
        'system':             5,   # dark purple
        'additional_context': 4,   # light blue
        'ai_instructions':    1,   # red
        'notes':              3,   # yellow
        'maximum_mark':       2,   # orange
        'model_answer':       10,  # green
        'question':           7,   # medium blue
        'student_answer':     8,   # light purple
        'summary':            6,   # salmon
        'detailed_analysis':  9,   # fuchsia
        'results_table':      11,  # violet
        'targeted_feedback':  6,   # salmon
        'response_format':    0,   # none (deprecated)
        'output_schema':      3,   # yellow
    }

    sequence = fields.Integer(string='Sequence', default=10)
    prompt_name = fields.Char(string='Prompt Name', required=True)
    prompt = fields.Text(string='Prompt', required=False)
    message_section = fields.Selection(
        selection=_PROMPT_MESSAGE_SECTIONS,
        string='Message Section',
        default='additional_context',
        required=True,
        help=(
            'Choose which generic prompt section this template should be added to. '
            'Use Additional Context for background guidance that helps interpretation but is not core marking criteria, '
            'not output JSON/schema rules, and not student answer content. '
            'Examples: accepted wording variants, spelling conventions, domain reference hints, and edge-case handling notes.'
        ),
    )
    enabled = fields.Boolean(string='Enabled', default=True)
    color = fields.Integer(string='Color', compute='_compute_color')
    display_name = fields.Char(compute='_compute_display_name', store=True)
    always_include = fields.Boolean(string='Always Include', default=False, help='If enabled, this prompt will always be included in AI calls for resources that use prompts, regardless of whether it is selected on the resource or not.')
    tag_ids = fields.Many2many(
        'ai.prompt.tag',
        'ai_prompt_tag_rel',
        'prompt_id',
        'tag_id',
        string='Tags',
        help='Descriptive tags for this prompt. Use the "code" tag to signal that student answers should be chunked by line rather than by sentence.',
    )
    applies_to_ai_models = fields.Many2many('aps.ai.model', 'ai_model_prompt_rel', 'prompt_id', 'model_id', string='Applies to AI Models', help='Select the AI models this prompt applies to. If no models are selected, this prompt will be available for all models.')
    applies_to_db_models = fields.Many2many(
        'ir.model',
        'ai_prompt_ir_model_rel',
        'prompt_id',
        'ir_model_id',
        string='Applies to Database Models',
        help='Limit prompt usage to specific Odoo models (e.g. aps.resources, aps.resource.submission). Leave empty to allow all.',
    )

    @api.depends('message_section')
    def _compute_color(self):
        for record in self:
            record.color = self._SECTION_COLORS.get(record.message_section, 0)

    @api.depends('prompt_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.prompt_name or ''

    @api.model
    def _has_tag(self, prompts, tag_name):
        """Return True if any record in ``prompts`` has a tag whose name matches ``tag_name`` (case-insensitive)."""
        key = (tag_name or '').strip().casefold()
        return any(
            tag.name.strip().casefold() == key
            for prompt in (prompts or self.browse())
            for tag in prompt.tag_ids
        )

    @api.model
    def _get_default_targeted_feedback_prompt_values(self):
        resource_models = self.env['ir.model'].sudo().search([
            ('model', 'in', ['aps.resources', 'aps.resource.submission']),
        ])
        return {
            'prompt_name': self._DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME,
            'prompt': self._DEFAULT_TARGETED_FEEDBACK_PROMPT_TEXT,
            'sequence': self._DEFAULT_TARGETED_FEEDBACK_PROMPT_SEQUENCE,
            'message_section': 'response_format',
            'enabled': True,
            'always_include': True,
            'applies_to_db_models': [(6, 0, resource_models.ids)],
        }

    @api.model
    def _ensure_tag(self, tag_name):
        """Find or create an ai.prompt.tag with the given name."""
        tag = self.env['ai.prompt.tag'].sudo().search([('name', '=ilike', tag_name)], limit=1)
        if not tag:
            tag = self.env['ai.prompt.tag'].sudo().create({'name': tag_name})
        return tag

    @api.model
    def _get_default_specific_instructions_prompt_values(self):
        resource_models = self.env['ir.model'].sudo().search([
            ('model', 'in', ['aps.resources', 'aps.resource.submission']),
        ])
        return {
            'prompt_name': self._DEFAULT_SPECIFIC_INSTRUCTIONS_PROMPT_NAME,
            'prompt': '',
            'sequence': self._DEFAULT_SPECIFIC_INSTRUCTIONS_PROMPT_SEQUENCE,
            'message_section': 'ai_instructions',
            'enabled': True,
            'always_include': False,
            'applies_to_db_models': [(6, 0, resource_models.ids)],
        }

    @api.model
    def ensure_default_specific_instructions_prompt(self):
        tag = self._ensure_tag(self._DEFAULT_SPECIFIC_INSTRUCTIONS_PROMPT_NAME)
        prompt = self.sudo().search([
            ('prompt_name', '=', self._DEFAULT_SPECIFIC_INSTRUCTIONS_PROMPT_NAME),
        ], order='sequence, id', limit=1)
        if prompt:
            if tag not in prompt.tag_ids:
                prompt.tag_ids = [(4, tag.id)]
            return prompt
        vals = self._get_default_specific_instructions_prompt_values()
        vals['tag_ids'] = [(4, tag.id)]
        return self.sudo().create(vals)

    @api.model
    def ensure_default_targeted_feedback_prompt(self):
        tag = self._ensure_tag(self._DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME)
        prompt = self.sudo().search([
            ('prompt_name', '=', self._DEFAULT_TARGETED_FEEDBACK_PROMPT_NAME),
        ], order='sequence, id', limit=1)
        if prompt:
            if tag not in prompt.tag_ids:
                prompt.tag_ids = [(4, tag.id)]
            return prompt
        vals = self._get_default_targeted_feedback_prompt_values()
        vals['tag_ids'] = [(4, tag.id)]
        return self.sudo().create(vals)
