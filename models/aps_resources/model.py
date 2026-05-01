import uuid
from odoo import api, fields, models


class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'APEX Resources'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    sequence = fields.Integer(string='Sequence', default=10)
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True, recursive=True)
    name = fields.Char(string='Name', tracking=True)
    custom_name_ids = fields.One2many('aps.resource.custom.name', 'resource_id', string='Custom Names')
    # Computed JSON data of custom names for various parents for this resource
    parent_custom_name_data = fields.Json(string='Custom Names Data', compute='_compute_parent_custom_name_data', store=True)
    description = fields.Text(string='Description', tracking=True)

    has_question = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('hidden', 'Yes (Hidden)'),
        ('use_parent', 'Use Parent'),
        ], string='Has Question',
        default='no',
        help='A resource can use the parent\'s question if set to "Use Parent".',
        required=True,
        tracking=True)
    question = fields.Html(string='Question')

    has_answer = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('hidden', 'Yes (Hidden)'),
        ('use_parent', 'Use Parent'),
        ], string='Has Answer',
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
        placeholder='Provide instructions for AI-assisted actions related to this resource. For example, you can ask the AI to generate a model answer based on the question, or to provide feedback on a student\'s submission.',
        help='Additional instructions for AI-assisted actions related to this resource.',
    )
    ai_use_model_answer = fields.Boolean(string='Use Model Answer')
    ai_use_question = fields.Boolean(string='Use Question')
    ai_prompt_ids = fields.Many2many(
        'ai_prompts',
        'aps_resources_ai_prompts_rel',
        'resource_id',
        'prompt_id',
        string='Prompts',
        domain=[('enabled', '=', True)],
        help='Optional prompts to include with AI instructions.',
    )
    ai_use_notes = fields.Boolean(string='Use Notes')
    ai_use_supporting_resources = fields.Boolean(string='Use Supporting Resources')
    ai_targeted_feedback = fields.Boolean(string='Targeted Feedback', help='Return highlighted feedback tied to specific points in the student answer, if supported by the AI model.')
    ai_test_prompt = fields.Boolean(string='Test Prompt', help='Enable a test area to trial the AI prompt against a sample answer.')
    ai_answer = fields.Html(string='Test Answer', help='Sample answer to test the AI prompt against.')
    ai_feedback = fields.Html(string='AI Feedback', readonly=True, help='Feedback returned by the AI for the test answer.')

    ai_action = fields.Selection([
        ('none', 'None'),
        ('mark_submission', 'Mark Submission'),
        ('mark_submission_use_answer', '--Dont Use---'),
        ('manual', 'Manual Action'),
    ], string='AI Action', default='none', required=True, tracking=True)

    ai_additional_prompt_ids = fields.Many2many(
        'ai_prompts',
        'aps_resources_ai_included_prompts_rel',
        'resource_id',
        'prompt_id',
        string='Additional Prompts',
        compute='_compute_ai_additional_prompt_ids',
        help='Prompts that will be included in AI calls for this resource, based on selected prompts and always-include rules.',
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
    subjects = fields.Many2many('op.subject', string='Subjects')
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

    @api.depends(
        'ai_prompt_ids',
        'ai_prompt_ids.enabled',
        'ai_prompt_ids.always_include',
        'ai_prompt_ids.applies_to_db_models',
    )
    def _compute_ai_additional_prompt_ids(self):
        always_prompts = self.env['ai_prompts'].sudo().search([
            ('enabled', '=', True),
            ('always_include', '=', True),
        ])
        for record in self:
            # selected = record.ai_prompt_ids.filtered(lambda p: p.enabled)
            always = always_prompts.filtered(
                lambda p: not p.applies_to_db_models
                or record._name in p.applies_to_db_models.mapped('model')
            )
            # record.ai_additional_prompt_ids = (selected | always)
            record.ai_additional_prompt_ids = always

    @api.depends('subjects', 'subjects.category_id')
    def _compute_subject_categories(self):
        for record in self:
            record.subject_categories = [(6, 0, record.subjects.mapped('category_id').ids)]