from odoo import models, fields, api, _
from odoo.exceptions import UserError


class APSResourceMassUpdateWizard(models.TransientModel):
    _name = 'aps.resource.mass.update.wizard'
    _description = 'Mass Update Resources Wizard'

    resource_ids = fields.Many2many(
        'aps.resources',
        string='Resources',
        required=True,
        default=lambda self: self._default_resource_ids(),
    )

    # --- Update flags and values ---

    update_name = fields.Boolean(string='Name')
    name_value = fields.Char(string='Value')

    update_description = fields.Boolean(string='Description')
    description_value = fields.Text(string='Value')

    update_type_id = fields.Boolean(string='Type')
    type_id_value = fields.Many2one('aps.resource.types', string='Value')

    update_category = fields.Boolean(string='Category')
    category_value = fields.Selection([
        ('mandatory', 'Mandatory'),
        ('optional', 'Optional'),
        ('information', 'Information'),
    ], string='Value')

    update_marks = fields.Boolean(string='Out of Marks')
    marks_value = fields.Float(string='Value', digits=(16, 1))

    update_points_scale = fields.Boolean(string='Points Scale')
    points_scale_value = fields.Integer(string='Value', default=1)

    update_score_contributes_to_parent = fields.Boolean(string='Contributes to Parent Score')
    score_contributes_to_parent_value = fields.Boolean(string='Value')

    update_url = fields.Boolean(string='URL')
    url_value = fields.Char(string='Value')

    update_has_question = fields.Boolean(string='Has Question')
    has_question_value = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
    ], string='Value')

    update_has_answer = fields.Boolean(string='Has Answer')
    has_answer_value = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
    ], string='Value')

    update_has_notes = fields.Boolean(string='Has Notes')
    has_notes_value = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
    ], string='Value')

    update_has_lesson_plan = fields.Boolean(string='Has Lesson Plan')
    has_lesson_plan_value = fields.Boolean(string='Value')

    update_has_default_answer = fields.Boolean(string='Has Default Answer')
    has_default_answer_value = fields.Boolean(string='Value')

    update_has_child_resources = fields.Boolean(string='Has Linked Resources')
    has_child_resources_value = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
    ], string='Value')

    update_has_supporting_resources = fields.Boolean(string='Has Supporting Resources')
    has_supporting_resources_value = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
    ], string='Value')

    update_allow_subject_editing = fields.Boolean(string='Allow Subject Editing')
    allow_subject_editing_value = fields.Boolean(string='Value')

    update_show_in_hierarchy = fields.Boolean(string='Show in Hierarchy')
    show_in_hierarchy_value = fields.Boolean(string='Value')

    # HTML fields — toggled on Options tab, edited on their own tabs
    update_question = fields.Boolean(string='Question')
    question_value = fields.Html(string='Value')

    update_answer = fields.Boolean(string='Answer')
    answer_value = fields.Html(string='Value')

    update_notes = fields.Boolean(string='Notes')
    notes_value = fields.Html(string='Value')

    update_lesson_plan = fields.Boolean(string='Lesson Plan')
    lesson_plan_value = fields.Html(string='Value')

    update_default_answer = fields.Boolean(string='Default Answer')
    default_answer_value = fields.Html(string='Value')

    @api.model
    def _default_resource_ids(self):
        return self.env.context.get('active_ids', [])

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            for cmd in self.env.context.get('default_resource_ids', []):
                if isinstance(cmd, (list, tuple)) and len(cmd) >= 3 and cmd[0] == 6:
                    active_ids = cmd[2]
                    break
        if active_ids:
            first = self.env['aps.resources'].browse(active_ids[0])
            if first.exists():
                if 'question_value' in fields_list:
                    defaults['question_value'] = first.question
                if 'answer_value' in fields_list:
                    defaults['answer_value'] = first.answer
                if 'notes_value' in fields_list:
                    defaults['notes_value'] = first.notes
                if 'lesson_plan_value' in fields_list:
                    defaults['lesson_plan_value'] = first.lesson_plan
                if 'default_answer_value' in fields_list:
                    defaults['default_answer_value'] = first.default_answer
        return defaults

    def action_update(self):
        self.ensure_one()

        if not self.resource_ids:
            raise UserError(_("No resources selected."))

        updates = {}

        if self.update_name:
            updates['name'] = self.name_value

        if self.update_description:
            updates['description'] = self.description_value

        if self.update_type_id:
            updates['type_id'] = self.type_id_value.id if self.type_id_value else False

        if self.update_category:
            updates['category'] = self.category_value

        if self.update_marks:
            updates['marks'] = self.marks_value

        if self.update_points_scale:
            updates['points_scale'] = self.points_scale_value

        if self.update_score_contributes_to_parent:
            updates['score_contributes_to_parent'] = self.score_contributes_to_parent_value

        if self.update_url:
            updates['url'] = self.url_value

        if self.update_has_question:
            updates['has_question'] = self.has_question_value

        if self.update_has_answer:
            updates['has_answer'] = self.has_answer_value

        if self.update_has_notes:
            updates['has_notes'] = self.has_notes_value

        if self.update_has_lesson_plan:
            updates['has_lesson_plan'] = self.has_lesson_plan_value

        if self.update_has_default_answer:
            updates['has_default_answer'] = self.has_default_answer_value

        if self.update_has_child_resources:
            updates['has_child_resources'] = self.has_child_resources_value

        if self.update_has_supporting_resources:
            updates['has_supporting_resources'] = self.has_supporting_resources_value

        if self.update_allow_subject_editing:
            updates['allow_subject_editing'] = self.allow_subject_editing_value

        if self.update_show_in_hierarchy:
            updates['show_in_hierarchy'] = self.show_in_hierarchy_value

        if self.update_question:
            updates['question'] = self.question_value

        if self.update_answer:
            updates['answer'] = self.answer_value

        if self.update_notes:
            updates['notes'] = self.notes_value

        if self.update_lesson_plan:
            updates['lesson_plan'] = self.lesson_plan_value

        if self.update_default_answer:
            updates['default_answer'] = self.default_answer_value

        if not updates:
            raise UserError(_("No updates selected. Please enable at least one update option."))

        self.resource_ids.write(updates)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Successfully updated %d resources.') % len(self.resource_ids),
                'type': 'success',
            }
        }
