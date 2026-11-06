from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.resources.chapter_tagging import chapter_labels, chapter_text


class APSChapterTaggingWizard(models.TransientModel):
    _name = 'aps.chapter.tagging.wizard'
    _description = 'Tag Resources with Textbook Chapters'

    resource_ids = fields.Many2many('aps.resources', required=True, readonly=True)
    summary_id = fields.Many2one(
        'aps.resources', string='Textbook Summary', required=True,
        domain=lambda self: [('tag_ids', 'in', [self.env.ref('aps_sis.tag_textbook_chapter_summary').id])],
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        if self.env.context.get('active_model') == 'aps.resources' and 'resource_ids' in field_names:
            values['resource_ids'] = [(6, 0, self.env.context.get('active_ids', []))]
        if 'summary_id' in field_names:
            summaries = self.env['aps.resources'].search([
                ('tag_ids', 'in', [self.env.ref('aps_sis.tag_textbook_chapter_summary').id]),
            ], limit=2)
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
        self.summary_id.check_access('read')
        summary_text = chapter_text(self.summary_id.notes)
        if not chapter_labels(summary_text):
            raise UserError(_('The summary Note must contain text with chapter labels such as Ch01 or Chapter 1.'))
        runs = self.env['aps.ai.run'].sudo().browse()
        for resource in resources:
            inputs = [
                (label, chapter_text(resource[field]))
                for label, field in [('Question', 'question'), ('Model Answer', 'answer'), ('Note', 'notes')]
            ]
            inputs = [(label, text) for label, text in inputs if text]
            run = self.env['aps.ai.run'].sudo().create({
                'resource_id': resource.id,
                'requested_by_id': self.env.uid,
                'processor_key': 'chapter_tagging',
                'chapter_summary_id': self.summary_id.id,
                'chapter_summary_text': summary_text,
                'chapter_input_fields': ', '.join(label for label, text in inputs) or _('None'),
                'chapter_input_text': '\n\n'.join('%s:\n%s' % item for item in inputs),
                'status_message': _('Queued chapter tagging...'),
            })
            run._queue_background_processing()
            runs |= run
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_chapter_tagging_progress',
            'params': {'run_ids': runs.ids, 'run_model': 'aps.ai.run'},
        }
