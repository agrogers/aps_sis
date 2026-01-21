from odoo import models, fields, api

class APSAssignStudentsWizardLine(models.TransientModel):
    _name = 'aps.assign.students.wizard.line'
    _description = 'Assign Students Wizard Line'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Name')

    wizard_id = fields.Many2one('aps.assign.students.wizard', required=True)
    type_icon = fields.Binary(related='resource_id.type_icon', string='Icon', readonly=True)
    resource_id = fields.Many2one('aps.resources', string='Resource', required=False)
    display_name = fields.Char(string='Resource', compute='_compute_display_name', store=False)
    description = fields.Text(string='Description', related='resource_id.description', readonly=True)
    has_question = fields.Selection(related='resource_id.has_question', readonly=True)
    has_answer = fields.Selection(related='resource_id.has_answer', readonly=True)
    supporting_resources_buttons = fields.Json(related='resource_id.supporting_resources_buttons', string='Resource Links', readonly=True)
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

        resource_id = res.get('resource_id')
        if not resource_id:
            return res

        resource = self.env['aps.resources'].browse(resource_id)

        # ---- existing submission label logic (kept) ----
        label = resource.display_name
        if res.get('date_assigned'):
            label += f' ({res["date_assigned"]})'
        res['submission_label'] = label

        # ---- NEW: create wizard lines explicitly ----
        lines = []

        selected = resource.has_question == 'yes'
        lines.append((0, 0, {
            'resource_id': resource.id,
            'selected': selected,
        }))

        for descendant in resource._get_all_descendants().filtered(lambda r: r.id):
            selected = descendant.has_question == 'yes'
            lines.append((0, 0, {
                'resource_id': descendant.id,
                'selected': selected,
            }))

        res['affected_resource_line_ids'] = lines

        return res


    @api.onchange('resource_id')
    def _onchange_resource_id(self):
        pass

    # @api.onchange('resource_id')
    # def _onchange_resource_id(self):
    #     if self.resource_id:
    #         all_descendants = self.resource_id._get_all_descendants().filtered(lambda r: r.id)
    #         selected = True if self.resource_id.has_question == 'yes' else False
    #         lines = []
    #         if self.resource_id.id:
    #             lines.append((0, 0, {
    #                 'resource_id': self.resource_id.id,
    #                 'selected': selected,
    #             }))
    #         for descendant in all_descendants:
    #             selected = True if descendant.has_question == 'yes' else False
    #             lines.append((0, 0, {
    #                 'resource_id': descendant.id,
    #                 'selected': selected,
    #             }))
    #         self.affected_resource_line_ids = lines
    #     else:
    #         self.affected_resource_line_ids = [(5, 0, 0)]

    def _default_assigned_by(self):
        """Get the faculty record for the current user"""
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        if employee:
            faculty = self.env['op.faculty'].search([('emp_id', '=', employee.id)], limit=1)
            return faculty.id if faculty else False
        return False

    def action_assign_students(self):
        print("=== In action_assign_students ===")
        self.ensure_one()
        print("Wizard ID:", self.id)  # Should be a real ID
        print("Affected lines count:", len(self.affected_resource_line_ids))
        print("Selected resources:", self.affected_resource_line_ids.filtered('selected').mapped('resource_id').ids)
        # ... rest of your code

    # def action_assign_students(self):
        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']
        
        # Get all resources to assign: selected resources from the list
        selected_resources = self.env['aps.resources']
        for line in self.affected_resource_line_ids:
            if line.selected and line.resource_id:
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