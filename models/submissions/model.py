from datetime import datetime, time, timedelta
import re

import pytz
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)
sentinel_zero = -0.01


def alpha_to_float(alpha_val, sentinel=sentinel_zero):
    """Parse an alpha score string to its numeric equivalent.

    Returns the parsed float when *alpha_val* is a valid number, or *sentinel*
    when it is empty, ``False``, or a non-numeric special code (e.g. "A", "-").
    """
    if not alpha_val or not str(alpha_val).strip():
        return sentinel
    cleaned = str(alpha_val).replace(',', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return sentinel

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
    type_id = fields.Many2one(
        'aps.resource.types',
        string='Resource Type',
        related='resource_id.type_id',
        readonly=True,
        store=True,
    )
    subject_categories = fields.Many2many(
        'aps.subject.category',
        'aps_submission_subject_category_rel',
        'submission_id',
        'category_id',
        string='Subject Categories',
        compute='_compute_subject_categories',
        readonly=True,
        store=True,
    )
    url = fields.Char(
        string='URL',
        tracking=True,
        help='Optional submission-specific URL override for the main assigned resource.'
    )
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
    score_alpha = fields.Char(
        string='Score',
        tracking=True,
        help='Score as text. Accepts a number or a special code such as A (Absent), C (Cheating), or - (Excluded). '
             'Changing this field automatically updates the numeric Score field.',
    )
    out_of_marks = fields.Float(string='Out of Marks', digits=(16, 1), store=True, tracking=True)
    out_of_marks_alpha = fields.Char(
        string='Out of Marks',
        tracking=True,
        help='Out-of-marks as text. Accepts a number or a special code. '
             'Changing this field automatically updates the numeric Out of Marks field.',
    )
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
        compute='_compute_supporting_resources_buttons',
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
    default_notebook_page_per_user = fields.Json(
        help="Used by the system to manage default pages.",
        default=dict,
        )
    auto_score = fields.Boolean(
        string='Auto Score',
        default=True,
        help='If True, the score and answer summary are automatically calculated from child '
             'resource scores. Set to False when the score has been manually entered by a user.',
        tracking=True,
    )

# region - Computed Fields

    @api.depends('resource_id', 'resource_id.subject_categories')
    def _compute_subject_categories(self):
        for record in self:
            record.subject_categories = [(6, 0, record.resource_id.subject_categories.ids)]

    @api.depends('date_submitted', 'date_due', 'state', 'points_scale')
    def _compute_points(self):
        for record in self:
            if record.state in ['complete', 'submitted'] and record.date_submitted:
                if not record.date_due:
                    points = 1  # on time if no due date. This means that the user has chosen to resubmit something. Set the points low so they can't easily resubmit multiple times to farm points but still give them some points for resubmitting. 
                else:
                    days_from_due_date = record.date_submitted - record.date_due
                    days_diff = days_from_due_date.days
                    
                    if days_diff > 2:  # very late (more than 2 days after due)
                        points = 1
                    elif days_diff > 0:  # late (1-2 days after due)
                        points = 2
                    elif days_diff >= -1:  # on time (on due date or 1 day early)
                        points = 3
                    elif days_diff >= -2:  # early (2 days early)
                        points = 4
                    else:  # very early (more than 2 days early)
                        points = 5

                record.points = int(points * record.points_scale)
            else:
                record.points = 0

    @api.depends('resource_id.supporting_resources_buttons', 'url')
    def _compute_supporting_resources_buttons(self):
        for record in self:
            links = record.resource_id.supporting_resources_buttons or []
            if record.url:
                overridden_links = []
                for link in links:
                    updated_link = dict(link)
                    if updated_link.get('is_main'):
                        updated_link['url'] = record.url
                    overridden_links.append(updated_link)
                record.supporting_resources_buttons = overridden_links
            else:
                record.supporting_resources_buttons = links

    @api.depends('resource_id.type_id', 'resource_id.type_id.icon')
    def _compute_type_icon(self):
        # This is needed because without it the icon is never cached properly. 
        # That means there is a lot of annoying downloads on every page refresh.
        # It is duplicated in other models as well.
        for record in self:
            record.type_icon = record.resource_id.type_id.icon if record.resource_id.type_id else False

    @api.depends('subjects', 'subjects.icon')
    def _compute_subject_icons(self):
        for record in self:
            if record.subjects:
                first = record.subjects[:1]
                record.subject_icons = first.icon if first else False
            else:
                record.subject_icons = False

    @api.depends('date_due','state')
    def _compute_days_till_due(self):
        today = fields.Date.today()
        for record in self:
            if not record.date_due or record.state != 'assigned':
                record.days_till_due = 999  # Arbitrary large number for no due date, essentially "not due"
                continue
            
            record.days_till_due = (record.date_due - today).days

    @api.depends('date_assigned', 'time_assigned')
    def _compute_submission_active(self):
        # There are problems with the way Odoo handles timezones and datetimes. Odoo stores datetimes in UTC 
        # and converts to local time based on the user's timezone. 
        # However, for the purpose of activating submissions based on the assigned date and time, 
        # we want to use a fixed timezone (Myanmar) regardless of the user's actual timezone. 
        # This is because the activation of submissions should be consistent for all users based on Myanmar local time.
        
        # I would prefer to filter records in the cron itself but I cant. I could filter just for non-active records
        # but that would cause problems with records that need to be deactivated when the assigned date is in the future. So instead I fetch all records that could possibly be active or inactive based on the assigned date and then filter them in Python. This is not ideal but it is necessary due to the limitations of Odoo's timezone handling and the need for consistent activation based on Myanmar local time.
        # Having two separate cron jobs for activation and deactivation would improve things because I can run the activaiton cron every minute and the deactivation cron every hour for example. But for simplicity I will keep it as one cron job that runs every 15 minutes and checks for both activation and deactivation candidates.
        
        # Hardcoded timezone for Myanmar (UTC+6:30, no DST) / this needs to be changed to use the TZ of the user who created the record or the server action
        FIXED_TZ_NAME = 'Asia/Yangon'
        tz = pytz.timezone(FIXED_TZ_NAME)

        # Current time in UTC (what Odoo uses internally)
        now_utc = fields.Datetime.now()

        # Current local time/date in Myanmar timezone (for domain filtering)
        now_local = now_utc.astimezone(tz)
        today_local = now_local.date()
        today_str = today_local.strftime('%Y-%m-%d')

        # Fetch only potential candidates based on date in Myanmar local time
        candidates_domain = [
            '|',
            '&', ('submission_active', '=', False), ('date_assigned', '<=', today_str),
            '&', ('submission_active', '=', True),
                 '|', ('date_assigned', '=', False), ('date_assigned', '>', today_str),
        ]

        candidates = self.search(candidates_domain)

        to_activate = self.env['aps.resource.submission']
        to_deactivate = self.env['aps.resource.submission']

        for record in candidates:
            if record.submission_active:
                # Already active → deactivate if date is future or missing
                to_deactivate |= record
                continue

            # Activation candidates (inactive)
            if not record.date_assigned:
                continue  # no date → skip or handle separately

            # Interpret date_assigned + time_assigned as local Myanmar time
            local_date = fields.Date.from_string(record.date_assigned)

            if not record.time_assigned or record.time_assigned == 0:
                # No time specified → activate at 00:00 Myanmar time
                local_dt_naive = datetime.combine(local_date, time(0, 0))
            else:
                # time_assigned is float hours (e.g. 13.5 → 13:30)
                hours = int(record.time_assigned)
                minutes = int((record.time_assigned - hours) * 60)
                local_dt_naive = datetime.combine(local_date, time(hours, minutes))

            # Make it timezone-aware (assume input was meant in Myanmar local time)
            local_dt_aware = tz.localize(local_dt_naive, is_dst=None)  # is_dst=None raises error on ambiguous times (rare)

            # Convert to naive UTC datetime for comparison with Odoo's now_utc
            assign_utc = local_dt_aware.astimezone(pytz.UTC).replace(tzinfo=None)

            # Activate if current UTC time has passed the assigned UTC time
            if now_utc >= assign_utc:
                to_activate |= record

        # Apply batch updates
        if to_activate:
            to_activate.write({'submission_active': True})
        if to_deactivate:
            to_deactivate.write({'submission_active': False})

    @api.model
    def recompute_submission_active_status(self):
        """Cron entrypoint: run auto-assign then recompute submission active flags."""
        try:
            # Reuse this minute-based cron to drive scheduled resource auto-assignment.
            self.env['aps.resources'].run_auto_assign()
        except Exception as exc:
            _logger.exception('Auto-assign step failed during recompute cron: %s', exc)

        submissions = self.search([])
        submissions._compute_submission_active()

    @api.depends('date_assigned', 'submission_active')
    def _compute_active_datetime(self):
        for record in self:
            if record.submission_active and not record.active_datetime:
                record.active_datetime = fields.Datetime.now()
            elif not record.submission_active:
                record.active_datetime = False

    @api.depends('feedback')
    def _compute_has_feedback(self):
        for record in self:
            feedback_text = str(record.feedback or '')
            feedback_text = feedback_text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
            for tag in ('</p>', '</div>', '</li>', '</h1>', '</h2>', '</h3>', '</h4>'):
                feedback_text = feedback_text.replace(tag, '\n')
            feedback_text = re.sub(r'<[^>]+>', '', feedback_text)
            feedback_text = feedback_text.replace('&nbsp;', ' ').strip()
            record.has_feedback = bool(feedback_text)

    @api.depends('date_assigned')
    def _compute_date_due(self):
        for record in self:
            if record.date_assigned:
                # Set due date to 7 days after assignment
                record.date_due = fields.Date.add(record.date_assigned, days=7)
            else:
                record.date_due = False

    @api.depends('date_due', 'date_submitted', 'date_completed', 'state')
    def _compute_due_status(self):
        
        now = fields.Date.today()
        for record in self:
           
            # Use completion date if submission is complete, otherwise use current date
            # Handle case where date_submitted is not set yet during state transition
            if record.state in ['submitted', 'complete'] and record.date_submitted:
                compare_date = record.date_submitted
            else:
                compare_date = now
            
            if not record.date_due:
                if record.state == 'assigned':
                    record.due_status = False
                else:
                    record.due_status = 'on-time'
            else:
                # Early: submitted 1 day or more before due date
                due_date_minus_1 = fields.Date.add(record.date_due, days=-1)

                if record.date_due and compare_date < due_date_minus_1:
                    # if the submission is well before the due date
                    record.due_status = 'early' if record.state in ['submitted', 'complete'] else False                    
                elif compare_date <= record.date_due:
                    # If the submission is within 1 day of the due date then it is on-time
                    record.due_status = 'on-time' if record.state in ['submitted', 'complete'] else False
                else:  
                    # If due date has passed, then the submission is late regardless of State
                    record.due_status = 'late'

    @api.depends()
    def _compute_is_current_user_faculty(self):
        faculty = self._get_current_faculty()
        for record in self:
            record.is_current_user_faculty = bool(faculty)

    @api.depends('reviewed_by')
    def _compute_is_current_user_reviewed(self):
        faculty = self._get_current_faculty()
        for record in self:
            record.is_current_user_reviewed = bool(faculty) and (faculty in record.reviewed_by)

    @api.depends('resource_id.has_answer', 'resource_id.primary_parent_id.has_answer')
    def _compute_model_answer_is_notes(self):
        for record in self:
            resource = record.resource_id
            record.model_answer_is_notes = bool(
                resource
                and (
                    resource.has_answer == 'yes_notes'
                    or (resource.has_answer == 'use_parent' and resource.primary_parent_id and resource.primary_parent_id.has_answer == 'yes_notes')
                )
            )

    @api.depends('score', 'out_of_marks')  # Needed to trigger recompute when related model fields change fields change
    def _compute_result_percent(self):
        """Auto-calculate result_percent based on score and out_of_marks"""
        for record in self:
            if record.score and record.score != sentinel_zero and record.out_of_marks and record.out_of_marks != sentinel_zero:
                record.result_percent = int(round((record.score / record.out_of_marks) * 100))
            elif record.score == sentinel_zero or not record.out_of_marks or record.out_of_marks == sentinel_zero:
                record.result_percent = 0
        
    @api.depends('date_assigned', 'submission_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.submission_name} ({record.date_assigned})"

# endregion - Computed Fields

# region - Alpha-Numeric Score Helpers

    @api.onchange('score_alpha')
    def _onchange_score_alpha(self):
        """Keep the numeric score field in sync with score_alpha."""
        self.score = alpha_to_float(self.score_alpha)

    @api.onchange('out_of_marks_alpha')
    def _onchange_out_of_marks_alpha(self):
        """Keep the numeric out_of_marks field in sync with out_of_marks_alpha."""
        self.out_of_marks = alpha_to_float(self.out_of_marks_alpha)

# endregion - Alpha-Numeric Score Helpers

    def _get_faculty_for_current_user(self):
        """Get the faculty record for the current user"""
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        if employee:
            faculty = self.env['op.faculty'].search([('emp_id', '=', employee.id)], limit=1)
            return faculty
        return False

    def _default_assigned_by(self):
        """Get the faculty record for the current user"""
        faculty = self._get_faculty_for_current_user()
        return faculty.id if faculty else False

    def _get_current_faculty(self):
        """Get the faculty record for the current user"""
        return self._get_faculty_for_current_user()
