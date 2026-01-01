from odoo import models, fields


class APSTask(models.Model):
    _name = 'aps.tasks'
    _description = 'APS Task'

    name = fields.Char(string='Name', required=True)
    description = fields.Html(string='Description')
    resource_ids = fields.Many2many(
        'aps.resources',
        'aps_task_resource_rel',
        'task_id',
        'resource_id',
        string='Resources'
    )

    resource_type_ids = fields.Many2many(
        'aps.resource.types',
        string='Resource Types',
        compute='_compute_resource_types',
        store=False
    )

    def _compute_resource_types(self):
        for task in self:
            types = task.resource_ids.mapped('type_id')
            task.resource_type_ids = types
