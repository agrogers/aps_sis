from odoo import models, fields, api

class APSAssignStudentsWizardLine(models.TransientModel):
    _name = 'aps.assign.students.wizard.line'
    _description = 'APEX Assign Students Wizard Line'
    _order = 'sequence, id'

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

class APSAssignStudentsWizard(models.TransientModel):
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
    affected_resource_line_ids = fields.One2many('aps.assign.students.wizard.line', 'wizard_id', string='Affected Resources')
    
    allow_subject_editing = fields.Boolean(
        string='Allow Subject Editing',
        store=True
    )

    has_question = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
        ], string='Has Question', 
        default='no', 
        help='A resource can use the parent\'s question if set to "Use Parent". This applies ONLY to the top-level resource. ' \
        'Child resources will always use their own question setting.',
        required=True,
)
    question = fields.Html(string='Question')
    parent_question = fields.Html(string='Parent Question', store=False)

    has_answer = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('yes_notes', 'Yes (Notes)'),
        ('use_parent', 'Use Parent'),
        ], string='Has Answer', 
        default='no', 
        help='Resources can include model answers to a question. A resource can use the parent\'s answer if set to "Use Parent".',
        required=True,
)
    answer = fields.Html(string='Answer', help='Model answer for the resource question.')    

    has_default_answer = fields.Boolean(
        string='Use Default Answer', 
        default=False, 
        help='Resources can include a default answer to a question. This is helpful if you wish to provide a template for students to fill in.',
        required=True,
)
    default_answer = fields.Html(string='Default Answer', help='Default answer template for the resource question.')    

    subjects = fields.Many2many('op.subject', string='Subjects')
    points_scale = fields.Integer(string='Points Scale', default=1, help='Scales the points allocated to the submission. This is useful for resources that are used in different contexts with different grading schemes.')
    notify_student = fields.Boolean(string='Notify Student', default=True, help='If enabled, students will receive a notification when they are assigned to the resource.')

    can_assign = fields.Boolean(string='Can Assign', compute='_compute_can_assign', store=False) # Helper field to enable/disable assign button based on whether any students and any resources are selected

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        resource = self.env['aps.resources'].browse(res.get('resource_id'))
        res['custom_submission_name'] = resource.display_name
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
            }
            for fname in self._fields:
                if fname in skip_fields:
                    continue
                # respect requested fields_list if provided
                if fields_list and fname not in fields_list:
                    continue
                # only copy if the resource model has the field
                if fname in resource._fields:
                    try:
                        val = resource[fname]
                        # store into default dict
                        res[fname] = val
                    except Exception:
                        # guard against unexpected read/compute errors
                        continue

    
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
        """Update student list when subjects change"""
        if self.subjects:
        
            # Find all students who are enrolled in running courses with these subjects
            student_partners = self.env['res.partner']
            
            # Get all students enrolled in running courses

            # student_records = self.env['op.student'].search([])
            # for student_record in student_records:
            #     running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
            #     student_subjects = running_courses.mapped('subject_ids')
            #     # If student has any of the resource subjects, include them
            #     if student_subjects:
            #         student_partners |= student_record.partner_id
            

            # 1. Get the subjects we care about (from the submission)
            relevant_subjects = self.subjects  # Many2many 'op.subject'

            if not relevant_subjects:
                # No subjects → no students (or handle differently)
                student_partners = self.env['res.partner']
            else:
                # 2. Find students who have at least one running course with overlapping subjects
                students = self.env['op.student'].search([
                    ('course_detail_ids.state', '=', 'running'),
                    ('course_detail_ids.subject_ids', 'in', relevant_subjects.ids),
                ])

                # 3. Get their partners
                student_partners = students.mapped('partner_id')

            if student_partners:
                self.student_ids = student_partners
            else:
                self.student_ids = False

    @api.onchange('resource_id')
    def _onchange_resource_id(self):
        if self.resource_id:
            
            all_descendants = self.resource_id._get_all_descendants()
            lines = [(0, 0, {
                'resource_id': self.resource_id.id,
                'selected': self.resource_id.has_question == 'yes',
                'sequence': 10,
            })]
            sequence = 20
            for descendant in all_descendants:
                selected = descendant.has_question == 'yes'
                lines.append((0, 0, {
                    'resource_id': descendant.id,
                    'parent_resource_id': self.resource_id.id,
                    'selected': selected,
                    'sequence': sequence,
                }))
                sequence += 10
            self.affected_resource_line_ids = lines
        else:
            self.affected_resource_line_ids = False

    def _default_assigned_by(self):
        """Get the faculty record for the current user"""
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        if employee:
            faculty = self.env['op.faculty'].search([('emp_id', '=', employee.id)], limit=1)
            return faculty.id if faculty else False

    def action_assign_students(self):
        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']
        top_level_resource = self.resource_id
        # Get all resources to assign: selected resources from the list, ordered by sequence
        selected_resources = self.env['aps.resources']
        order = 1
        for line in self.affected_resource_line_ids.sorted('sequence'):
            if line.selected:
                selected_resources |= line.resource_id
                # Set order on the line for later use
                line.submission_order = order
                order += 1

        # Resolve submission names for the entire tree using custom names
        top_name = self.custom_submission_name or None
        name_map = selected_resources._resolve_submission_names(
            top_level_resource, top_level_name=top_name,
        )

        for index, resource in enumerate(selected_resources, start=1):
            # Find the order for this resource
            line = self.affected_resource_line_ids.filtered(lambda l: l.resource_id == resource and l.selected)
            submission_order = line.submission_order if line else 0
            # Submission name resolved by the tree-aware helper
            submission_name = name_map.get(resource.id, resource.name or '')

            # Set the question based on the resource's setting and the wizard's fields
            # If the resource is the top_level_resource, use the wizard's has_question and question field settings. 
            # Otherwise, use the resource's has_question and question.
            if resource == top_level_resource:
                # The question HTML field is already prefilled with the correct question based on the resource's has_question setting in the onchange of resource_id, 
                # so we can just use that value directly without needing to check the has_question field again here. 
                # This also allows the user to override the question for the top-level resource if they want to.
                has_question = self.has_question
                parent_question = question = self.question 
            else:
                has_question = resource.has_question
                question = resource.question 
                parent_question = resource.primary_parent_id.question if resource.primary_parent_id else False

            if has_question == 'no':
                use_question = False
            elif has_question == 'yes':
                use_question = question if question else False
            elif has_question == 'use_parent':
                # Copy question from resource if not explicitly provided
                use_question = parent_question if parent_question else False
                
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
                # Create submission. Multiple submissions allowed per task.
                submission_model.create({
                    'task_id': task.id,
                    'assigned_by': self.assigned_by.id if self.assigned_by else False,
                    'submission_label': self.submission_label,
                    'submission_order': submission_order,
                    'submission_name': submission_name,
                    'date_assigned': self.date_assigned,
                    'time_assigned': self.time_assigned,
                    'date_due': self.date_due,
                    'allow_subject_editing': self.allow_subject_editing,
                    'state': 'assigned',
                    'question': use_question,
                    'has_question': has_question,
                    'answer': self.default_answer if self.has_default_answer and self.default_answer else False,
                    'subjects': assigned_subjects.ids,
                    'points_scale': self.points_scale,
                    'notification_state': 'not_sent' if self.notify_student else 'skipped',
                })
        return {'type': 'ir.actions.act_window_close'}