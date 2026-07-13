import uuid
from odoo import api, fields, models

HAS_QUESTION_SELECTION = [
    ('no', 'No'),
    ('yes', 'Yes'),
    ('hidden', 'Yes (Hidden from Students)'),
    ('use_parent', 'Use Parent'),
]

HAS_ANSWER_SELECTION = [
    ('no', 'No'),
    ('yes', 'Yes'),
    ('hidden', 'Yes (Hidden from Students)'),
    ('use_parent', 'Use Parent'),
]

# Maps toggle field name → prompt message_section for section-based
# prompt shortcut toggles on the AI Instructions tab.
_AI_SECTION_TOGGLES = [
    ('ai_summary', 'summary'),
    ('ai_analysis', 'detailed_analysis'),
    ('ai_table_of_results', 'results_table'),
]

# Prompts tagged with this tag are treated as supplemental — they are
# included alongside (not instead of) any default prompts injected by
# toggles.  They are excluded from all deduplication checks so they
# never suppress a toggle-driven default for the same section.
_ADDITIONAL_TAG = 'additional'


def _is_supplemental(prompt):
    """Return True if *prompt* is tagged as supplemental (Additional)."""
    return any(t.name.strip().casefold() == _ADDITIONAL_TAG for t in prompt.tag_ids)


def _section_covered(prompts, section):
    """True only when a non-supplemental prompt already covers *section*."""
    return any(p.message_section == section for p in prompts if not _is_supplemental(p))


def _tag_covered(prompts, tag_name):
    """True only when a non-supplemental prompt already carries *tag_name*."""
    key = tag_name.strip().casefold()
    return any(
        any(t.name.strip().casefold() == key for t in p.tag_ids)
        for p in prompts
        if not _is_supplemental(p)
    )


