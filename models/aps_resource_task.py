from datetime import datetime
import json

from odoo import models, fields, api

class APSResourceTask(models.Model):
    _name = 'aps.resource.task'
    _description = 'APEX Task'
    
    _sql_constraints = [
        ('unique_resource_student', 'UNIQUE(resource_id, student_id)', 'This student is already assigned to this resource.'),
    ]

    display_name = fields.Char(compute='_compute_display_name', store=True)
    resource_id = fields.Many2one('aps.resources', string='Resource', required=True)
    student_id = fields.Many2one('res.partner', string='Student', domain=[('is_student', '=', True)], required=True)
    submission_count = fields.Integer(
        string='Attempts', 
        compute='_compute_submission_stats', store=True,
        help='The number of submissions made by the student for this task.')
    last_result = fields.Float(string='Last Result%', compute='_compute_submission_stats', store=True, default=None)
    avg_result = fields.Float(string='Average Result%', compute='_compute_submission_stats', store=True, default=None)
    weighted_result = fields.Float(string='Weighted Result%', compute='_compute_submission_stats', store=True, default=None)
    best_result = fields.Float(string='Best Result%', compute='_compute_submission_stats', store=True, default=None)
    state = fields.Selection([
        ('created', 'Created'),
        ('assigned', 'Assigned'),
        ('reassigned', 'Reassigned'),
        ('due', 'Due'),
        ('submitted', 'Submitted'),
        ('overdue', 'Overdue'),
        ('complete', 'Complete'),
        ('late', 'Late'),
    ], string='State', default='created',
        decoration_success="state == 'complete'",
        decoration_warning="state == 'created' or state == 'late'",
        decoration_info="state in ['assigned', 'due', 'reassigned', 'submitted']",
        decoration_danger="state == 'overdue'")
    date_assigned = fields.Date(string='Date Assigned', compute='_compute_date_assigned', store=True)
    date_due = fields.Date(string='Due Date', compute='_compute_date_due', store=True)
    latest_submission_text = fields.Char(
        compute='_compute_latest_submission_data',
        store=True,
        string='Recent Submissions',
        help='The latest submission for this task based on the assignment date.'
    )
    submission_ids = fields.One2many('aps.resource.submission', 'task_id', string='Submissions')
    type_icon = fields.Image(
        string='Type Icon',
        compute="_compute_type_icon",
        store=True
    )


    @api.depends('resource_id.type_id', 'resource_id.type_id.icon')
    def _compute_type_icon(self):
        # This is needed because without it the icon is never cached properly. 
        # That means there is a lot of annoying downloads on every page refresh.
        # It is duplicated in other models as well.
        for record in self:
            record.type_icon = record.resource_id.type_id.icon if record.resource_id.type_id else False

    @api.depends('student_id', 'resource_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.student_id and rec.resource_id:
                rec.display_name = f"{rec.student_id.name} - {rec.resource_id.name}"
            elif rec.student_id:
                rec.display_name = rec.student_id.name
            elif rec.resource_id:
                rec.display_name = rec.resource_id.name
            else:
                rec.display_name = "New Task"

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to ensure proper record creation"""
        records = super().create(vals_list)
        return records

    def write(self, vals):
        """Override write to ensure proper updates"""
        result = super().write(vals)
        return result

    def _update_state_from_submissions(self):
        """Update task state based on submission states."""
        for task in self:
            if not task.submission_ids:
                # No submissions, keep current state
                continue
            
            # State priority: complete > submitted > assigned
            state_priority = {'assigned': 1, 'submitted': 2, 'complete': 3}
            
            # Find the highest priority state among all submissions
            submission_states = task.submission_ids.mapped('state')
            priorities = [state_priority.get(state, 0) for state in submission_states]
            min_priority = min(priorities) if priorities else 0
            
            # Map back to state
            # priority_to_state = {1: 'assigned', 2: 'reassigned', 3: 'due', 4: 'submitted', 5: 'overdue', 6: 'complete'}
            priority_to_state = {1: 'assigned', 1: 'submitted', 3: 'complete'}
            new_state = priority_to_state.get(min_priority, task.state)
            
            # Update state if different
            if task.state != new_state:
                task.state = new_state

    @api.depends('submission_ids', 'submission_ids.date_assigned', 'submission_ids.create_date', 'submission_ids.state', 'submission_ids.score', 'submission_ids.out_of_marks')
    def _compute_submission_stats(self):
        for rec in self:
            submissions = rec.submission_ids.filtered(lambda a: a.state in ['submitted', 'complete'] and a.score != -0.01).sorted(lambda s: s.date_assigned or s.create_date)
            rec.submission_count = len(submissions)
            if submissions:
                scores = submissions.mapped('result_percent')
                rec.last_result = scores[-1] if scores else False
                rec.avg_result = round(sum(scores) / len(scores), 2) if scores else False
                rec.best_result = max(scores) if scores else False
                
                # Calculate weighted result using last 10 submissions
                # Most recent gets highest weight (n, n-1, n-2, ..., 1)
                last_submissions = submissions[-10:]  # Get last 10 submissions
                if last_submissions:
                    weighted_sum = 0.0
                    weight_total = 0
                    num_submissions = len(last_submissions)
                    
                    for idx, submission in enumerate(last_submissions):
                        weight = idx + 1  # Weight: 1 for oldest, 2, 3, ..., n for most recent
                        weighted_sum += submission.result_percent * weight
                        weight_total += weight
                    
                    rec.weighted_result = round(weighted_sum / weight_total, 2) if weight_total > 0 else False
                else:
                    rec.weighted_result = False
            else:
                rec.last_result = False
                rec.avg_result = False
                rec.weighted_result = False
                rec.best_result = False

    @api.depends('submission_ids.date_due', 'submission_ids.state')
    def _compute_date_due(self):
        for rec in self:
            # Get the earliest submission date for assigned tasks. If all tasks are complete, keep date_due as is.
            submitted_dates = rec.submission_ids.filtered(lambda s: s.state=='assigned' and s.date_due).mapped('date_due')
            if submitted_dates:
                rec.date_due = min(submitted_dates)

    @api.depends('submission_ids.date_assigned', 'submission_ids.state')
    def _compute_date_assigned(self):
        for rec in self:
            # Get the earliest submission assignment date
            assigned_dates = rec.submission_ids.filtered(lambda s: s.state=='assigned' and s.date_assigned).mapped('date_assigned')
            if assigned_dates:
                rec.date_assigned = min(assigned_dates)

    @api.depends('submission_ids', 'submission_ids.date_assigned', 'submission_ids.create_date', 'submission_ids.state', 'submission_ids.score', 'submission_ids.out_of_marks')
    def _compute_latest_submission_data(self):
        for rec in self:
            # Skip computation for unsaved records to avoid interference
            if not rec.id:
                rec.latest_submission_text = json.dumps({'pills': []})
                continue
                
            # Get last 3 submissions, most recent first
            # The most recent are first because they are the ones that the user is most likely to want to see.
            # This looks weird though when there are a lot of submission created for far distant dates.
            submissions = rec.submission_ids.filtered(lambda s: s.submission_active).sorted(lambda s: s.date_assigned or s.create_date or datetime.min, reverse=True)[:3]
            
            pills = []
            state_colors = {
                'complete': 'success',
                'submitted': 'info',
                'assigned': 'secondary',
                'incomplete': 'secondary',
            }
            
            for sub in submissions:
                # Skip unsaved submissions
                if not sub.id:
                    continue
                    
                color = "border-0 bg-" + state_colors.get(sub.state, 'secondary') 
                if sub.state=='assigned' and sub.due_status == 'late':
                    color = "border-0 bg-danger"
                if sub.date_assigned:
                    date_str = f"{sub.date_assigned.day} {sub.date_assigned.strftime('%b %y')}"
                else:
                    date_str = 'No date'
                score_str = ""
                if sub.score != -0.01 and sub.out_of_marks != -0.01:
                    # Format numbers to show decimals only when needed
                    score_fmt = f"{sub.score:g}" if sub.score == int(sub.score) else f"{sub.score:.1f}"
                    marks_fmt = f"{sub.out_of_marks:g}" if sub.out_of_marks == int(sub.out_of_marks) else f"{sub.out_of_marks:.1f}"
                    score_str = f"{score_fmt}/{marks_fmt}"
                text = f"{date_str}: {score_str}" if score_str else date_str
                pills.append({
                    'type': 'submission',
                    'id': int(sub.id),
                    'res_model': 'aps.resource.submission',
                    'color': color,
                    'text': text,
                })
            
            # Add task pill - only if record is saved
            pills.append({
                'type': 'task',
                'id': int(rec.id),
                'res_model': rec._name,
                'color': 'border border-dark',
                'text': f'All ({len(rec.submission_ids)})',
            })
            
            rec.latest_submission_text = json.dumps({'pills': pills})

    @api.model
    def get_progress_data(self, task_id):
        """
        Returns progress data for the image_result widget.
        Returns weighted_result and up to 10 most recent submission result_percent values.
        """
        task = self.browse(task_id)
        if not task.exists():
            return {
                'weighted_result': 0,
                'submission_results': [],
            }
        
        # Get the 10 most recent submissions ordered by date_assigned desc
        # Exclude submissions with negative result_percent or score of -0.01
        submissions = task.submission_ids.filtered(
            lambda s: (s.result_percent or 0) >= 0 and s.score != -0.01
        ).sorted(key=lambda s: s.date_assigned or '', reverse=True)[:10]
        
        return {
            'weighted_result': task.weighted_result or 0,
            'submission_results': [s.result_percent or 0 for s in submissions],
        }

    def action_create_submission(self):
        self.ensure_one()
        faculty = self.env['op.faculty'].search([('user_id', '=', self.env.user.id)], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Submission',
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'view_id': self.env.ref('aps_sis.view_aps_resource_submission_form').id,
            'context': {
                'default_task_id': self.id,
                'default_resource_id': self.resource_id.id,
                'default_assigned_by': faculty.id if faculty else False,
                'default_date_assigned': fields.Date.today(),
                'form_view_initial_mode': 'edit',
            },
            'target': 'current',
        }