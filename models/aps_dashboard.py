from odoo import models, fields, api

class APSDashboard(models.TransientModel):
    _name = 'aps.dashboard'
    _description = 'APS Dashboard'

    total_submissions = fields.Integer(string='Total Submissions', compute='_compute_stats', store=False)
    completed_submissions = fields.Integer(string='Completed Submissions', compute='_compute_stats', store=False)
    overdue_tasks = fields.Integer(string='Overdue Tasks', compute='_compute_stats', store=False)
    active_resources = fields.Integer(string='Active Resources', compute='_compute_stats', store=False)
    total_tasks = fields.Integer(string='Total Tasks', compute='_compute_stats', store=False)
    top_student = fields.Char(string='Top Student', compute='_compute_stats', store=False)
    overdue_students = fields.Integer(string='Students with Overdue Tasks', compute='_compute_stats', store=False)

    @api.depends()
    def _compute_stats(self):
        for rec in self:
            submission_model = self.env['aps.resource.submission']
            task_model = self.env['aps.resource.task']
            resource_model = self.env['aps.resources']
            partner_model = self.env['res.partner']
            rec.total_submissions = submission_model.search_count([])
            rec.completed_submissions = submission_model.search_count([('state', '=', 'complete')])
            rec.overdue_tasks = task_model.search_count([('date_due', '<', fields.Date.today()), ('state', '!=', 'complete')])
            rec.active_resources = resource_model.search_count([('task_ids', '!=', False)])
            rec.total_tasks = task_model.search_count([])
            # Top student by completed submissions
            top_student_id = False
            top_student_count = 0
            student_counts = {}
            for submission in submission_model.search([('state', '=', 'complete')]):
                student_id = submission.task_id.student_id.id if submission.task_id and submission.task_id.student_id else False
                if student_id:
                    student_counts[student_id] = student_counts.get(student_id, 0) + 1
                    if student_counts[student_id] > top_student_count:
                        top_student_count = student_counts[student_id]
                        top_student_id = student_id
            if top_student_id:
                rec.top_student = partner_model.browse(top_student_id).name
            else:
                rec.top_student = 'N/A'
            # Students with overdue tasks
            overdue_students = set()
            for task in task_model.search([('date_due', '<', fields.Date.today()), ('state', '!=', 'complete')]):
                if task.student_id:
                    overdue_students.add(task.student_id.id)
            rec.overdue_students = len(overdue_students)