import json
import ast
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
    subjects = fields.Many2many('op.subject', string='Subjects', related='resource_id.subjects')
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
    out_of_marks = fields.Float(string='Out of Marks', related='resource_id.marks', store=True, readonly=True)
    result_percent = fields.Integer(string='Result %', compute='_compute_result_percent', store=True, tracking=True)
    due_status = fields.Selection([
        ('late', 'Late'),
        ('on-time', 'On Time'),
        ('early', 'Early'),
    ], string='Due Status', compute='_compute_due_status', store=True)
    days_till_due = fields.Integer(compute='_compute_days_till_due')  # creates a class used to highlight records when they are nearing their due date
    actual_duration = fields.Float(string='Actual Duration (hours)', digits=(16, 1))
    feedback = fields.Html(string='Feedback')
    answer = fields.Html(string='Answer')
    has_question = fields.Selection(string='Has Question', related='resource_id.has_question', readonly=True, store=True)
    has_feedback = fields.Boolean(string='Has Feedback', compute='_compute_has_feedback', store=True)
    has_answer = fields.Selection(string='Has Answer', related='resource_id.has_answer', readonly=True, store=True)
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
    model_answer = fields.Html(
        string='Model Answer',
        related='resource_id.answer',
        readonly=True,
        help='The model answer from the associated resource for comparison.'
    )
    question = fields.Html(
        string='Question',
        related='resource_id.question',
        readonly=True,
        help='The question from the associated resource.'
    )
    supporting_resources_buttons = fields.Json(
        string='Links',
        related='resource_id.supporting_resources_buttons',
        help='Links to resources associated with this submission (e.g., main resource and supporting resources).'
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
    submission_active = fields.Boolean(string='Active', compute="_compute_submission_active", default=True, store=True)

# region - Computed Fields

    @api.depends('resource_id.type_id', 'resource_id.type_id.icon')
    def _compute_type_icon(self):
        # This is needed because without it the icon is never cached properly. 
        # That means there is a lot of annoying downloads on every page refresh.
        # It is duplicated in other models as well.
        for record in self:
            record.type_icon = record.resource_id.type_id.icon if record.resource_id.type_id else False

    @api.depends('resource_id.subjects', 'resource_id.subjects.icon')
    def _compute_subject_icons(self):
        for record in self:
            if record.resource_id and record.resource_id.subjects:
                first = record.resource_id.subjects[:1]
                record.subject_icons = first.icon if first else False
            else:
                record.subject_icons = False

    @api.depends('date_due')
    def _compute_days_till_due(self):
        today = fields.Date.today()
        for record in self:
            if not record.date_due or record.state != 'assigned':
                record.days_till_due = 999  # Arbitrary large number for no due date, essentially "not due"
                continue
            
            record.days_till_due = (record.date_due - today).days

    @api.depends('date_assigned')
    def _compute_submission_active(self):
        for record in self:
            if record.date_assigned:
                if (record.date_assigned <= fields.Date.today()) != record.submission_active:
                    record.submission_active = (record.date_assigned <= fields.Date.today())

    @api.model
    def recompute_submission_active_status(self):
        """Recompute active status for all submissions. Called by cron job daily."""
        submissions = self.search([])
        submissions._compute_submission_active()

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
            # student_name = record.task_id.student_id.name if record.task_id.student_id else 'Unknown Student'
            # resource_name = record.resource_id.display_name if record.resource_id else 'Unknown Resource'

            # label = f">{record.submission_label} " if record.submission_label else ""
            record.display_name = f"{record.submission_name} ({record.date_assigned})"

# endregion - Computed Fields

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        """
        Intercepts the view loading process. If a student is logged in,
        force the use of student-specific views regardless of what was requested.
        """
        
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
                    
                    if node.get('name') not in  ['answer','score','review_requested_by']:
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
        
        for record in self:
            new_submission = record.copy({
                'assigned_by': faculty.id if faculty else False,
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

# endregion - Action Methods

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
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

# region - Write Override

    def write(self, vals):
        
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
        
        old_faculty_map = {rec.id: set(rec.review_requested_by.ids) for rec in self}

        result = super().write(vals)
        
        # Update task state when submission state changes
        if 'state' in vals:
            # Get unique tasks from the submissions
            tasks = self.mapped('task_id')
            if tasks:
                tasks._update_state_from_submissions()


        if 'review_requested_by' in vals:
            for record in self:
                old_ids = old_faculty_map.get(record.id, set())
                new_ids = set(record.review_requested_by.ids)
                
                # Find only the IDs that are in the new set but weren't in the old set
                added_ids = new_ids - old_ids
                
                if added_ids:
                    record._notify_new_faculty_reviewers(added_ids)
        return result


# region - Activity Notifications    
    def _notify_new_submission(self, subject_ids):
        """Creates an activity for each newly added faculty member."""
        # Search for faculty records to get their associated User IDs

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
                    summary=_(f"Review Requested by {self.env.user.display_name} for {self.display_name} ({self.student_id.display_name})"),
                    note=_(f"You have been requested to review the resource submission: {self.display_name}"),
                    date_deadline=fields.Date.add(fields.Date.today(), days=1),  
                    request_partner_id=self.env.user.partner_id.id
                )


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'state' not in vals:
                vals['state'] = 'assigned'
        submissions = super().create(vals_list)
        # Update task states for newly created submissions
        tasks = submissions.mapped('task_id')
        if tasks:
            tasks._update_state_from_submissions()
        # Log creation for debugging
        for submission in submissions:
            _logger.info(f"Created submission {submission.id} for task {submission.task_id.id}")
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
        default['assigned_by'] = self._get_current_faculty().id
        default['score'] = sentinel_zero
        # date_due will be recomputed based on the new date_assigned
        return super().copy(default)
    
