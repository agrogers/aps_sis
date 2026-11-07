from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.resources.chapter_tagging import (
    chapter_summary_candidates,
    chapter_text,
    create_chapter_tagging_run,
)


class APSChapterTaggingWizard(models.TransientModel):
    _name = 'aps.chapter.tagging.wizard'
    _description = 'Tag Resources with Textbook Chapters'

    resource_ids = fields.Many2many('aps.resources', required=True, readonly=True)
    summary_id = fields.Many2one('aps.resources', string='Textbook Summary', required=True)
    eligible_summary_ids = fields.Many2many(
        'aps.resources', compute='_compute_eligible_summary_ids',
    )

    @api.depends('resource_ids', 'resource_ids.subjects')
    def _compute_eligible_summary_ids(self):
        for wizard in self:
            wizard.eligible_summary_ids = chapter_summary_candidates(
                wizard.env, wizard.resource_ids,
            )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        if self.env.context.get('active_model') == 'aps.resources' and 'resource_ids' in field_names:
            values['resource_ids'] = [(6, 0, self.env.context.get('active_ids', []))]
        if 'summary_id' in field_names:
            resources = self.env['aps.resources'].browse(
                self.env.context.get('active_ids', []),
            ).exists()
            summaries = chapter_summary_candidates(self.env, resources)
            if len(summaries) == 1:
                values['summary_id'] = summaries.id
        return values

    def action_tag_chapters(self):
        self.ensure_one()
        if not self.env.user.has_group('aps_sis.group_aps_teacher'):
            raise AccessError(_('Only teachers can start chapter tagging.'))
        resources = self.resource_ids.exists()
        if not resources:
            raise UserError(_('Select at least one resource to tag.'))
        resources.check_access('write')
        if not self.summary_id:
            raise UserError(_('Select a textbook summary matching the subjects of the selected resources.'))
        self.summary_id.check_access('read')
        if self.summary_id not in chapter_summary_candidates(self.env, resources):
            raise UserError(_('The textbook summary must share a subject with every selected resource.'))
        summary_text = chapter_text(self.summary_id.notes)
        if not chapter_labels(summary_text):
            raise UserError(_('The summary Note must contain text with chapter labels such as Ch01 or Chapter 1.'))
        runs = self.env['aps.ai.run'].sudo().browse()
        for resource in resources:
            runs |= create_chapter_tagging_run(resource, self.summary_id, self.env.uid)
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_chapter_tagging_progress',
            'params': {
                'run_ids': runs.ids,
                'run_labels': runs.mapped('resource_id.display_name'),
                'run_model': 'aps.ai.run',
            },
        }
