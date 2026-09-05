from odoo import models, fields, api, _
from odoo.exceptions import UserError


class APSResourceMassUpdateWizard(models.TransientModel):
    _name = 'aps.resource.mass.update.wizard'
    _description = 'Mass Update Resources Wizard'
    _rec_name = 'id'

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

    update_sequence = fields.Boolean(string='Sequence')
    sequence_value = fields.Integer(string='Value')

    update_weight = fields.Boolean(string='Weight')
    weight_value = fields.Float(string='Value', digits=(16, 1))

    update_points_scale = fields.Boolean(string='Points Scale')
    points_scale_value = fields.Integer(string='Value', default=1)

    update_score_contributes_to_parent = fields.Boolean(string='Contributes to Parent Score')
    score_contributes_to_parent_value = fields.Boolean(string='Value')

    update_url = fields.Boolean(string='URL')
    url_value = fields.Char(string='Value')

    update_subjects = fields.Boolean(string='Subjects')
    subject_ids_value = fields.Many2many(
        'aps.subject', 'aps_mass_update_subject_rel', 'wizard_id', 'subject_id',
        string='Value',
    )

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

    update_auto_assign = fields.Boolean(string='Auto Assign')
    auto_assign_value = fields.Boolean(string='Value')
    update_auto_assign_date = fields.Boolean(string='Next Assign Date')
    auto_assign_date_value = fields.Date(string='Value')
    update_auto_assign_end_date = fields.Boolean(string='Auto Assign End Date')
    auto_assign_end_date_value = fields.Date(string='Value')
    update_auto_assign_due_days = fields.Boolean(string='Auto Assign Due Days')
    auto_assign_due_days_value = fields.Integer(string='Value')
    update_auto_assign_frequency = fields.Boolean(string='Auto Assign Frequency')
    auto_assign_frequency_value = fields.Integer(string='Value')
    update_auto_assign_time = fields.Boolean(string='Auto Assign Time')
    auto_assign_time_value = fields.Float(string='Value')
    update_auto_assign_all_students = fields.Boolean(string='Assign All Students')
    auto_assign_all_students_value = fields.Boolean(string='Value')
    update_auto_assign_notify_student = fields.Boolean(string='Notify Student')
    auto_assign_notify_student_value = fields.Boolean(string='Value')
    update_auto_assign_custom_name = fields.Boolean(string='Auto Assign Custom Name')
    auto_assign_custom_name_value = fields.Char(string='Value')

    update_ai_instructions = fields.Boolean(string='AI Instructions')
    ai_instructions_value = fields.Html(string='Value')
    update_ai_model_id = fields.Boolean(string='AI Model')
    ai_model_id_value = fields.Many2one('aps.ai.model', string='Value', domain=[('enabled', '=', True)])
    update_ai_model_ids = fields.Boolean(string='AI Models')
    ai_model_ids_value = fields.Many2many(
        'aps.ai.model', 'aps_mass_update_ai_model_rel', 'wizard_id', 'model_id',
        string='Value', domain=[('enabled', '=', True)],
    )
    update_ai_prompt_ids = fields.Boolean(string='AI Prompts')
    ai_prompt_ids_value = fields.Many2many(
        'ai_prompts', 'aps_mass_update_ai_prompt_rel', 'wizard_id', 'prompt_id',
        string='Value', domain=[('enabled', '=', True)],
    )
    update_ai_action = fields.Boolean(string='AI Action')
    ai_action_value = fields.Selection([
        ('none', 'None'), ('mark_submission', 'Mark Submission'),
        ('mark_submission_use_answer', '--Dont Use---'), ('manual', 'Manual Action'),
    ], string='Value')
    _AI_BOOLEAN_FIELDS = (
        'ai_use_model_answer', 'ai_use_question', 'ai_merge_responses',
        'ai_merge_response_chunks', 'ai_use_notes', 'ai_use_supporting_resources',
        'ai_targeted_feedback', 'ai_toc', 'ai_summary', 'ai_analysis',
        'ai_table_of_results', 'ai_test_prompt', 'ai_show_saved_responses',
    )
    update_ai_use_model_answer = fields.Boolean(string='Use AI Model Answer')
    ai_use_model_answer_value = fields.Boolean(string='Value')
    update_ai_use_question = fields.Boolean(string='Use AI Question')
    ai_use_question_value = fields.Boolean(string='Value')
    update_ai_merge_responses = fields.Boolean(string='Merge AI Responses')
    ai_merge_responses_value = fields.Boolean(string='Value')
    update_ai_merge_response_chunks = fields.Boolean(string='Merge AI Response Chunks')
    ai_merge_response_chunks_value = fields.Boolean(string='Value')
    update_ai_use_notes = fields.Boolean(string='Use AI Notes')
    ai_use_notes_value = fields.Boolean(string='Value')
    update_ai_use_supporting_resources = fields.Boolean(string='Use AI Supporting Resources')
    ai_use_supporting_resources_value = fields.Boolean(string='Value')
    update_ai_targeted_feedback = fields.Boolean(string='Targeted AI Feedback')
    ai_targeted_feedback_value = fields.Boolean(string='Value')
    update_ai_toc = fields.Boolean(string='AI TOC')
    ai_toc_value = fields.Boolean(string='Value')
    update_ai_summary = fields.Boolean(string='AI Summary')
    ai_summary_value = fields.Boolean(string='Value')
    update_ai_analysis = fields.Boolean(string='AI Analysis')
    ai_analysis_value = fields.Boolean(string='Value')
    update_ai_table_of_results = fields.Boolean(string='AI Table of Results')
    ai_table_of_results_value = fields.Boolean(string='Value')
    update_ai_test_prompt = fields.Boolean(string='Test AI Prompt')
    ai_test_prompt_value = fields.Boolean(string='Value')
    update_ai_show_saved_responses = fields.Boolean(string='Show Saved AI Responses')
    ai_show_saved_responses_value = fields.Boolean(string='Value')

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

    update_tags = fields.Boolean(string='Tags')
    tags_add_ids = fields.Many2many(
        'aps.resource.tags',
        'aps_mass_update_tags_add_rel',
        'wizard_id', 'tag_id',
        string='Add Tags',
    )
    tags_remove_ids = fields.Many2many(
        'aps.resource.tags',
        'aps_mass_update_tags_remove_rel',
        'wizard_id', 'tag_id',
        string='Remove Tags',
    )

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

        if self.update_sequence:
            updates['sequence'] = self.sequence_value

        if self.update_weight:
            updates['weight'] = self.weight_value

        if self.update_points_scale:
            updates['points_scale'] = self.points_scale_value

        if self.update_score_contributes_to_parent:
            updates['score_contributes_to_parent'] = self.score_contributes_to_parent_value

        if self.update_url:
            updates['url'] = self.url_value

        if self.update_subjects:
            updates['subjects'] = [(6, 0, self.subject_ids_value.ids)]

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

        for field_name in self._AI_BOOLEAN_FIELDS:
            if getattr(self, 'update_' + field_name):
                updates[field_name] = getattr(self, field_name + '_value')

        if self.update_ai_instructions:
            updates['ai_instructions'] = self.ai_instructions_value
        if self.update_ai_model_id:
            updates['ai_model_id'] = self.ai_model_id_value.id or False
        if self.update_ai_model_ids:
            updates['ai_model_ids'] = [(6, 0, self.ai_model_ids_value.ids)]
        if self.update_ai_prompt_ids:
            updates['ai_prompt_ids'] = [(6, 0, self.ai_prompt_ids_value.ids)]
        if self.update_ai_action:
            updates['ai_action'] = self.ai_action_value

        for field_name in (
            'auto_assign', 'auto_assign_date', 'auto_assign_end_date',
            'auto_assign_due_days', 'auto_assign_frequency', 'auto_assign_time',
            'auto_assign_all_students', 'auto_assign_notify_student',
            'auto_assign_custom_name',
        ):
            if getattr(self, 'update_' + field_name):
                updates[field_name] = getattr(self, field_name + '_value')

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

        if not updates and not self.update_tags:
            raise UserError(_("No updates selected. Please enable at least one update option."))

        if updates:
            self.resource_ids.write(updates)

        if self.update_tags:
            tag_commands = []
            for tag in self.tags_remove_ids:
                tag_commands.append((3, tag.id))
            for tag in self.tags_add_ids:
                tag_commands.append((4, tag.id))
            if tag_commands:
                self.resource_ids.write({'tag_ids': tag_commands})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Successfully updated %d resources.') % len(self.resource_ids),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
