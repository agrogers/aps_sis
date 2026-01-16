from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)
sentinel_zero = -0.01

class APSResourceSubmission(models.Model):
    _name = 'aps.resource.submission'
    _description = 'Resource Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    display_name = fields.Char(compute='_compute_display_name', store=True)
    task_id = fields.Many2one('aps.resource.task', string='Task', required=True)
    resource_id = fields.Many2one('aps.resources', string='Resource', related='task_id.resource_id')
    subjects = fields.Many2many('op.subject', string='Subjects', related='resource_id.subjects')
    student_id = fields.Many2one('res.partner', string='Student', related='task_id.student_id')
    assigned_by = fields.Many2one('op.faculty', string='Assigned By', default=lambda self: self._default_assigned_by())
    submission_label = fields.Char(
        string='Label',
        help='Identifier for grouping submissions, e.g., S1 Exam, Exam Prep, Homework .'
    )
    state = fields.Selection([
        ('assigned', 'Assigned'),
        ('submitted', 'Submitted'),
        ('complete', 'Finalised'),  # Leave the underlying value as 'complete' for easier sync with task state 
        ], string='State', default='assigned', 
        tracking=True,
        required=True)
    date_assigned = fields.Datetime(
        string='Date Assigned',
        default=fields.Datetime.now)
    date_submitted = fields.Datetime(
        string='Date Submitted', 
        help='The date when the submission was made by the student.',
        tracking=True)
    date_completed = fields.Datetime(
        string='Date Finalised', 
        help='The date when the submission was marked as finalised by the teacher. Submissions may be rejected.',
        tracking=True)
    date_due = fields.Datetime(string='Due Date', tracking=True)
    score = fields.Float(string='Score', digits=(16, 1), tracking=True, default=sentinel_zero)
    out_of_marks = fields.Float(string='Out of Marks', related='resource_id.marks', store=True, readonly=True)
    result_percent = fields.Integer(string='Result %', compute='_compute_result_percent', store=True, tracking=True)
    due_status = fields.Selection([
        ('late', 'Late'),
        ('on-time', 'On Time'),
        ('early', 'Early'),
    ], string='Due Status', compute='_compute_due_status', store=True)
    actual_duration = fields.Float(string='Actual Duration (hours)', digits=(16, 1))
    feedback = fields.Html(string='Feedback')
    answer = fields.Html(string='Answer')
    has_feedback = fields.Boolean(string='Has Feedback', compute='_compute_has_feedback', store=True)
    has_answer = fields.Boolean(string='Has Answer', compute='_compute_has_answer', store=True)
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

    @api.depends('feedback')
    def _compute_has_feedback(self):
        for record in self:
            record.has_feedback = bool(record.feedback and record.feedback.strip())

    @api.depends('answer')
    def _compute_has_answer(self):
        for record in self:
            record.has_answer = bool(record.answer and record.answer.strip())

    @api.depends('date_assigned')
    def _compute_date_due(self):
        for record in self:
            if record.date_assigned:
                # Set due date to 7 days after assignment
                record.date_due = fields.Datetime.add(record.date_assigned, days=7)
            else:
                record.date_due = False

    @api.depends('date_due', 'date_submitted', 'date_completed', 'state')
    def _compute_due_status(self):
        
        now = fields.Datetime.now()
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
                due_date_minus_1 = fields.Date.add(record.date_due.date(), days=-1)

                if record.date_due.date() and compare_date.date() < due_date_minus_1:
                    record.due_status = 'early'
                elif compare_date.date() <= record.date_due.date():
                    record.due_status = 'on-time'
                else:
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
        
    @api.depends('task_id.student_id.name', 'resource_id.display_name', 'submission_label')
    def _compute_display_name(self):
        for record in self:
            student_name = record.task_id.student_id.name if record.task_id.student_id else 'Unknown Student'
            resource_name = record.resource_id.display_name if record.resource_id else 'Unknown Resource'
            label = f">{record.submission_label} " if record.submission_label else ""
            record.display_name = f"{resource_name}{label}({student_name})"

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

    def action_mark_complete(self):
        faculty = self._get_current_faculty()
        if not faculty:
            raise UserError("Only faculty members can mark submissions as complete.")
        
        completion_date = fields.Date.today()
        vals = {
            'state': 'complete',
            'date_completed': completion_date,
            'reviewed_by': [(4, faculty.id)] if faculty else [],
        }
        
        # If no submission date is set, set it to the completion date
        if not self.date_submitted:
            vals['date_submitted'] = completion_date
        
        self.write(vals)

    def action_mark_submitted(self):
        self.write({
            'state': 'submitted',
            'date_submitted': fields.Date.today(),
        })

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

    def write(self, vals):
        # Handle automatic date setting based on state changes
        if 'state' in vals:
            for record in self:
                # If changing to submitted and no submission date, set it to today
                if vals['state'] == 'submitted' and not record.date_submitted and 'date_submitted' not in vals:
                    vals['date_submitted'] = fields.Datetime.now()
                
                # If changing to complete and no completion date, set it to today
                elif vals['state'] == 'complete' and not record.date_completed and 'date_completed' not in vals:
                    vals['date_completed'] = fields.Datetime.now()
                    # Also ensure submission date is set if missing
                    if not record.date_submitted and 'date_submitted' not in vals:
                        vals['date_submitted'] = fields.Datetime.now()
        
        result = super().write(vals)
        
        # Update task state when submission state changes
        if 'state' in vals:
            # Get unique tasks from the submissions
            tasks = self.mapped('task_id')
            if tasks:
                tasks._update_state_from_submissions()
        return result

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