from odoo import _, api, fields, models
from odoo.exceptions import UserError


class APSResourcePrintWizard(models.TransientModel):
    _name = 'aps.resource.print.wizard'
    _description = 'Resource Print Options'

    resource_ids = fields.Many2many(
        'aps.resources',
        'aps_resource_print_wizard_rel',
        'wizard_id',
        'resource_id',
        string='Resources',
        readonly=True,
    )
    resource_count = fields.Integer(string='Resources Selected', readonly=True)
    include_basic = fields.Boolean(string='Basic Information', default=True)
    include_notes = fields.Boolean(string='Notes', default=True)
    include_question = fields.Boolean(string='Question', default=True)
    include_model_answer = fields.Boolean(string='Model Answer', default=True)
    include_lesson_plan = fields.Boolean(string='Lesson Plan', default=True)
    include_assigned_students = fields.Boolean(string='Assigned Students', default=True)
    title_mode = fields.Selection(
        [
            ('normal', 'Normal'),
            ('none', 'None'),
            ('numbered', 'Numbered'),
        ],
        string='Title',
        default='normal',
        required=True,
    )
    include_images = fields.Boolean(string='Include Images', default=True)
    page_breaks = fields.Selection(
        [
            ('none', 'None'),
            ('resource', 'Resource'),
            ('field', 'Field'),
        ],
        string='Page Breaks',
        default='none',
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        resource_ids = self.env.context.get('active_ids', [])
        if not resource_ids:
            resource_ids = self.env.context.get('default_resource_ids', [])
            if resource_ids and isinstance(resource_ids[0], (list, tuple)):
                resource_ids = next(
                    (command[2] for command in resource_ids if command[0] == 6),
                    [],
                )
        if resource_ids:
            resources = self.env['aps.resources'].browse(resource_ids).exists()
            values['resource_ids'] = [(6, 0, resources.ids)]
            values['resource_count'] = len(resources)
        return values

    def action_print_report(self):
        self.ensure_one()
        if not self.resource_ids:
            raise UserError(_('Select at least one resource to print.'))
        if not any((
            self.include_basic,
            self.include_notes,
            self.include_question,
            self.include_model_answer,
            self.include_lesson_plan,
            self.include_assigned_students,
        )):
            raise UserError(_('Select at least one section to include.'))

        data = {
            'resource_ids': self.resource_ids.ids,
            'include_basic': self.include_basic,
            'include_notes': self.include_notes,
            'include_question': self.include_question,
            'include_model_answer': self.include_model_answer,
            'include_lesson_plan': self.include_lesson_plan,
            'include_assigned_students': self.include_assigned_students,
            'title_mode': self.title_mode,
            'include_images': self.include_images,
            'page_breaks': self.page_breaks,
        }
        return self.env.ref('aps_sis.action_report_aps_resources_print').report_action(
            self.resource_ids,
            data=data,
        )