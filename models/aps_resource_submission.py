from datetime import datetime, time, timedelta
import json
import ast

import pytz
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from lxml import etree

_logger = logging.getLogger(__name__)
sentinel_zero = -0.01

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

# region - Computed Fields

    # @api.depends('default_notebook_page')
    # def _compute_default_notebook_page_per_user(self):
    #     for rec in self:
    #         current_user_id = self.env.user.id
    #         data = rec.default_notebook_page_per_user or {}
    #         data[current_user_id] = rec.default_notebook_page
    #         rec.default_notebook_page_per_user = data

    @api.depends('date_submitted', 'date_due', 'state', 'points_scale')
    def _compute_points(self):
        for record in self:
            if record.state in ['complete', 'submitted'] and record.date_submitted:
                if not record.date_due:
                    points = 3  # on time if no due date
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
        """Recompute active status for all submissions. Called by cron job daily."""
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
            record.has_feedback = bool(record.feedback and record.feedback.strip())

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

# region - Auto Score / Auto Answer

    @staticmethod
    def _fmt_num(n):
        """Format a number, removing unnecessary decimal places."""
        if n == int(n):
            return str(int(n))
        return f"{n:.2f}"

    def _recalculate_score_from_children(self):
        """For records with auto_score=True, recalculate score and answer summary
        from child resource submissions for the same student and submission label.

        The parent score is only updated when *every* contributing child has at
        least one submission in the 'submitted' or 'complete' state for the same
        student and label.  When a child resource has multiple submissions with the
        same label the one with the highest score is used so that duplicate entries
        do not distort the total.
        """
        for record in self:
            if not record.auto_score:
                continue

            child_resources = record.resource_id.child_ids if record.resource_id else False
            if not child_resources:
                continue

            # Only include children that contribute to the parent score
            contributing_children = child_resources.filtered(lambda r: r.score_contributes_to_parent)
            if not contributing_children:
                continue

            base_domain = [
                ('resource_id', 'in', contributing_children.ids),
                ('student_id', '=', record.student_id.id),
            ]
            if record.submission_label:
                base_domain.append(('submission_label', '=', record.submission_label))

            # Guard: every contributing child must have at least one submitted or
            # completed submission (same student, same label) before we update the
            # parent.  If any child is missing one we skip this parent entirely.
            submitted_resource_ids = set(
                self.search(base_domain + [('state', 'in', ('submitted', 'complete'))]).mapped('resource_id.id')
            )
            if not all(c.id in submitted_resource_ids for c in contributing_children):
                continue

            child_submissions = self.search(base_domain).sorted(
                lambda s: (s.submission_order or 999, s.submission_name or '')
            )

            if not child_submissions:
                continue

            # Deduplicate: for each contributing child resource keep only the
            # submission with the best (highest) score.  This handles the edge
            # case where a child resource has two submissions sharing the same
            # label and resource ID.
            best_per_resource = {}
            for sub in child_submissions:
                rid = sub.resource_id.id
                sub_score = sub.score if sub.score != sentinel_zero else 0.0
                existing = best_per_resource.get(rid)
                if existing is None:
                    best_per_resource[rid] = sub
                else:
                    existing_score = existing.score if existing.score != sentinel_zero else 0.0
                    if sub_score > existing_score:
                        best_per_resource[rid] = sub

            deduplicated = sorted(
                best_per_resource.values(),
                key=lambda s: (s.submission_order or 999, s.submission_name or ''),
            )

            total_score = 0.0
            total_out_of = 0.0
            lines = []

            for child_sub in deduplicated:
                score = child_sub.score if child_sub.score != sentinel_zero else 0.0
                out_of = child_sub.out_of_marks or 0.0
                name = child_sub.submission_name or child_sub.display_name or '?'
                lines.append(
                    f"{name}) Score: {self._fmt_num(score)}/{self._fmt_num(out_of)}"
                )
                total_score += score
                total_out_of += out_of

            new_score = total_score if total_out_of > 0 else sentinel_zero

            if not lines:
                continue

            total_line = f"TOTAL: {self._fmt_num(total_score)}/{self._fmt_num(total_out_of)}"
            all_lines = lines + [total_line]
            summary_html = '<p>' + '</p><p>'.join(all_lines) + '</p>'

            # Pass auto_score=True explicitly so write() does not flip the flag back to False
            record.write({
                'score': new_score,
                'answer': summary_html,
                'auto_score': True,
            })

    def _check_and_update_parent_score(self):
        """After a score update on this record, find the corresponding parent submissions
        for all parent resources and trigger a score recalculation if the parent has
        auto_score enabled."""
        for record in self:
            if not record.resource_id or not record.resource_id.parent_ids:
                continue

            for parent_resource in record.resource_id.parent_ids:
                # Find the parent task for the same student
                parent_task = self.env['aps.resource.task'].search([
                    ('resource_id', '=', parent_resource.id),
                    ('student_id', '=', record.student_id.id),
                ], limit=1)

                if not parent_task:
                    continue

                # Find the parent submission, preferring one with a matching label
                parent_domain = [('task_id', '=', parent_task.id)]
                if record.submission_label:
                    parent_domain.append(('submission_label', '=', record.submission_label))

                parent_submission = self.search(parent_domain, order='create_date desc', limit=1)

                if not parent_submission:
                    continue

                if parent_submission.auto_score:
                    parent_submission._recalculate_score_from_children()

