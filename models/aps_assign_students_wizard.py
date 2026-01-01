from odoo import models, fields, api

class APSAssignStudentsWizard(models.TransientModel):
    _name = 'aps.assign.students.wizard'
    _description = 'Assign Students to Resource Wizard'

    resource_id = fields.Many2one('aps.resources', string='Resource', required=True, readonly=True)
    date_assigned = fields.Date(string='Date Assigned', required=True, default=fields.Date.today)
    due_date = fields.Date(string='Due Date', required=True)
    student_ids = fields.Many2many('res.partner', string='Students', domain=[('is_student', '=', True)], required=True)

    def action_assign_students(self):
        assignment_model = self.env['aps.resource.assignment']
        attempt_model = self.env['aps.resource.attempt']
        
        for student in self.student_ids:
            # Check if assignment exists
            assignment = assignment_model.search([
                ('resource_id', '=', self.resource_id.id),
                ('student_id', '=', student.id)
            ], limit=1)
            
            if not assignment:
                assignment = assignment_model.create({
                    'resource_id': self.resource_id.id,
                    'student_id': student.id,
                    'state': 'assigned',
                    'due_date': self.due_date,
                })
            
            # Create attempt
            attempt_model.create({
                'assignment_id': assignment.id,
                'date_assigned': self.date_assigned,
                'due_date': self.due_date,
                'state': 'incomplete',
            })
        
        return {'type': 'ir.actions.act_window_close'}