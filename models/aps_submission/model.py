import logging
from odoo import models, fields

from .constants import sentinel_zero

_logger = logging.getLogger(__name__)


class APSResourceSubmission(models.Model):
    _name = 'aps.resource.submission'
    _description = 'APEX Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    display_name = fields.Char(
        compute='_compute_display_name', store=True,
        help='The submission name'
        )
    submission_name = fields.Char(
        string='Submission Name',
    )
    task_id = fields.Many2one('aps.resource.task', string='Task', required=True)
    resource_id = fields.Many2one('aps.resources', string='Resource', related='task_id.resource_id')
    subjects = fields.Many2many('op.subject', string='Subjects')
    student_id = fields.Many2one('res.partner', string='Student', related='task_id.student_id')
    assigned_by = fields.Many2one('op.faculty', string='Assigned By', default=lambda self: self._default_assigned_by())
    submission_label = fields.Char(
        string='Label',
        help='Identifier for grouping submissions, e.g., S1 Exam, Exam Prep, Homework .'
    )
    submission_order = fields.Integer(string='Submission Order')
    state = fields.Selection([
        ('assigned', 'Assigned'),
        ('submitted', 'Submitted'),
        ('complete', 'Finalised'),  # Leave the underlying value as 'complete' for easier sync with task state
        ], string='State', default='assigned',
        tracking=True,
        required=True)
    date_assigned = fields.Date(
        string='Date Assigned',
        default=fields.Date.today)
    time_assigned = fields.Float(
        string='Time Assigned',
        help='The specific time when this submission should become active as a decimal (e.g., 14.5 = 14:30). If not set, the submission becomes active at midnight on the assigned date.')
    date_submitted = fields.Date(
        string='Date Submitted',
        help='The date when the submission was made by the student.',
        tracking=True)
    date_completed = fields.Date(
        string='Date Finalised',
        help='The date when the submission was marked as finalised by the teacher. Submissions may be rejected.',
        tracking=True)
    date_due = fields.Date(string='Due Date', tracking=True)
    score = fields.Float(string='Score', digits=(16, 2), tracking=True, default=sentinel_zero)
    out_of_marks = fields.Float(string='Out of Marks', digits=(16, 1), store=True, tracking=True)
    result_percent = fields.Integer(string='Result %', compute='_compute_result_percent', store=True, tracking=True)
    due_status = fields.Selection([
        ('late', 'Late'),
        ('on-time', 'On Time'),
        ('early', 'Early'),
    ], string='Due Status', compute='_compute_due_status', store=True)
    days_till_due = fields.Integer(compute='_compute_days_till_due', store=True)  # creates a class used to highlight records when they are nearing their due date
    actual_duration = fields.Float(string='Actual Duration (hours)', digits=(16, 1))
    feedback = fields.Html(string='Feedback')
    has_answer = fields.Selection(string='Has Answer', related='resource_id.has_answer', readonly=True, store=True)
    answer = fields.Html(string='Answer')
    has_feedback = fields.Boolean(string='Has Feedback', compute='_compute_has_feedback', store=True)
    reviewed_by = fields.Many2many(
        'op.faculty',
        'aps_submission_reviewed_by_rel',
        'submission_id',
        'faculty_id',
        string='Reviewed By',
        tracking=True,
    )
    review_requested_by = fields.Many2many(
        'op.faculty',
        'aps_submission_review_request_rel',
        'submission_id',
        'faculty_id',
        string='Review Requested By',
        help='Faculty members who have been requested to review this submission.',
        tracking=True,
    )
    is_current_user_faculty = fields.Boolean(compute='_compute_is_current_user_faculty')
    is_current_user_reviewed = fields.Boolean(compute='_compute_is_current_user_reviewed')
    model_answer = fields.Html(
        string='Model Answer',
        related='resource_id.answer',
        readonly=True,
        help='The model answer from the associated resource for comparison.'
    )
    model_answer_is_notes = fields.Boolean(
        string='Model Answer Is Notes',
        compute='_compute_model_answer_is_notes',
        store=False
    )
    has_question = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
        ], string='Has Question',
        default='no',
        help='A resource can use the parent\'s question if set to "Use Parent".',
        required=True,
        tracking=True)
    question = fields.Html(
        string='Question',
        help='The question from the associated resource.'
    )
    supporting_resources_buttons = fields.Json(
        string='Links',
        related='resource_id.supporting_resources_buttons',
        help='Links to resources associated with this submission (e.g., main resource and supporting resources).'
    )
    resource_notes = fields.Html(
        string='Notes',
        related='resource_id.notes',
        readonly=True,
        help='Notes from the associated resource.'
    )
    resource_has_notes = fields.Selection(
        string='Has Notes',
        related='resource_id.has_notes',
        readonly=True,
    )
    type_icon = fields.Image(
        string='Type Icon',
        compute="_compute_type_icon",
        store=True
    )
    subject_icons = fields.Image(
        string='Subject Icon',
        compute='_compute_subject_icons',
        help='Icon for the first subject associated with the resource',
        store=True,
    )
    submission_active = fields.Boolean(string='Active', compute="_compute_submission_active", default=False, store=True,
        help='Indicates whether the submission is active and so visible to the student based on the assigned date. A submission becomes active when the assigned date is today or in the past.')
    active_datetime = fields.Datetime(string='Active Since', compute='_compute_active_datetime', store=True, help='The datetime when the submission became active. Used to trigger notifications for new active submissions.')
    notified_active = fields.Boolean(
        string='Notified',
        default=lambda self: not self.env.user.has_group('aps_sis.group_aps_teacher'),
        help='Indicates whether the user has been notified that this submission is active. Defaults to False for teachers and True for others.'
    )
    notification_state = fields.Selection(required=True, default='skipped',
        selection= [('not_sent', 'Not Sent'), ('sent', 'Sent'), ('posted','Posted'), ('failed', 'Failed'), ('skipped', 'Skipped')],
        string='Notification State',
        help="Tracks the state of notifications for this submission. 'Not Sent' will allow the automated notification " \
        "process to attempt sending a notification. 'Sent' indicates an email has been sent while 'Posted' indicates that an Odoo message has been logged. " \
        "'Skipped' is the default for submissions that are not eligible for notifications and will be ignored by the notification process.")
    allow_subject_editing = fields.Boolean(
        string='Allow Subject Editing',
        default=False,
        help='If enabled, users can edit the subjects associated with this resource. This is useful for resources that are shared across multiple subjects, where the subject association may need to be customized at the submission level.',
    )
    points_scale = fields.Integer(string='Points Scale', default=0)  # I need to save this here because the scale changes depending on how the resource is being used. End of semester exmams the point scale is not used. Non enforced work is.
    points = fields.Integer(
        string='Points', compute='_compute_points', store=True,
        help='The points allocated to this submission.')

    # default_notebook_page = fields.Char(help="Used by the system to manage default pages.")
    default_notebook_page_per_user = fields.Json(
        help="Used by the system to manage default pages.",
        default=dict,
        # compute="_compute_default_notebook_page_per_user",
        # store=True
        )

    auto_score = fields.Boolean(
        string='Auto Score',
        default=True,
        help='If True, the score and answer summary are automatically calculated from child '
             'resource scores. Set to False when the score has been manually entered by a user.',
        tracking=True,
    )