# endregion - Auto Score / Auto Answer

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

# region - Action Methods
    def action_mark_complete(self):
        today = fields.Date.today()

        for record in self:
            faculty = self._get_current_faculty()
            if not faculty:
                raise UserError("Only faculty members can mark submissions as complete.")

            if record.state == 'complete':
                continue  # or raise / log / skip

            record.write({
                'state': 'complete',
                'date_completed': today,
            })

        # Optional success message
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_mark_submitted(self):
        self.write({
            'state': 'submitted',
            'date_submitted': fields.Date.today(),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_mark_unsubmitted(self):
        self.write({
            'state': 'assigned',
            'date_submitted': False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_resubmit(self):
        """Resubmit the submission by creating a copy with cleared fields."""
        faculty = self._get_current_faculty()
        faculty_id = faculty.id if faculty else False
        
        for record in self:
            new_submission = record.copy({
                'assigned_by': faculty_id,
                'date_due': False,
                'answer': None,
                'feedback': None,
                'reviewed_by': [(5,)],  # Clear many2many
                'review_requested_by': [(5,)],  # Clear many2many
                'state': 'assigned',  # Reset to assigned
                'date_submitted': False,
                'date_completed': False,
                'score': sentinel_zero,
                'result_percent': 0,
                'active_datetime': False,
                'submission_active': True,

            })
        
        # Open the new submission form
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resubmitted Submission',
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': new_submission.id,
            'target': 'current',
        }

    def action_set_due_status_on_time(self):
        self.write({
            'due_status': 'on-time',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_mark_reviewed(self):
        faculty = self._get_current_faculty()
        if not faculty:
            raise UserError("Only faculty members can mark submissions as reviewed.")

        for record in self:
            record.write({
                'reviewed_by': [(4, faculty.id)],
                'review_requested_by': [(3, faculty.id)],
            })

        return True

    def action_open_student_dashboard(self):
        """Open the student dashboard for the current submission's student."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.student_id.name} - Dashboard',
            'res_model': 'aps.resource.submission',
            'view_mode': 'graph,calendar,list',
            'domain': [('student_id', '=', self.student_id.id)],
            'context': {'search_default_student_id': self.student_id.id},
            'target': 'current',
        }

    def action_open_submission(self):
        """Open the submission form view."""
        self.ensure_one()
        view_id = self.env.ref('aps_sis.view_aps_resource_submission_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'views': [(view_id, 'form')] if view_id else [],  # only include if view exists
        }
    
    def action_open_submission_student_view(self):
        """Open the submission form view for students."""
        self.ensure_one()
        view_id = self.env.ref('aps_sis.view_aps_resource_submission_form_for_students').id
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'context': {
                'default_notebook_page': 'question_page',
            },
            'views': [(view_id, 'form')] if view_id else [],  # only include if view exists
        }

    def action_open_task(self):
        """Open the linked task's form view."""
        self.ensure_one()
        if not self.task_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.task_id.display_name,
            'res_model': 'aps.resource.task',
            'view_mode': 'form',
            'res_id': self.task_id.id,
            'target': 'current',
        }

# endregion - Action Methods

# region - Overrides and records methods

    def write(self, vals):
        
        # Mark score and answer as manually set when either is changed without explicitly
        # passing auto_score=True. Our auto-calculation code always passes auto_score=True
        # explicitly, so this only triggers for user-initiated changes.
        if ('score' in vals or 'answer' in vals) and 'auto_score' not in vals:
            vals['auto_score'] = False

        # Capture old auto_score values to detect transitions to True
        old_auto_score = {rec.id: rec.auto_score for rec in self}

        # Handle automatic date setting based on state changes
        if 'state' in vals:
            for record in self:
                # If changing to submitted and no submission date, set it to today
                if vals['state'] == 'submitted':
                    if record.subjects:
                        record._notify_new_submission(subject.id for subject in record.subjects)

                    if not record.date_submitted and 'date_submitted' not in vals:
                        vals['date_submitted'] = fields.Date.today()
                
                # If changing to complete and no completion date, set it to today
                elif vals['state'] == 'complete' and not record.date_completed and 'date_completed' not in vals:
                    vals['date_completed'] = fields.Date.today()
                    # Also ensure submission date is set if missing
                    if not record.date_submitted and 'date_submitted' not in vals:
                        vals['date_submitted'] = fields.Date.today()

                # Also set date_assigned if not set (for auto-assigned submissions)
                if not record.date_assigned and 'date_assigned' not in vals:
                    vals['date_assigned'] = fields.Date.today()
                

        old_faculty_map = {rec.id: set(rec.review_requested_by.ids) for rec in self}

        result = super().write(vals)
        
        # Update task state when submission state changes
        if 'state' in vals:
            # Get unique tasks from the submissions
            tasks = self.mapped('task_id')
            if tasks:
                tasks._update_state_from_submissions()

        # When auto_score is reset to True, immediately recalculate from children
        if vals.get('auto_score') is True:
            to_recalculate = self.filtered(
                lambda r: not old_auto_score.get(r.id, True)
            )
            if to_recalculate:
                to_recalculate._recalculate_score_from_children()

        # When score changes (for any reason), or a submission reaches a
        # submitted/complete state, check if a parent submission needs updating.
        if 'score' in vals or vals.get('state') in ('submitted', 'complete'):
            self._check_and_update_parent_score()

        if 'review_requested_by' in vals:
            for record in self:
                old_ids = old_faculty_map.get(record.id, set())
                new_ids = set(record.review_requested_by.ids)
                
                # Find only the IDs that are in the new set but weren't in the old set
                added_ids = new_ids - old_ids
                # Find IDs that were in the old set but are not in the new set
                removed_ids = old_ids - new_ids
                
                if added_ids:
                    record._notify_new_faculty_reviewers(added_ids)
                    
                    # Add the new faculty members as followers
                    faculty_to_follow = self.env['op.faculty'].browse(added_ids)
                    partner_ids = faculty_to_follow.mapped('partner_id.id')
                    if partner_ids:
                        record.message_subscribe(partner_ids=partner_ids)
                
                if removed_ids:
                    # Remove faculty members as followers when they're no longer requested to review
                    faculty_to_unfollow = self.env['op.faculty'].browse(removed_ids)
                    partner_ids = faculty_to_unfollow.mapped('partner_id.id')
                    if partner_ids:
                        record.message_unsubscribe(partner_ids=partner_ids)
        return result
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'state' not in vals:
                vals['state'] = 'assigned'
        
        # Copy question from resource if not explicitly provided
        for vals in vals_list:
            if 'question' not in vals and 'task_id' in vals:
                task = self.env['aps.resource.task'].browse(vals['task_id'])
                if task.resource_id and task.resource_id.question:
                    vals['question'] = task.resource_id.question

        # Default out_of_marks from the linked resource if not explicitly set
        for vals in vals_list:
            if 'out_of_marks' not in vals:
                resource = None
                if 'resource_id' in vals:
                    resource = self.env['aps.resources'].browse(vals['resource_id'])
                elif 'task_id' in vals:
                    task = self.env['aps.resource.task'].browse(vals['task_id'])
                    resource = task.resource_id
                if resource:
                    vals['out_of_marks'] = resource.marks

        submissions = super().create(vals_list)
        # Update task states for newly created submissions
        tasks = submissions.mapped('task_id')
        if tasks:
            tasks._update_state_from_submissions()
        # Log creation for debugging
        for submission in submissions:
            _logger.info(f"Created submission {submission.id} for task {submission.task_id.id}")
            
            # Add faculty reviewers and assigner as followers
            partner_ids = []
            
            # Add student as follower
            if submission.student_id:
                partner_ids.append(submission.student_id.id)
            
            # Add assigned faculty as follower
            if submission.assigned_by and submission.assigned_by.partner_id:
                partner_ids.append(submission.assigned_by.partner_id.id)
            
            # Add faculty reviewers as followers
            if submission.review_requested_by:
                reviewer_partner_ids = submission.review_requested_by.mapped('partner_id.id')
                partner_ids.extend(reviewer_partner_ids)
            
            # Subscribe all relevant partners
            if partner_ids:
                submission.message_subscribe(partner_ids=list(set(partner_ids)))
        
        return submissions

    def copy(self, default=None):
        if default is None:
            default = {}
        default['answer'] = None
        default['feedback'] = None
        default['date_assigned'] = fields.Date.today()
        default['date_submitted'] = False
        default['date_completed'] = False
        default['reviewed_by'] = []
        default['review_requested_by'] = []
        faculty = self._get_current_faculty()
        default['assigned_by'] = faculty.id if faculty else False
        default['score'] = sentinel_zero
        # date_due will be recomputed based on the new date_assigned
        return super().copy(default)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        """
        Intercepts the view loading process. If a student is logged in,
        force the use of student-specific views regardless of what was requested.
        """
        import traceback
        _logger.warning(f"_get_view called: view_id={view_id}, view_type={view_type}, user={self.env.user.name}, student_group={self.env.user.has_group('aps_resource_submission.group_aps_student')}")
        _logger.warning(f"Call stack: {traceback.format_stack()[-3:-1]}")
        
        # 1. Check if user is a student
        if self.env.user.has_group('aps_resource_submission.group_aps_student'):
            
            # 2. Redirect 'tree' (list) requests to the student list view
            if view_type == 'list': # In v18, 'tree' is often 'list' in the backend
                view_id = self.env.ref('aps_resource_submission.view_aps_resource_submission_list_for_students').id
                
            # 3. Redirect 'form' requests to the student form view
            elif view_type == 'form':
                view_id = self.env.ref('aps_resource_submission.view_aps_resource_submission_form_for_students').id

        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form':
            if view.name == 'aps.resource.submission.form.for.students':
                for node in arch.xpath("//field"):
                    
                    if node.get('name') not in  ['answer','score','review_requested_by','subjects','default_notebook_page_per_user']:
                        options_str = node.get('options') or '{}'
                        try:
                            # Try parsing as JSON first
                            options = json.loads(options_str)
                        except json.JSONDecodeError:
                            # If JSON fails, try parsing as Python literal (handles single quotes)
                            try:
                                options = ast.literal_eval(options_str)
                            except (ValueError, SyntaxError):
                                # If both fail, start with empty dict
                                options = {}
                        options['no_open'] = "not is_current_user_faculty"
                        node.set('options', json.dumps(options))
                        
                        if node.get('readonly'): continue  # If the readonly status has been explicitly set, skip it
                        node.set('readonly', 'not is_current_user_faculty')
                        # Disable the ability to open the resource from student view
        return arch, view

    @api.onchange('state')
    def _onchange_state_set_dates(self):
        """Set date_submitted/date_completed immediately when state changes in the form."""
        for record in self:
            # When marking submitted in the form, set a submitted timestamp if missing
            if record.state == 'submitted' and not record.date_submitted:
                record.date_submitted = fields.Date.today()
            # When marking complete in the form, set completion and submission timestamps if missing
            if record.state == 'complete':
                if not record.date_completed:
                    record.date_completed = fields.Date.today()
                if not record.date_submitted:
                    record.date_submitted = fields.Date.today()


#endregion - Overrides and records methods

# region - Notifications    
    def _notify_new_submission(self, subject_ids):
        """Creates an activity for each newly added faculty member."""
        # Search for faculty records to get their associated User IDs
        
        new_setting_to_receive_notifications = False
        
        if not new_setting_to_receive_notifications:
            return

        subjects = self.env['op.subject'].browse(list(subject_ids))

        for subject in subjects:
            # Most op.faculty models link to a user via a 'user_id' field
            for faculty in subject.faculty_ids:
                if faculty.emp_id.user_id:
                    self.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=faculty.emp_id.user_id.id,
                        summary=_(f"New submission by {self.student_id.display_name} for {self.display_name}"),
                        note=_(f"A task has been submitted which you may need to review or complete."),
                        date_deadline=fields.Date.add(fields.Date.today(), days=1),  
                        request_partner_id=self.env.user.partner_id.id
                    )

    def _notify_new_faculty_reviewers(self, faculty_ids):
        """Creates an activity for each newly added faculty member."""
        # Search for faculty records to get their associated User IDs
        faculties = self.env['op.faculty'].browse(list(faculty_ids))
        
        for faculty in faculties:
            # Most op.faculty models link to a user via a 'user_id' field
            if faculty.emp_id.user_id:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=faculty.emp_id.user_id.id,
                    summary=_(f"Review Requested by {self.env.user.display_name} for {self.submission_name} ({self.student_id.display_name})"),
                    note=_(f"You have been requested to review the resource submission: {self.submission_name}"),
                    date_deadline=fields.Date.add(fields.Date.today(), days=1),  
                    request_partner_id=self.env.user.partner_id.id
                )

    @api.model
    def send_active_notifications(self):
        """Send notifications for submissions that became active at least 10 minutes ago. Called by cron every 10 minutes."""
        from datetime import timedelta
        mins_before_notification = int(
            self.env['ir.config_parameter'].sudo().get_param('apex.mins_before_notification')
        ) or 10
        threshold_time = fields.Datetime.now() - timedelta(minutes=mins_before_notification)
        submissions = self.search([
            ('submission_active', '=', True),
            ('notification_state', '=', 'not_sent'),
            ('active_datetime', '!=', False),
            ('active_datetime', '<=', threshold_time),
        ])
        for submission in submissions:
            if submission.student_id and submission.student_id.email:
                # Send email notification
                template = self.env.ref('aps_sis.apex_submission_active_email_template', raise_if_not_found=False)
                if template:
                    # Example in email template or chatter
                    view = self.env.ref('aps_sis.view_aps_resource_submission_form_for_students')
                    if view:
                        record_url = f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/web#id={submission.id}&model={self._name}&view_id={view.id}"
                    else:
                        record_url = f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}"
                 
                context = {
                    'question': submission.question,  
                    'submission_name': submission.submission_name,
                    'date_assigned': submission.date_assigned,  
                    'date_due': submission.date_due,
                    'record_url': record_url,
                }
                try:
                    template.with_context(context).send_mail(submission.id, force_send=True)
                    submission.notification_state = 'sent'
                except Exception as e:
                    _logger.error(f"Failed to send email notification for submission {submission.id}: {str(e)}")
                    submission.notification_state = 'failed'

            if submission.notification_state == 'not_sent':
                # Fallback: post message
                try:
                    submission.message_post(
                        body=_("Your task '%s' is now active.") % submission.display_name,
                        partner_ids=[submission.student_id.id],
                        message_type='notification',
                        subtype_xmlid='mail.mt_note'
                    )
                    submission.notification_state = 'posted'
                except Exception as e:
                    _logger.error(f"Failed to post notification message for submission {submission.id}: {str(e)}")
                    submission.notification_state = 'failed'

# endregion - Notifications

# region - Get Data    
    @api.model
    def read_group_points_by_student(self, domain, orderby=False):
        return self.sudo().read_group(
            domain=domain,
            fields=["points:sum"],
            groupby=["student_id"],
            orderby=orderby,
            lazy=True,  # or False, depending on your needs
        )
    
    @api.model
    def read_submission_data(self, domain, fields, orderby=False, limit=False):
        return self.env['aps.resource.submission'].sudo().search_read(
                domain=domain,
                fields=fields,
                order=orderby,
                limit=limit,
            )
    
    @api.model
    def get_progress_data_for_dashboard(self, student_id, period_start_date):
        """
        Get student progress data for dashboard charts.
        Fetches submissions for resources with ' Progress' in the name.
        Returns:
        - line_data: List of progress data points over time by subject
        - bar_data: Current progress percentage by subject
        - pace_data: PACE information from resource notes (including redline dates)
        - subject_colors: Color mapping for subjects
        - exclude_from_average: Subject names to exclude from redline highlight
        - exclude: Subjects to completely exclude from the chart
        """
        from datetime import datetime, timedelta
        import re
        import html as html_lib
        from markupsafe import Markup
        
        # Find all resources with ' Progress' in the name
        progress_resources = self.env['aps.resources'].search([
            ('name', 'ilike', ' Progress')
        ])
        
        if not progress_resources:
            return {
                'line_data': [],
                'bar_data': [],
                'pace_data': {},
                'subject_colors': {},
                'exclude_from_average': [],
                'exclude': [],
            }
        
        # Parse exclude_from_average and exclude from resource notes
        exclude_from_average = []
        exclude = []
        for resource in progress_resources:
            if resource.notes:
                notes_text = resource.notes
                if isinstance(notes_text, Markup) or '<' in str(notes_text):
                    notes_text = str(notes_text)
                    notes_text = re.sub(r'<br\s*/?>', '\n', notes_text, flags=re.IGNORECASE)
                    notes_text = re.sub(r'</(?:p|div|li)>', '\n', notes_text, flags=re.IGNORECASE)
                    notes_text = re.sub(r'<[^>]+>', '', notes_text)
                notes_text = html_lib.unescape(str(notes_text))
                notes_text = notes_text.replace('\xa0', ' ')
                
                match = re.search(r'\bexclude_from_average:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude_from_average:
                            exclude_from_average.append(cleaned_name)
                
                match = re.search(r'\bexclude:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude:
                            exclude.append(cleaned_name)
        
        # Build domain for submissions
        domain = [
            ('resource_id', 'in', progress_resources.ids),
            ('student_id', '=', student_id),
            ('submission_active', '=', True),
            ('state', 'in', ['submitted', 'complete'])
        ]
        
        # Fetch submissions
        submissions = self.search(domain, order='date_submitted asc')
        
        if not submissions:
            return {
                'line_data': [],
                'bar_data': [],
                'pace_data': {},
                'subject_colors': {},
                'exclude_from_average': exclude_from_average,
                'exclude': exclude,
            }
        
        # Get all subjects from submissions
        all_subjects = self.env['op.subject']
        for sub in submissions:
            all_subjects |= sub.subjects
        
        # Filter out excluded subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)
        
        # Get subject colors (with automatic color generation for subjects without categories)
        subject_colors = self.env['op.subject'].get_subject_colors_map(all_subjects.ids)
        
        # Group submissions by subject and build historical data
        subject_data = {}  # {subject_id: [(date, result_percent), ...]}
        current_progress = {}  # {subject_id: {'result_percent': x, 'date': y}}
        pace_info = {}  # {resource_id: {start_date, end_date, redline_start_date, redline_end_date, resource_name}}
        
        for submission in submissions:
            for subject in submission.subjects:
                if subject.name in exclude:
                    continue
                if subject.id not in subject_data:
                    subject_data[subject.id] = []
                
                # Only use submitted or completed dates since we're filtering for those states
                date_to_use = submission.date_submitted or submission.date_completed
                if date_to_use:
                    subject_data[subject.id].append({
                        'date': date_to_use.isoformat(),
                        'result_percent': submission.result_percent,
                        'subject_id': subject.id,
                        'subject_name': subject.name,
                    })
                    
                    # Track latest result for bar chart (most recent submission by date)
                    if subject.id not in current_progress:
                        current_progress[subject.id] = {
                            'result_percent': submission.result_percent,
                            'date': date_to_use
                        }
                    else:
                        # Update if this is a more recent submission
                        if date_to_use > current_progress[subject.id]['date']:
                            current_progress[subject.id] = {
                                'result_percent': submission.result_percent,
                                'date': date_to_use
                            }
                
                # Get PACE/redline dates from resource notes
                # Note: resource.subjects is a Many2many field - one resource can have multiple subjects
                # The PACE dates from the resource's notes field apply to ALL subjects linked to that resource
                # Store PACE info once per resource (not per subject) to avoid duplicate PACE lines
                if submission.resource_id and submission.resource_id.id not in pace_info:
                    pace_dates = submission.resource_id.get_pace_dates()
                    if any([
                        pace_dates['start_date'],
                        pace_dates['end_date'],
                        pace_dates['redline_start_date'],
                        pace_dates['redline_end_date'],
                    ]):
                        pace_info[submission.resource_id.id] = {
                            'start_date': pace_dates['start_date'].isoformat() if pace_dates['start_date'] else False,
                            'end_date': pace_dates['end_date'].isoformat() if pace_dates['end_date'] else False,
                            'redline_start_date': pace_dates['redline_start_date'].isoformat() if pace_dates['redline_start_date'] else False,
                            'redline_end_date': pace_dates['redline_end_date'].isoformat() if pace_dates['redline_end_date'] else False,
                            'resource_name': submission.resource_id.name,
                        }
        
        # Return all data points (sorted by date) - no filtering by period
        # Frontend will handle zooming to the selected period
        all_subject_data = {}
        
        for subject_id, data_points in subject_data.items():
            # Sort by date and remove duplicates
            sorted_points = sorted(data_points, key=lambda x: x['date'])
            all_subject_data[subject_id] = sorted_points
        
        # Build bar data (current progress)
        bar_data = []
        for subject_id, progress_data in current_progress.items():
            subject = all_subjects.filtered(lambda s: s.id == subject_id)
            if subject:
                bar_data.append({
                    'subject_id': subject_id,
                    'subject_name': subject.name,
                    'progress': progress_data['result_percent'],  # Extract result_percent from dict
                    'color': subject_colors.get(subject_id, '#6c757d')  # Fallback to gray
                })
        
        return {
            'line_data': all_subject_data,
            'bar_data': bar_data,
            'pace_data': pace_info,
            'subject_colors': subject_colors,
            'exclude_from_average': exclude_from_average,
            'exclude': exclude,
            'period_start': period_start_date,  # For zoom reference
            'period_end': datetime.now().date().isoformat()  # Today as period end
        }

    @api.model
    def get_student_comparison_data(self):
        """
        Get progress comparison data for all students.
        Returns the most recent progress score for each student in each subject.
        Returns:
        - student_data: List of students with their progress by subject
        - subject_list: List of all subjects
        - subject_colors: Color mapping for subjects
        - pace_average: Average PACE percentage across resources
        - exclude_from_average: List of subject names to exclude from average calculation
        """
        from datetime import datetime
        import re
        from markupsafe import Markup
        
        # Find all resources with ' Progress' in the name
        progress_resources = self.env['aps.resources'].search([
            ('name', 'ilike', ' Progress')
        ])
        
        if not progress_resources:
            return {
                'student_data': [],
                'subject_list': [],
                'subject_colors': {},
                'pace_average': 0,
                'exclude_from_average': []
            }
        
        # Parse exclude_from_average and exclude from resource notes
        exclude_from_average = []
        exclude = []
        for resource in progress_resources:
            if resource.notes:
                # Strip HTML tags if present
                notes_text = resource.notes
                if isinstance(notes_text, Markup) or '<' in str(notes_text):
                    notes_text = str(notes_text)
                    notes_text = re.sub(r'<br\s*/?>', '\n', notes_text, flags=re.IGNORECASE)
                    notes_text = re.sub(r'</(?:p|div|li)>', '\n', notes_text, flags=re.IGNORECASE)
                    notes_text = re.sub(r'<[^>]+>', '', notes_text)
                # Decode HTML entities (e.g., &nbsp; -> space)
                import html
                notes_text = html.unescape(str(notes_text))
                notes_text = notes_text.replace('\xa0', ' ')
                
                match = re.search(r'\bexclude_from_average:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude_from_average:
                            exclude_from_average.append(cleaned_name)
                
                match = re.search(r'\bexclude:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude:
                            exclude.append(cleaned_name)
        
        # Build domain for submissions
        domain = [
            ('resource_id', 'in', progress_resources.ids),
            ('submission_active', '=', True),
            ('state', 'in', ['submitted', 'complete'])
        ]
        
        # Fetch submissions
        submissions = self.search(domain, order='date_submitted asc')
        
        if not submissions:
            return {
                'student_data': [],
                'subject_list': [],
                'subject_colors': {},
                'pace_average': 0
            }
        
        # Get all subjects from submissions
        all_subjects = self.env['op.subject']
        for sub in submissions:
            all_subjects |= sub.subjects
        
        # Filter out excluded subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)

        # Restrict to subjects students are currently enrolled in
        student_enrolled_subjects = {}  # {partner_id: set(enrolled_subject_ids)}
        all_enrolled_subject_ids = set()
        partner_ids = list({sub.student_id.id for sub in submissions if sub.student_id})
        student_records = self.env['op.student'].search([('partner_id', 'in', partner_ids)])
        for student_record in student_records:
            running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
            enrolled_ids = set(running_courses.mapped('subject_ids').ids)
            student_enrolled_subjects[student_record.partner_id.id] = enrolled_ids
            all_enrolled_subject_ids.update(enrolled_ids)
        if all_enrolled_subject_ids:
            all_subjects = all_subjects.filtered(lambda s: s.id in all_enrolled_subject_ids)

        # Get subject colors
        subject_colors = self.env['op.subject'].get_subject_colors_map(all_subjects.ids)
        
        # Build student progress data: {student_id: {subject_id: {'result': x, 'date': y}}}
        student_progress = {}
        pace_values = []
        redline_values = []
        processed_resources_for_pace = set()
        all_subject_ids_set = set(all_subjects.ids)  # enrolled + not excluded

        for submission in submissions:
            student_id = submission.student_id.id
            if not student_id:
                continue
                
            if student_id not in student_progress:
                student_progress[student_id] = {
                    'name': submission.student_id.name,
                    'subjects': {}
                }
            
            for subject in submission.subjects:
                if subject.id not in all_subject_ids_set:
                    continue
                student_enrolled = student_enrolled_subjects.get(student_id)
                if student_enrolled is not None and subject.id not in student_enrolled:
                    continue
                date_to_use = submission.date_submitted or submission.date_completed
                if not date_to_use:
                    continue
                
                # Track latest result for each subject (most recent submission)
                if subject.id not in student_progress[student_id]['subjects']:
                    student_progress[student_id]['subjects'][subject.id] = {
                        'result_percent': submission.result_percent,
                        'date': date_to_use
                    }
                else:
                    # Update if this is a more recent submission
                    if date_to_use > student_progress[student_id]['subjects'][subject.id]['date']:
                        student_progress[student_id]['subjects'][subject.id] = {
                            'result_percent': submission.result_percent,
                            'date': date_to_use
                        }
            
            # Calculate PACE and redline for averaging (process each resource only once)
            if submission.resource_id and submission.resource_id.id not in processed_resources_for_pace:
                processed_resources_for_pace.add(submission.resource_id.id)
                pace_dates = submission.resource_id.get_pace_dates()
                today = datetime.now().date()
                
                if pace_dates['start_date'] and pace_dates['end_date']:
                    start_date = pace_dates['start_date']
                    end_date = pace_dates['end_date']
                    if start_date <= today <= end_date:
                        total_days = (end_date - start_date).days
                        if total_days > 0:
                            days_from_start = (today - start_date).days
                            pace_percent = (days_from_start / total_days) * 100
                            pace_values.append(min(100, max(0, pace_percent)))
                
                if pace_dates['redline_start_date'] and pace_dates['redline_end_date']:
                    rl_start = pace_dates['redline_start_date']
                    rl_end = pace_dates['redline_end_date']
                    if rl_start <= today <= rl_end:
                        total_days = (rl_end - rl_start).days
                        if total_days > 0:
                            days_from_start = (today - rl_start).days
                            redline_percent = (days_from_start / total_days) * 100
                            redline_values.append(min(100, max(0, redline_percent)))
        
        # Format for frontend
        student_list = []
        for student_id, student_info in student_progress.items():
            student_data = {
                'student_id': student_id,
                'student_name': student_info['name'],
                'progress_by_subject': {}
            }
            for subject_id, progress_info in student_info['subjects'].items():
                student_data['progress_by_subject'][subject_id] = progress_info['result_percent']
            student_list.append(student_data)
        
        # Calculate average PACE and redline
        pace_average = sum(pace_values) / len(pace_values) if pace_values else 0
        redline_average = sum(redline_values) / len(redline_values) if redline_values else 0
        
        # Build subject list
        subject_list = []
        for subject in all_subjects:
            subject_list.append({
                'id': subject.id,
                'name': subject.name,
                'color': subject_colors.get(subject.id, '#6c757d')
            })
        
        return {
            'student_data': student_list,
            'subject_list': subject_list,
            'subject_colors': subject_colors,
            'pace_average': pace_average,
            'redline_average': redline_average,
            'exclude_from_average': exclude_from_average,
            'exclude': exclude,
        }

    @api.model
    def get_current_user_is_teacher(self):
        """
        Check if the current user is a teacher.
        Returns True if the user is in the group_aps_teacher group.
        """
        teacher_group = self.env.ref('aps_sis.group_aps_teacher', raise_if_not_found=False)
        if not teacher_group:
            return False
        
        current_user = self.env.user
        return teacher_group in current_user.groups_id
# endregion - Get Data