from odoo import models, fields, api

class APSAssignStudentsWizardLine(models.TransientModel):
    _name = 'aps.assign.students.wizard.line'
    _description = 'Assign Students Wizard Line'

    wizard_id = fields.Many2one('aps.assign.students.wizard', required=True)
    resource_id = fields.Many2one('aps.resources', string='Resource', required=True)
    display_name = fields.Char(string='Resource', compute='_compute_display_name', store=False)
    description = fields.Text(string='Description', related='resource_id.description', readonly=True)
    selected = fields.Boolean(string='Assign', default=True)

    @api.depends('resource_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.resource_id.display_name if rec.resource_id else ''

class APSAssignStudentsWizard(models.TransientModel):
    _name = 'aps.assign.students.wizard'
    _description = 'Assign Students to Resource Wizard'

    resource_id = fields.Many2one('aps.resources', string='Resource', required=True, readonly=True)
    date_assigned = fields.Date(string='Date Assigned', required=True, default=fields.Date.today)
    date_due = fields.Date(string='Due Date', required=True)
    student_ids = fields.Many2many('res.partner', string='Students', domain=[('is_student', '=', True)], required=True)
    assigned_by = fields.Many2one('op.faculty', string='Assigned By', default=lambda self: self._default_assigned_by())
    submission_label = fields.Char(help='Identifier for grouping submissions, e.g., S1 Exam, Exam Prep, Homework')
    affected_resource_line_ids = fields.One2many('aps.assign.students.wizard.line', 'wizard_id', string='Affected Resources')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        return res

    @api.onchange('resource_id')
    def _onchange_resource_id(self):
        if self.resource_id:
            all_descendants = self.resource_id._get_all_descendants()
            lines = [(0, 0, {
                'resource_id': self.resource_id.id,
                'selected': True,
            })]
            for descendant in all_descendants:
                lines.append((0, 0, {
                    'resource_id': descendant.id,
                    'selected': True,
                }))
            self.affected_resource_line_ids = lines
        else:
            self.affected_resource_line_ids = False

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
        
        # Get all resources to assign: selected resources from the list
        selected_resources = self.env['aps.resources']
        for line in self.affected_resource_line_ids:
            if line.selected:
                selected_resources |= line.resource_id
        
        for resource in selected_resources:
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
                    'date_assigned': self.date_assigned,
                    'date_due': self.date_assigned,
                    'state': 'assigned',
                })
        
        return {'type': 'ir.actions.act_window_close'}