class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'APEX Resources'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    sequence = fields.Integer(string='Sequence', default=10)
    favourite_user_ids = fields.Many2many(
        'res.users',
        'aps_resource_favourite_user_rel',
        'resource_id',
        'user_id',
        string='Favourite Users',
    )
    is_favourite = fields.Boolean(
        string='Favourite',
        compute='_compute_is_favourite',
        inverse='_inverse_is_favourite',
        search='_search_is_favourite',
        store=False,
    )
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True, recursive=True)
    name = fields.Char(string='Name', tracking=True)
    custom_name_ids = fields.One2many('aps.resource.custom.name', 'resource_id', string='Custom Names')
    # Computed JSON data of custom names for various parents for this resource
    parent_custom_name_data = fields.Json(string='Custom Names Data', compute='_compute_parent_custom_name_data', store=True)
    description = fields.Text(string='Description', tracking=True)

    has_question = fields.Selection(HAS_QUESTION_SELECTION, string='Has Question',
        default='no',
        help='A resource can use the parent\'s question if set to "Use Parent".',
        required=True,
        tracking=True)
    question = fields.Html(string='Question')

    has_answer = fields.Selection(HAS_ANSWER_SELECTION, string='Has Answer',
        default='no',
        help='Resources can include model answers to a question. A resource can use the parent\'s answer if set to "Use Parent".',
        required=True,
        tracking=True)
    answer = fields.Html(string='Answer', help='Model answer for the resource question.')

    has_default_answer = fields.Boolean()
    default_answer = fields.Html(string='Default Answer', help='Default answer template for the resource question.')

    has_notes = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
        ], string='Has Notes',
        default='no',
        help='Resources can include notes. A resource can use the parent\'s notes if set to "Use Parent".',
        required=True,
        tracking=True)
    notes = fields.Html(string='Notes', help='Notes for the resource.')

    lesson_plan = fields.Html(string='Lesson Plan', help='The lesson plan for this resource.')
    has_lesson_plan = fields.Boolean(string='Has Lesson Plan', store=True)

    has_child_resources = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ], string='Has Linked Resources',
        default='no',
        help='Linked resources can be used to break down a resource into smaller parts. They usually contribute to the overall marks of the parent resource.',
        required=True,
        tracking=True)

    has_supporting_resources = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ], string='Has Supporting Resources',
        default='no',
        help='Supporting resources can be used to add supplementary materials that do not contribute to the overall marks of the parent resource.',
        required=True,
        tracking=True)

    ai_instructions = fields.Html(
        string='AI Instructions',
        placeholder='Provide instructions for AI-assisted actions related to this resource only. For example, you can ask the AI to generate a model answer based on the question, or to provide feedback on a student\'s submission.',
        help='Additional instructions for AI-assisted actions related to this resource.',
    )
    ai_use_model_answer = fields.Boolean(string='Use Model Answer')
    ai_use_question = fields.Boolean(string='Use Question')
    ai_model_id = fields.Many2one(
        'aps.ai.model',
        string='AI Model',
        domain=[('enabled', '=', True)],
        help='If set, this model is used for AI generation for this resource and its submissions. Leave empty to use the normal enabled-model fallback order.',
    )
    ai_model_ids = fields.Many2many(
        'aps.ai.model',
        'aps_resources_ai_models_rel',
        'resource_id',
        'model_id',
        string='AI Models',
        domain=[('enabled', '=', True)],
        help=(
            'Select one or more AI models for this resource. '
            'When multiple models are selected they all run simultaneously and '
            'their results are merged. '
            'Leave empty to use the single "AI Model" field or the global fallback order.'
        ),
    )
    has_multiple_ai_models = fields.Boolean(
        string='Has Multiple AI Models',
        compute='_compute_has_multiple_ai_models',
        help='True when more than one model is selected in AI Models.',
    )
    ai_merge_responses = fields.Boolean(
        string='Merge Responses via AI',
        default=False,
        help=(
            'When multiple AI models are selected, send all their feedback to '
            'one model and ask it to produce a single merged response. '
            'When disabled the feedback from each model is concatenated.'
        ),
    )
    ai_merge_response_chunks = fields.Boolean(
        string='Merge Response Chunks',
        default=False,
        help=(
            'When multiple AI models return targeted (chunked) feedback, '
            'merge feedback items that share the same label rather than '
            'simply combining all items.'
        ),
    )
    ai_use_notes = fields.Boolean(string='Use Notes')
    ai_use_supporting_resources = fields.Boolean(string='Use Supporting Resources')
    ai_targeted_feedback = fields.Boolean(string='Targeted Feedback', help='Return highlighted feedback tied to specific points in the student answer, if supported by the AI model.')
    ai_toc = fields.Boolean(string='TOC', help='Inject the default Table of Contents prompt for this resource.')
    ai_summary = fields.Boolean(string='Summary', help='Inject the default Summary prompt for this resource.')
    ai_analysis = fields.Boolean(string='Analysis', help='Inject the default Analysis prompt for this resource.')
    ai_table_of_results = fields.Boolean(string='Table of Results', help='Inject the default Table of Results prompt for this resource.')
    ai_test_prompt = fields.Boolean(string='Test Prompt', help='Enable a test area to trial the AI prompt against a sample answer.')
    ai_answer = fields.Html(string='Test Answer', help='Sample answer to test the AI prompt against.')
    ai_feedback = fields.Html(string='AI Feedback', readonly=True, help='Feedback returned by the AI for the test answer.')
    ai_score = fields.Float(string='AI Score', digits=(16, 2), readonly=True, help='Score returned by the AI for the test answer, if applicable.')
    ai_score_comment = fields.Char(string='AI Score Comment', readonly=True, help='Comment about the score returned by the AI for the test answer, if applicable. This is used when a score is not returned to provide feedback on why.')

    ai_saved_responses = fields.Json(
        string='Saved AI Responses',
        copy=False,
        help='JSON storage for saved AI test prompt responses (name, date, model, answer, feedback, score, etc.).',
    )
    ai_show_saved_responses = fields.Boolean(
        string='Show Saved Responses',
        default=False,
        help='Toggle visibility of the saved AI responses section.',
    )
    ai_selected_response_key = fields.Char(
        string='Selected Saved Response',
        help='Key of the currently selected saved AI response.',
    )
    
    ai_action = fields.Selection([
        ('none', 'None'),
        ('mark_submission', 'Mark Submission'),
        ('mark_submission_use_answer', '--Dont Use---'),
        ('manual', 'Manual Action'),
    ], string='AI Action', default='none', required=True, tracking=True)

    ai_active_prompts = fields.Many2many(
        'ai_prompts',
        string='Active Prompts',
        compute='_compute_ai_active_prompts',
        help='The prompt records that will actually be combined for this resource, in runtime order.',
    )
    ai_prompt_ids = fields.Many2many(
        'ai_prompts',
        'aps_resources_ai_prompts_rel',
        'resource_id',
        'prompt_id',
        string='Prompts',
        domain=[('enabled', '=', True)],
        help='Optional prompts to include with AI instructions.',
    )

    thumbnail = fields.Binary(string='Thumbnail')

    type_id = fields.Many2one('aps.resource.types', string='Type', ondelete='set null', store=True, tracking=True)
    type_icon = fields.Image(string='Type Icon', compute='_compute_type_icon', readonly=True, store=True)
    type_color = fields.Char(string='Type Color', related='type_id.color', readonly=True)
    url = fields.Char(string='URL', required=False, tracking=True)
    category = fields.Selection([
        ('mandatory', 'Mandatory'),
        ('optional', 'Optional'),
        ('information', 'Information'),
        ], string='Category',
        default='optional',
        help='Identifies which resources should be assigned to students to complete.', tracking=True)
    marks = fields.Float(string='Out of Marks', digits=(16, 1), help='Maximum marks/points for this resource')
    weight = fields.Float(string='Weight', digits=(16, 1), help='Weight of this resource in the overall calculation')
    score_contributes_to_parent = fields.Boolean(
        string='Contributes to Parent Score',
        default=True,
        help='When enabled, this resource\'s score is included in the parent resource\'s total score calculation.',
    )
    subjects = fields.Many2many('aps.subject', string='Subjects')
    subject_categories = fields.Many2many(
        'aps.subject.category',
        'aps_resources_subject_category_rel',
        'resource_id',
        'category_id',
        string='Subject Categories',
        compute='_compute_subject_categories',
        store=True,
    )
    tag_ids = fields.Many2many('aps.resource.tags', string='Tags')
    task_ids = fields.One2many('aps.resource.task', 'resource_id', string='Tasks')
    parent_ids = fields.Many2many('aps.resources', 'aps_resources_rel', 'child_id', 'parent_id',
                                  string='Parent Resources', domain="[('id', '!=', id)]")
    supporting_parent_ids = fields.Many2many('aps.resources', 'aps_supporting_resources_rel', 'child_id', 'parent_id',
                                  string='Supporting Parent Resources', domain="[('id', '!=', id)]")

    # Dashboard computed fields
    total_submissions = fields.Integer(string='Total Submissions', compute='_compute_dashboard_stats', store=False)
    completed_submissions = fields.Integer(string='Completed Submissions', compute='_compute_dashboard_stats', store=False)
    overdue_tasks = fields.Integer(string='Overdue Tasks', compute='_compute_dashboard_stats', store=False)
    primary_parent_id = fields.Many2one(
        'aps.resources',
        string='Main Parent',
        domain="[('id', 'in', parent_ids)]",
        help='The resource used for generating the display name. Must be one of the selected parents.',
    )
    child_ids = fields.Many2many('aps.resources', 'aps_resources_rel', 'parent_id', 'child_id', string='Linked Resources', domain="[('id', '!=', id)]")
    child_count = fields.Integer(string='Total Children', compute='_compute_child_count')
    has_multiple_parents = fields.Boolean(string='Has Multiple Parents', compute='_compute_has_multiple_parents')
    supporting_resource_ids = fields.Many2many('aps.resources', 'aps_supporting_resources_rel', 'parent_id', 'child_id', string='Supporting Resources', domain="[('id', '!=', id)]")
    supporting_resource_count = fields.Integer(string='Supporting Resources Count', compute='_compute_supporting_resource_count')
    recent_submission_count = fields.Integer(string='Recent Submissions', compute='_compute_recent_submission_count')
    supporting_resources_buttons = fields.Json(
        string='Resource Links',
        compute='_compute_supporting_resources_buttons',
        help='JSON data containing resource links with icons for the widget.'
    )
    subject_icons = fields.Image(
        string='Subject Icon',
        compute='_compute_subject_icons',
        help='Icon for the first subject associated with the resource',
        store=True,
    )
    allow_subject_editing = fields.Boolean(
        string='Allow Subject Editing',
        default=False,
        help='If enabled, users can edit the subjects associated with this resource. This is useful for resources that are shared across multiple subjects, where the subject association may need to be customized at the submission level.',
    )

    # Auto Assign fields
    auto_assign = fields.Boolean(
        string='Auto Assign',
        default=False,
        help='If enabled, this resource will be automatically assigned to students on a recurring schedule.',
    )
    auto_assign_date = fields.Date(
        string='Next Assign Date',
        default=lambda self: fields.Date.add(fields.Date.context_today(self), days=2),
        help='The cron job will run on this date and then advance it by the frequency.',
    )
    auto_assign_end_date = fields.Date(
        string='End Date',
        help='Optional. Auto assignment stops after this date.',
    )
    auto_assign_due_days = fields.Integer(
        string='Due Days',
        default=6,
        help='How many days before this task becomes due. 0=the same day.',
    )
    auto_assign_frequency = fields.Integer(
        string='Frequency (days)',
        default=7,
        help='Number of days between automatic assignments.',
    )
    auto_assign_time = fields.Float(
        string='Time Assigned',
        default=0.0,
        help='Time of day (decimal) when the submission becomes active, e.g. 14.5 = 14:30.',
    )
    auto_assign_all_students = fields.Boolean(
        string='Assign All Students',
        default=True,
        help='If enabled, all students enrolled in the linked subjects will be assigned.',
    )
    auto_assign_student_ids = fields.Many2many(
        'res.partner',
        'aps_resources_auto_assign_students_rel',
        'resource_id',
        'partner_id',
        string='Students',
        domain=[('is_student', '=', True)],
        help='Students to assign when "Assign All Students" is disabled.',
    )
    auto_assign_notify_student = fields.Boolean(
        string='Notify Student',
        default=True,
        help='If enabled, students will receive a notification when assigned.',
    )
    auto_assign_custom_name = fields.Char(
        string='Custom Name',
        help='Overrides the default resource name. The assignment date will be appended automatically.',
    )
    auto_assign_log = fields.Text(
        string='Log',
        readonly=True,
        help='Record of automatic assignment runs.',
    )
    points_scale = fields.Integer(
        string='Points Scale', help="Scales the default points allocated to a resource.",
        default=1
    )
    display_name_breadcrumb = fields.Json(
        string='Display Name Breadcrumb',
        compute='_compute_display_name_breadcrumb',
        store=True,
        help='Stored list of [{id, label}] entries representing the ancestor chain for the breadcrumb pills widget.',
    )
    share_token = fields.Char(
        string='Share Token',
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: str(uuid.uuid4()),
        help='Unique token used to generate a public share URL for this resource.',
    )
    share_url = fields.Char(
        string='Share URL',
        compute='_compute_share_url',
        help='Public URL to share this resource with anyone.',
    )
    show_in_hierarchy = fields.Boolean(
        string='Show in Hierarchy',
        default=False,
        help='Include this resource in the Resource Hierarchy view.',
    )
    is_recently_viewed = fields.Boolean(
        string='Recently Viewed',
        compute='_compute_is_recently_viewed',
        search='_search_is_recently_viewed',
    )
    is_aps_manager = fields.Boolean(
        string='Is APEX Manager',
        compute='_compute_is_aps_manager',
        help='True when the current user belongs to the APEX Manager group.',
    )

    @api.depends_context('uid')
    def _compute_is_aps_manager(self):
        is_manager = self.env.user.has_group('aps_sis.group_aps_manager')
        for record in self:
            record.is_aps_manager = is_manager

    @api.depends('ai_model_ids')
    def _compute_has_multiple_ai_models(self):
        for record in self:
            record.has_multiple_ai_models = len(record.ai_model_ids) > 1

    @api.depends(
        'ai_prompt_ids',
        'ai_prompt_ids.enabled',
        'ai_prompt_ids.always_include',
        'ai_prompt_ids.applies_to_ai_models',
        'ai_prompt_ids.applies_to_db_models',
        'ai_prompt_ids.message_section',
        'ai_prompt_ids.prompt_name',
        'ai_prompt_ids.tag_ids',
        'ai_model_id',
        'ai_model_id.enabled',
        'ai_model_id.provider_id.enabled',
        'ai_model_ids',
        'ai_model_ids.enabled',
        'ai_model_ids.provider_id.enabled',
        'ai_action',
        'ai_use_model_answer',
        'ai_use_question',
        'ai_use_notes',
        'ai_targeted_feedback',
        'ai_toc',
        'ai_summary',
        'ai_analysis',
        'ai_table_of_results',
        'ai_instructions',
        'marks',
    )
    def _compute_ai_active_prompts(self):
        ai_model_env = self.env['aps.ai.model']
        empty_prompts = self.env['ai_prompts']
        for record in self:
            prompts = empty_prompts
            try:
                candidate_models = ai_model_env._get_generation_candidates(resource=record)
                active_model = candidate_models[:1]
                if active_model:
                    section_order = {
                        k: i for i, k in enumerate(active_model._get_prompt_section_order())
                    }

                    def _sort_key(r):
                        return (section_order.get(r.message_section or '', 9999), (r.sequence or 0), r.id)

                    prompts = active_model._collect_all_applicable_prompts(record.ai_prompt_ids, record._name)
                    instructions_text = active_model._html_to_text(record.ai_instructions or '').strip()
                    ctx_flags = {
                        'ai_targeted_feedback': bool(record.ai_targeted_feedback),
                        'ai_standard_feedback': not bool(record.ai_targeted_feedback),
                        'use_question': bool(record.ai_use_question),
                        'use_model_answer': bool(record.ai_use_model_answer or record.ai_action == 'mark_submission_use_answer'),
                        'use_note': bool(record.ai_use_notes),
                        'instructions': instructions_text,
                        'student_answer': True,  # Always include the student answer in the context for prompt tagging purposes, even if it's empty. This allows prompts to be tagged with "No Student Answer" or similar to handle empty answers.
                    }
                    # Exclude supplemental prompts from the candidate list so
                    # they do not suppress default prompts for the same section.
                    non_supplemental_ids = record.ai_prompt_ids.filtered(lambda p: not _is_supplemental(p))
                    extra = active_model._resolve_ctx_tagged_prompts(ctx_flags, non_supplemental_ids)
                    if extra:
                        prompts = (prompts | extra).sorted(key=_sort_key)
                    # Suppress "Specific Instructions" tagged prompts when there are no instructions
                    if not instructions_text and instructions_text != '':
                        prompts = prompts.filtered(
                            lambda p: not any(
                                t.name.strip().casefold() == 'specific instructions'
                                for t in p.tag_ids
                            )
                        )
                    # Inject the first "Score" tagged prompt when out_of_marks is non-zero
                    # and no prompt already in the active set covers the 'score' section.
                    if record.marks and not _section_covered(prompts, 'score'):
                        score_prompt = self.env['ai_prompts'].search(
                            [('enabled', '=', True), ('tag_ids.name', 'ilike', 'score')],
                            order='sequence asc, id asc',
                            limit=1,
                        )
                        if score_prompt and score_prompt not in prompts:
                            prompts = (prompts | score_prompt).sorted(key=_sort_key)
                    # Inject the first "Targeted Feedback" tagged prompt when targeted
                    # feedback is requested and no prompt already covers that section.
                    if record.ai_targeted_feedback and not _section_covered(prompts, 'targeted_feedback'):
                        targeted_prompt = self.env['ai_prompts'].search(
                            [('enabled', '=', True), ('tag_ids.name', 'ilike', 'targeted feedback')],
                            order='sequence asc, id asc',
                            limit=1,
                        )
                        if targeted_prompt and targeted_prompt not in prompts:
                            prompts = (prompts | targeted_prompt).sorted(key=_sort_key)
                    # Inject the first "TOC" tagged prompt when requested.
                    # TOC does not have a dedicated message_section; it is identified
                    # by a tag named "TOC".
                    if record.ai_toc:
                        if not _tag_covered(prompts, 'toc'):
                            toc_prompt = self.env['ai_prompts'].search(
                                [('enabled', '=', True), ('tag_ids.name', '=ilike', 'TOC')],
                                order='sequence asc, id asc',
                                limit=1,
                            )
                            if toc_prompt and toc_prompt not in prompts:
                                prompts = (prompts | toc_prompt).sorted(key=_sort_key)
                    # Inject the first enabled prompt for each section-based toggle when
                    # the toggle is enabled and no prompt already covers that section.
                    for toggle_field, section in _AI_SECTION_TOGGLES:
                        if getattr(record, toggle_field) and not _section_covered(prompts, section):
                            section_prompt = self.env['ai_prompts'].search(
                                [('enabled', '=', True), ('message_section', '=', section)],
                                order='sequence asc, id asc',
                                limit=1,
                            )
                            if section_prompt and section_prompt not in prompts:
                                prompts = (prompts | section_prompt).sorted(key=_sort_key)
                    # For each content section that has a paired format section,
                    # auto-inject the first enabled format prompt when the content
                    # section is active but no format prompt is already present
                    # (including any manually added via ai_prompt_ids).
                    _FORMAT_PAIRS = [
                        ('summary', 'summary_format'),
                        ('detailed_analysis', 'detailed_analysis_format'),
                        ('results_table', 'results_table_format'),
                    ]
                    for content_section, format_section in _FORMAT_PAIRS:
                        if (
                            _section_covered(prompts, content_section)
                            and not _section_covered(prompts, format_section)
                        ):
                            fmt_prompt = self.env['ai_prompts'].search(
                                [('enabled', '=', True), ('message_section', '=', format_section)],
                                order='sequence asc, id asc',
                                limit=1,
                            )
                            if fmt_prompt and fmt_prompt not in prompts:
                                prompts = (prompts | fmt_prompt).sorted(key=_sort_key)

            except Exception:
                prompts = empty_prompts
            record.ai_active_prompts = prompts

    @api.onchange(
        'ai_prompt_ids',
        'ai_model_id',
        'ai_model_ids',
        'ai_action',
        'ai_use_model_answer',
        'ai_use_question',
        'ai_use_notes',
        'ai_targeted_feedback',
        'ai_toc',
        'ai_summary',
        'ai_analysis',
        'ai_table_of_results',
        'ai_instructions',
    )
    def _onchange_ai_prompt_preview_fields(self):
        self._compute_ai_active_prompts()

    @api.depends('subjects', 'subjects.category_id')
    def _compute_subject_categories(self):
        for record in self:
            record.subject_categories = [(6, 0, record.subjects.mapped('category_id').ids)]

    def _get_image_bytes_from_url(self, src):
        """Resolve an image src URL to raw bytes using Odoo's ir.binary.

        Handles:
          - /web/image/<id>  (attachment by ID)
          - /web/image/model/id/field
          - data:image/...;base64,...
        Returns bytes or None.
        """
        import base64 as b64mod
        import re as _re

        if not src:
            return None

        # base64 data URI
        b64_match = _re.match(r'data:image/[^;]+;base64,(.+)', src, _re.DOTALL)
        if b64_match:
            try:
                return b64mod.b64decode(b64_match.group(1))
            except Exception:
                return None

        # /web/image/<id> — attachment by ID
        att_match = _re.match(r'/web/image/(\d+)(?:/.*)?$', src)
        if att_match:
            try:
                att = self.env['ir.attachment'].browse(int(att_match.group(1))).sudo()
                if att.exists() and att.datas:
                    import base64 as _b64
                    return _b64.b64decode(att.datas)
            except Exception:
                return None

        # /web/image/model/id/field — read binary field via ir.binary
        model_match = _re.match(r'/web/image/(\w+)/(\d+)/(\w+)', src)
        if model_match:
            try:
                model_name, res_id, field_name = model_match.groups()
                record = self.env[model_name].sudo().browse(int(res_id))
                if record.exists():
                    val = record[field_name]
                    if val:
                        return val if isinstance(val, bytes) else val.encode('latin-1') if isinstance(val, str) else None
            except Exception:
                return None

        return None

    def _ensure_image_aspect_ratios(self, html):
        """Inject aspect-ratio CSS into <img> tags that lack it.

        For each <img> in *html* that does not already have an aspect-ratio
        in its style attribute, resolve the image source, read dimensions
        with Pillow, and add ``aspect-ratio: W/H`` to the style.

        Returns (updated_html, changed) where *changed* is True if any
        <img> tags were modified.
        """
        import io
        import re
        try:
            from PIL import Image
        except ImportError:
            return html, False

        if not html or '<img' not in html.lower():
            return html, False

        changed = False

        def _replace_img(match):
            nonlocal changed
            tag = match.group(0)

            # Skip if style already contains aspect-ratio
            if 'aspect-ratio' in tag:
                return tag

            # Extract src
            src_match = re.search(r'src=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            if not src_match:
                return tag
            src = src_match.group(1)

            # Resolve image bytes
            img_bytes = self._get_image_bytes_from_url(src)
            if not img_bytes:
                return tag

            try:
                with Image.open(io.BytesIO(img_bytes)) as img:
                    w, h = img.size
                if w <= 0 or h <= 0:
                    return tag
            except Exception:
                return tag

            # Compute reduced aspect ratio
            from math import gcd
            d = gcd(w, h)
            ratio_w, ratio_h = w // d, h // d

            # Inject or update style attribute
            ratio_str = f'aspect-ratio: {ratio_w}/{ratio_h}'
            style_match = re.search(r'style=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            if style_match:
                old_style = style_match.group(1)
                new_style = f'{old_style.rstrip(";")}; {ratio_str}' if old_style.strip() else ratio_str
                tag = tag[:style_match.start(1)] + new_style + tag[style_match.end(1):]
            else:
                tag = re.sub(r'\s*/?\s*>$', f' style="{ratio_str}">', tag)
            changed = True
            return tag

        html = re.sub(r'<img\b[^>]*>', _replace_img, html, flags=re.IGNORECASE)
        return html, changed
