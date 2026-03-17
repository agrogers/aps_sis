import uuid
from odoo import models, fields


class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'APEX Resources'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    sequence = fields.Integer(string='Sequence', default=10)
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    name = fields.Char(string='Name', tracking=True)
    custom_name_ids = fields.One2many('aps.resource.custom.name', 'resource_id', string='Custom Names')
    # Computed JSON data of custom names for various parents for this resource
    parent_custom_name_data = fields.Json(string='Custom Names Data', compute='_compute_parent_custom_name_data', store=True)
    description = fields.Text(string='Description', tracking=True)

    has_question = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
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
        ('yes_notes', '!!! Dont Use'),
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
    score_contributes_to_parent = fields.Boolean(
        string='Contributes to Parent Score',
        default=True,
        help='When enabled, this resource\'s score is included in the parent resource\'s total score calculation.',
    )
    subjects = fields.Many2many('op.subject', string='Subjects')
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
    is_recently_viewed = fields.Boolean(
        string='Recently Viewed',
        compute='_compute_is_recently_viewed',
        search='_search_is_recently_viewed',
    )
