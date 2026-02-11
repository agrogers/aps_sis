from odoo import models, fields, api

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
    date_due = fields.Date(string='Due Date', required=True)
    student_ids = fields.Many2many('res.partner', string='Students', domain=[('is_student', '=', True)], required=True)
    assigned_by = fields.Many2one('op.faculty', string='Assigned By', default=lambda self: self._default_assigned_by())
    custom_submission_name = fields.Char(string='Custom Submission Name')
    warning_message = fields.Char(string='Warning', compute='_compute_warning_message', store=False)
    submission_label = fields.Char(string='Submission Label', help='Identifier for grouping submissions, e.g., S1 Exam, Exam Prep, Homework')
    affected_resource_line_ids = fields.One2many('aps.assign.students.wizard.line', 'wizard_id', string='Affected Resources', order='sequence')
    can_assign = fields.Boolean(string='Can Assign', compute='_compute_can_assign', store=False)
    allow_subject_editing = fields.Boolean(
        string='Allow Subject Editing',
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
)
    question = fields.Html(string='Question')
    parent_question = fields.Html(string='Parent Question', store=False)

    has_answer = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
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
                'resource_id', 'warning_message', 'can_assign', 'parent_question', 'parent_answer',
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

        # # Copy matching fields from the selected resource into the wizard fields
        # if self.resource_id:
        #     skip_fields = {
        #         'id', 'display_name', 'name', 'affected_resource_line_ids',
        #         'student_ids', 'submission_label', 'submission_order', 'assigned_by',
        #         'resource_id', 'warning_message', 'can_assign', 'parent_question', 'parent_answer',
        #     }
        #     for fname in self._fields:
        #         if fname in skip_fields:
        #             continue
        #         # only copy if resource has this field
        #         if fname in self.resource_id._fields:
        #             try:
        #                 setattr(self, fname, self.resource_id[fname])
        #             except Exception:
        #                 # ignore fields that can't be assigned or cause errors
        #                 continue

    def _default_assigned_by(self):
        """Get the faculty record for the current user"""
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        if employee:
            faculty = self.env['op.faculty'].search([('emp_id', '=', employee.id)], limit=1)
            return faculty.id if faculty else False
        return False

    def action_assign_students(self):
        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']
        parent_resource = self.resource_id
        parent_name = parent_resource.display_name or parent_resource.name or ''
        separator = ' 🢒 '
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
                if resource.id == parent_resource.id:
                    submission_name = parent_name
                else:
                    child_name = resource.name or resource.display_name or ''
                    custom_data = resource.parent_custom_name_data or []
                    if isinstance(custom_data, (list, tuple)):
                        for entry in custom_data:
                            if entry.get('parent_resource_id') == parent_resource.id and entry.get('custom_name'):
                                child_name = entry.get('custom_name')
                                break
                    # Remove overlap as in _compute_display_name
                    overlap_length = 0
                    parent_len = len(parent_name)
                    child_len = len(child_name)
                    match_found = False
                    for i in range(1, min(parent_len, child_len) + 1):
                        if child_name[:i] == parent_name[-i:]:
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
                            submission_name = parent_name + separator + remaining_name
                        else:
                            submission_name = parent_name
                    else:
                        submission_name = parent_name + separator + child_name
            for student in self.student_ids:
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
                    'date_due': self.date_due,
                    'allow_subject_editing': self.allow_subject_editing,
                    'state': 'assigned',
                    'answer': self.default_answer if self.has_default_answer and self.default_answer else False,
                })
        return {'type': 'ir.actions.act_window_close'}