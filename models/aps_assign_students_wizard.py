from odoo import models, fields, api
from .aps_assign_mixin import APSAssignMixin

class APSAssignStudentsWizardLine(models.TransientModel):
    _name = 'aps.assign.students.wizard.line'
    _description = 'APEX Assign Students Wizard Line'

    sequence = fields.Integer(string='Sequence', default=10)
    wizard_id = fields.Many2one('aps.assign.students.wizard', required=True)
    type_icon = fields.Binary(related='resource_id.type_icon', string='Icon', readonly=True)    
    resource_id = fields.Many2one('aps.resources', string='Resource', required=True)
    display_name = fields.Char(string='Resource', compute='_compute_display_name', store=False)
    description = fields.Text(string='Description', related='resource_id.description', readonly=True)
    has_question = fields.Selection(related='resource_id.has_question', readonly=True)
    has_answer = fields.Selection(related='resource_id.has_answer', readonly=True)
    points_scale = fields.Integer(related='resource_id.points_scale', readonly=True)
    supporting_resources_buttons = fields.Json(related='resource_id.supporting_resources_buttons', string='Resource Links', readonly=True)    
    selected = fields.Boolean(string='Assign', default=True)
    parent_custom_name_data = fields.Json(string='Custom Names', related='resource_id.parent_custom_name_data', readonly=True, required=False)
    parent_resource_id = fields.Many2one('aps.resources', string='Resource', required=False)
    submission_order = fields.Integer(string='Submission Order')

    @api.depends('resource_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.resource_id.display_name if rec.resource_id else ''

class APSAssignStudentsWizard(APSAssignMixin, models.TransientModel):
    _name = 'aps.assign.students.wizard'
    _description = 'APEXAssign Students to Resource Wizard'

    resource_id = fields.Many2one('aps.resources', string='Resource', required=True, readonly=True)
    date_assigned = fields.Date(string='Date Assigned', required=True, default=fields.Date.today)
    time_assigned = fields.Float(
        string='Time Assigned',
        help='The specific time when this submission should become active as a decimal (e.g., 14.5 = 14:30). If not set, the submission becomes active at midnight on the assigned date.')
    date_due = fields.Date(string='Due Date', required=True)
    student_ids = fields.Many2many('res.partner', string='Students', domain=[('is_student', '=', True)], required=True)
    assigned_by = fields.Many2one('op.faculty', string='Assigned By', default=lambda self: self._default_assigned_by())
    custom_submission_name = fields.Char(string='Custom Submission Name')
    warning_message = fields.Char(string='Warning', compute='_compute_warning_message', store=False)
    submission_label = fields.Char(string='Submission Label', help='Identifier for grouping submissions, e.g., S1 Exam, Exam Prep, Homework')
    recurring_days = fields.Integer(
        string='Recurring (Days)',
        default=0,
        help='Days between recurring assignments. Set to 0 to disable recurring scheduling.',
    )
    affected_resource_line_ids = fields.One2many('aps.assign.students.wizard.line', 'wizard_id', string='Affected Resources', order='sequence')
    
    allow_subject_editing = fields.Boolean(
        string='Allow Subject Editing',
        store=True
    )

    def _assign_students_field_name(self):
        return 'student_ids'

    def _assign_resources_field_name(self):
        return 'affected_resource_line_ids'

    use_question = fields.Boolean(string='Use Question', default=False, help='Enable to include a question for this assignment.')
    question = fields.Html(string='Question')

    use_model_answer = fields.Boolean(string='Use Model Answer')
    # model_answer is used only for display purposes in the wizard and is not stored, since it is always derived from the resource. This allows us to show the model answer for the resource even if the user chooses to use a custom question/answer for this assignment.
    model_answer = fields.Html(string='Answer', help='Model answer for the resource question.')

    use_default_answer = fields.Boolean(
        string='Use Default Answer', 
        default=False, 
        help='Resources can include a default answer to a question. This is helpful if you wish to provide a template for students to fill in.',
        required=False,
    )
    default_answer = fields.Html(string='Default Answer', help='Default answer template for the resource question.')    

    subjects = fields.Many2many('op.subject', string='Subjects')
    points_scale = fields.Integer(string='Points Scale', default=1, help='Scales the points allocated to the submission. This is useful for resources that are used in different contexts with different grading schemes.')
    notify_student = fields.Boolean(string='Notify Student', default=True, help='If enabled, students will receive a notification when they are assigned to the resource.')
    
    use_notes = fields.Boolean(string='Use Notes', default=False, help='Enable to include notes for this assignment.')
    notes = fields.Html(string='Notes', help='Notes for the resource.')

    can_assign = fields.Boolean(string='Can Assign', compute='_compute_can_assign', store=False) # Helper field to enable/disable assign button based on whether any students and any resources are selected

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        resource = self.env['aps.resources'].browse(res.get('resource_id'))
        # res['custom_submission_name'] = resource.display_name
        label = resource.display_name
        if res.get('date_assigned'):
            label += f' ({res["date_assigned"]})'
        res['submission_label'] = label        

        if res.get('date_assigned'):
            from datetime import timedelta
            res['date_due'] = res['date_assigned'] + self.env['aps.resources']._default_assignment_duration()

        # Copy any matching simple field values from the resource to the wizard defaults
        if resource and resource.exists():
            # Fields we should not copy or that are handled separately
            skip_fields = {
                'id', 'display_name', 'name', 'affected_resource_line_ids',
                'student_ids', 'submission_label', 'submission_order', 'assigned_by',
                'resource_id', 'warning_message', 'can_assign', 'parent_question', 'parent_answer', 'time_assigned',
                'has_notes', 'parent_notes',
            }
            for fname in self._fields:
                if fname in skip_fields:
                    continue
                # respect requested fields_list if provided
                if fields_list and fname not in fields_list:
                    continue
                # only copy if the resource model has the field
                if fname == 'has_answer':
                    # has_answer is a bit special because we want to set it to True if there is either an answer or a default answer, since the resource can have either or both and we want to indicate that in the wizard. This allows the user to see that there is an answer associated with the resource even if they are choosing to use a custom question and answer for this assignment.
                    res['use_model_answer'] = (resource.has_answer != 'no')
                    continue
                    
                if fname == 'has_question':
                    # has_question is a bit special because we want to set it to True if there is either a question or a default question, since the resource can have either or both and we want to indicate that in the wizard. This allows the user to see that there is a question associated with the resource even if they are choosing to use a custom question and answer for this assignment.
                    res['use_question'] = (resource.has_question != 'no')
                    continue

                if fname == 'has_notes':
                    # has_notes is a bit special because we want to set it to True if there are notes or a default notes, since the resource can have either or both and we want to indicate that in the wizard. This allows the user to see that there are notes associated with the resource even if they are choosing to use custom notes for this assignment.
                    res['use_notes'] = (resource.has_notes != 'no')
                    continue                    

                if fname == 'has_default_answer':
                    # has_default_answer is a bit special because we want to set it to True if there is a default answer, since the resource can have either or both and we want to indicate that in the wizard. This allows the user to see that there is a default answer associated with the resource even if they are choosing to use a custom question and answer for this assignment.
                    res['use_default_answer'] = (resource.has_default_answer != 'no')
                    continue                    

                if fname in resource._fields:
                    try:
                        val = resource[fname]
                        # store into default dict
                        res[fname] = val
                    except Exception:
                        # guard against unexpected read/compute errors
                        continue

            # Set has_notes to 'yes' if the resource has notes (either directly or via parent)
            resource_notes = resource.notes
            if not resource_notes and resource.has_notes == 'use_parent' and resource.primary_parent_id:
                resource_notes = resource.primary_parent_id.notes
            res['use_notes'] = bool(resource_notes)
            res['notes'] = resource_notes if resource_notes else False

    
        return res

    @api.onchange('has_question')
    def _onchange_has_question(self):
        if self.resource_id:
            if self.has_question == 'no':
                self.question = False
            elif self.has_question == 'yes':
                self.question = self.resource_id.question if self.resource_id.question else False
            elif self.has_question == 'use_parent':
                self.question = self.resource_id._question_from_parent()

    @api.onchange('date_assigned')
    def _onchange_date_due(self):
        if self.date_assigned:
            from datetime import timedelta
            self.date_due = self.date_assigned + self.env['aps.resources']._default_assignment_duration()

    @api.onchange('custom_submission_name', 'date_assigned')
    def _onchange_custom_submission_name(self):
        base = self.custom_submission_name or self.resource_id.display_name or ''
        if self.date_assigned:
            self.submission_label = f'{base} ({self.date_assigned})'
        else:
            self.submission_label = base

    @api.depends('student_ids', 'affected_resource_line_ids')
    def _compute_can_assign(self):
        for rec in self:
            has_students = bool(rec.student_ids)
            has_selected_resources = any(line.selected for line in rec.affected_resource_line_ids)
            rec.can_assign = has_students and has_selected_resources

    @api.depends('custom_submission_name', 'resource_id', 'affected_resource_line_ids')
    def _compute_warning_message(self):
        for rec in self:
            if rec.custom_submission_name and rec.custom_submission_name != rec.resource_id.display_name:
                selected_resources_count = len(rec.affected_resource_line_ids.filtered(lambda l: l.selected))
                rec.warning_message = f'This applies to all {selected_resources_count} selected resources.'
            else:
                rec.warning_message = False

    @api.onchange('subjects')
    def _onchange_subjects(self):
        self._onchange_subjects_shared()

    @api.onchange('resource_id')
    def _onchange_resource_id(self):
        self._onchange_resource_id_shared()

    def _default_assigned_by(self):
        """Get the faculty record for the current user"""
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        if employee:
            faculty = self.env['op.faculty'].search([('emp_id', '=', employee.id)], limit=1)
            return faculty.id if faculty else False

    def action_assign_students(self):
        self.ensure_one()
        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']
        assign_details_model = self.env['aps.assign.details']
        
        # For recurring assignments, create assign_details first
        assign_detail_id = None
        if self.recurring_days > 0 and not self.env.context.get('skip_recurring_save'):
            assign_detail = self._save_recurring_assignment_details()
            assign_detail_id = assign_detail.id if assign_detail else None
        
        top_level_resource = self.resource_id
        top_level_resource_name = top_level_resource.display_name or top_level_resource.name or ''
        separator = ' 🢒 '
        label_source = self.submission_label or self.custom_submission_name or top_level_resource_name
        submission_label_for_date = assign_details_model._format_submission_label(label_source, self.date_assigned)
        # Get all resources to assign: selected resources from the list, ordered by sequence
        selected_resources = self.env['aps.resources']
        order = 1
        for line in self.affected_resource_line_ids.sorted('sequence'):
            if line.selected:
                selected_resources |= line.resource_id
                # Set order on the line for later use
                line.submission_order = order
                order += 1
        for index, resource in enumerate(selected_resources, start=1):
            # Find the order for this resource
            line = self.affected_resource_line_ids.filtered(lambda l: l.resource_id == resource and l.selected)
            submission_order = line.submission_order if line else 0
            # Compute submission_name: parent 🢒 child (or just parent if same)
            child_name = resource.name or resource.display_name or ''
            # Naming is tricky due to possible custom names set per parent.
            # There could be many resources are assigned. Normally they have their own names.
            # But we might want the name, esp when assigning a single resource.
            # Use parent-specific custom name if present, otherwise fall back to resource name/display_name
            if self.custom_submission_name:
                if len(selected_resources) == 1:
                    # Only one resource assigned, use the custom name directly
                    submission_name = self.custom_submission_name
                else:
                    submission_name = f"{self.custom_submission_name} ({child_name})"
            else:
                if resource.id == top_level_resource.id:
                    submission_name = top_level_resource_name
                else:
                    child_name = resource.name or resource.display_name or ''
                    custom_data = resource.parent_custom_name_data or []
                    if isinstance(custom_data, (list, tuple)):
                        for entry in custom_data:
                            if entry.get('parent_resource_id') == top_level_resource.id and entry.get('custom_name'):
                                child_name = entry.get('custom_name')
                                break
                    # Remove overlap as in _compute_display_name
                    overlap_length = 0
                    parent_len = len(top_level_resource_name)
                    child_len = len(child_name)
                    match_found = False
                    for i in range(1, min(parent_len, child_len) + 1):
                        if child_name[:i] == top_level_resource_name[-i:]:
                            overlap_length = i
                            match_found = True
                        else:
                            if match_found:
                                break
                    if overlap_length > 0:
                        remaining_name = child_name[overlap_length:].lstrip()
                        import re
                        remaining_name = re.sub(r'^\.+', '', remaining_name).lstrip()
                        if remaining_name:
                            submission_name = top_level_resource_name + separator + remaining_name
                        else:
                            submission_name = top_level_resource_name
                    else:
                        submission_name = top_level_resource_name + separator + child_name

            # Set the question based on the resource's setting and the wizard's fields
            # If the resource is the top_level_resource, use the wizard's has_question and question field settings. 
            # Otherwise, use the resource's has_question and question.
            if resource == top_level_resource:
                # The question HTML field is already prefilled with the correct question based on the resource's has_question setting in the onchange of resource_id, 
                # so we can just use that value directly without needing to check the has_question field again here. 
                # This also allows the user to override the question for the top-level resource if they want to.
                use_question = self.use_question
                question = self.question 
                notes = self.notes
                use_notes = self.use_notes
            else:
                use_question = False if resource.has_question == "no" else True
                notes = resource.notes
                use_notes = False if resource.has_notes == "no" else True
                question = resource.question 

            if not use_question:
                question = False

            if not use_notes:
                notes = False
            
            for student in self.student_ids:
                
                if len(self.subjects) < 2:
                    # If there is only one subject attached to the Resource then assume that is what should be assigned to the student regardless of what subjects they are currently taking.
                    # This is needed when a resource (eg ESL nugget) needs to be given to a student who doesn't do the subject.
                    # It assumes that there is only one subject associated then it must be relevant. 
                    # If there are multiple subjects then we will try to be smarter and only assign the ones that are relevant to the student based on their current courses.
                    assigned_subjects = self.subjects
                else:
                    # Get student's assigned subjects from running courses
                    student_record = self.env['op.student'].search([('partner_id', '=', student.id)], limit=1)
                    student_subjects = self.env['op.subject']
                    if student_record:
                        running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
                        student_subjects = running_courses.mapped('subject_ids')
                    # Intersect with wizard subjects
                    assigned_subjects = self.subjects & student_subjects
                
                # Check if task exists
                task = task_model.search([
                    ('resource_id', '=', resource.id),
                    ('student_id', '=', student.id)
                ], limit=1)
                if not task:
                    task = task_model.create({
                        'resource_id': resource.id,
                        'student_id': student.id,
                        'state': 'assigned',
                        'date_due': self.date_due,
                    })
                # Define has_answer before use
                has_answer = True if self.use_default_answer and self.default_answer else False
                # Create submission. Multiple submissions allowed per task.
                submission_model.create({
                    'task_id': task.id,
                    'assign_detail_id': assign_detail_id,
                    'assigned_by': self.assigned_by.id if self.assigned_by else False,
                    'submission_label': submission_label_for_date,
                    'submission_order': submission_order,
                    'submission_name': submission_name,
                    'date_assigned': self.date_assigned,
                    'time_assigned': self.time_assigned,
                    'date_due': self.date_due,
                    'allow_subject_editing': self.allow_subject_editing,
                    'state': 'assigned',
                    'answer': self.default_answer if self.use_default_answer and self.default_answer else False,
                    'subjects': assigned_subjects.ids,
                    'points_scale': self.points_scale,
                    'notification_state': 'not_sent' if self.notify_student else 'skipped',
                })

        return {'type': 'ir.actions.act_window_close'}

    def _save_recurring_assignment_details(self):
        self.ensure_one()
        due_offset_days = 0
        if self.date_assigned and self.date_due:
            due_offset_days = (self.date_due - self.date_assigned).days

        selected_lines = self.affected_resource_line_ids.filtered(lambda line: line.selected).sorted('sequence')
        assign_details_records = []
        for line in selected_lines:
            resource = line.resource_id
            is_top_level = resource.id == self.resource_id.id
            if is_top_level:
                vals = {
                    'enabled': self.recurring_days > 0 if self.recurring_days else False,
                    'resource_id': resource.id,
                    'assigned_by': self.assigned_by.id if self.assigned_by else False,
                    'custom_submission_name': self.custom_submission_name,
                    'submission_label': self.submission_label,
                    'date_due_offset_days': due_offset_days,
                    'time_assigned': self.time_assigned,
                    'recurring_days': self.recurring_days,
                    'next_assignment_date': fields.Date.add(self.date_assigned, days=self.recurring_days) if self.date_assigned and self.recurring_days > 0 else self.date_assigned,
                    'last_assigned_date': self.date_assigned,
                    'allow_subject_editing': self.allow_subject_editing,
                    'use_question': self.use_question,
                    'question': self.question,
                    'use_model_answer': self.use_model_answer,
                    'model_answer': self.model_answer,
                    'use_default_answer': self.use_default_answer,
                    'default_answer': self.default_answer,
                    'use_notes': self.use_notes,
                    'notes': self.notes,
                    'subjects': [(6, 0, self.subjects.ids)],
                    'points_scale': self.points_scale,
                    'notify_student': self.notify_student,
                    'assign_student_ids': [(0, 0, {'student_id': student.id}) for student in self.student_ids],
                }
            else:
                vals = {
                    'enabled': self.recurring_days > 0 if self.recurring_days else False,
                    'resource_id': resource.id,
                    'assigned_by': self.assigned_by.id if self.assigned_by else False,
                    'custom_submission_name': resource.display_name,
                    'submission_label': resource.display_name,
                    'date_due_offset_days': due_offset_days,
                    'time_assigned': self.time_assigned,
                    'recurring_days': self.recurring_days,
                    'next_assignment_date': fields.Date.add(self.date_assigned, days=self.recurring_days) if self.date_assigned and self.recurring_days > 0 else self.date_assigned,
                    'last_assigned_date': self.date_assigned,
                    'allow_subject_editing': resource.allow_subject_editing,
                    'question': resource.question,
                    'answer': resource.answer,
                    'notes': resource.notes,
                    'subjects': [(6, 0, resource.subjects.ids)],
                    'points_scale': resource.points_scale,
                    'notify_student': self.notify_student,
                    'assign_student_ids': [(0, 0, {'student_id': student.id}) for student in self.student_ids],
                }
            assign_details_records.append(self.env['aps.assign.details'].create(vals))
        return assign_details_records