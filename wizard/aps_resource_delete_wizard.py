from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ApsResourceDeleteWizard(models.TransientModel):
    _name = 'aps.resource.delete.wizard'
    _description = 'Delete Resource and Assignments'

    resource_id = fields.Many2one(
        'aps.resources',
        string='Resource',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    task_count = fields.Integer(compute='_compute_preview')
    task_preview = fields.Text(compute='_compute_preview')
    assigned_submission_count = fields.Integer(compute='_compute_preview')
    assigned_submission_preview = fields.Text(compute='_compute_preview')
    submitted_submission_count = fields.Integer(compute='_compute_preview')
    submitted_submission_preview = fields.Text(compute='_compute_preview')
    finalised_submission_count = fields.Integer(compute='_compute_preview')
    finalised_submission_preview = fields.Text(compute='_compute_preview')

    @api.depends(
        'resource_id',
        'resource_id.task_ids',
        'resource_id.task_ids.student_id',
        'resource_id.task_ids.display_name',
        'resource_id.task_ids.submission_ids',
        'resource_id.task_ids.submission_ids.state',
        'resource_id.task_ids.submission_ids.submission_name',
        'resource_id.task_ids.submission_ids.display_name',
    )
    def _compute_preview(self):
        states = {
            'assigned': ('assigned_submission_count', 'assigned_submission_preview'),
            'submitted': ('submitted_submission_count', 'submitted_submission_preview'),
            'complete': ('finalised_submission_count', 'finalised_submission_preview'),
        }
        for wizard in self:
            tasks = self.env['aps.resource.task']
            submissions = self.env['aps.resource.submission']
            if wizard.resource_id:
                tasks = self.env['aps.resource.task'].search([
                    ('resource_id', '=', wizard.resource_id.id),
                ], order='student_id, id')
                if tasks:
                    submissions = self.env['aps.resource.submission'].search([
                        ('task_id', 'in', tasks.ids),
                    ], order='task_id, date_assigned, id')

            wizard.task_count = len(tasks)
            wizard.task_preview = '\n'.join(
                task.display_name or task.student_id.display_name
                for task in tasks
            ) or 'No tasks.'

            for state, (count_field, preview_field) in states.items():
                state_submissions = submissions.filtered(lambda submission: submission.state == state)
                wizard[count_field] = len(state_submissions)
                wizard[preview_field] = '\n'.join(
                    '%s - %s - %s' % (
                        submission.student_id.display_name,
                        submission.task_id.display_name,
                        submission.submission_name or submission.display_name,
                    )
                    for submission in state_submissions
                ) or 'None.'

    def action_confirm_delete(self):
        self.ensure_one()
        resource = self.resource_id.exists()
        if not resource:
            raise UserError(_('This resource no longer exists.'))

        tasks = self.env['aps.resource.task'].search([
            ('resource_id', '=', resource.id),
        ])
        submissions = self.env['aps.resource.submission'].search([
            ('task_id', 'in', tasks.ids),
        ]) if tasks else self.env['aps.resource.submission']

        parent_resources = resource.parent_ids
        parent_submissions = self.env['aps.resource.submission'].search([
            ('resource_id', 'in', parent_resources.ids),
            ('auto_score', '=', True),
        ]) if parent_resources else self.env['aps.resource.submission']

        submissions.unlink()
        tasks.unlink()
        resource.with_context(_aps_resource_delete_wizard=True).unlink()

        parent_submissions.exists()._recalculate_score_from_children()
        return {'type': 'ir.actions.client', 'tag': 'reload'}