import json
import ast

from odoo import models, fields, api, _
from .model import sentinel_zero, alpha_to_float
import logging
from lxml import etree

_logger = logging.getLogger(__name__)


class APSResourceSubmissionOverrides(models.Model):
    _inherit = 'aps.resource.submission'

# region - Overrides and records methods

    def write(self, vals):
        
        # Sync alpha fields → numeric fields when only the alpha field is provided
        # (e.g. when saved programmatically without the onchange firing).
        # Do this before the auto_score check so that 'score in vals' is correct.
        if 'score_alpha' in vals and 'score' not in vals:
            vals['score'] = alpha_to_float(vals['score_alpha'])
        if 'out_of_marks_alpha' in vals and 'out_of_marks' not in vals:
            vals['out_of_marks'] = alpha_to_float(vals['out_of_marks_alpha'])

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

            # Update progress submissions derived from Progress-Quiz tasks
            quiz_tasks = self.mapped('task_id').filtered(
                lambda t: t.resource_id.tag_ids.filtered(
                    lambda tag: tag.name == 'Progress Quiz'
                )
            )
            if quiz_tasks:
                quiz_tasks._update_progress_from_quizzes()

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

        # Update progress submissions derived from Progress-Quiz tasks
        quiz_tasks = tasks.filtered(
            lambda t: t.resource_id.tag_ids.filtered(
                lambda tag: tag.name == 'Progress Quiz'
            )
        )
        if quiz_tasks:
            quiz_tasks._update_progress_from_quizzes()
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
