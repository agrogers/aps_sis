import uuid
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class APSAISaveResponseWizard(models.TransientModel):
    _name = 'aps.ai.save.response.wizard'
    _description = 'Save AI Response'

    resource_id = fields.Many2one(
        'aps.resources',
        string='Resource',
        required=True,
        readonly=True,
    )
    response_name = fields.Char(
        string='Response Name',
        required=True,
        help='A memorable name for this saved AI response.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            res['resource_id'] = active_id
            resource = self.env['aps.resources'].browse(active_id)
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
            res['response_name'] = _('Response – %s') % now_str
        return res

    def action_save(self):
        self.ensure_one()
        resource = self.resource_id
        if not resource:
            raise UserError(_('No resource found to save the response to.'))

        if not resource.ai_feedback:
            raise UserError(
                _('There is no AI response to save. Please run the AI test first.')
            )

        # Determine the AI model name used for the last test run
        ai_model_name = False
        if resource.ai_model_id:
            ai_model_name = resource.ai_model_id.display_name
        else:
            # Try to find the active model that would have been used
            try:
                candidates = self.env['aps.ai.model']._get_generation_candidates(resource=resource)
                if candidates:
                    ai_model_name = candidates[0].display_name
            except Exception:
                pass

        key = str(uuid.uuid4())
        entry = {
            'name': self.response_name,
            'saved_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ai_model_name': ai_model_name or '',
            'ai_answer': resource.ai_answer or '',
            'ai_feedback': resource.ai_feedback or '',
            'ai_score': resource.ai_score or 0.0,
            'ai_score_comment': resource.ai_score_comment or '',
            'ai_answer_chunks': resource.ai_answer_chunks or None,
            'ai_answer_chunked_html': resource.ai_answer_chunked_html or '',
            'ai_feedback_items': resource.ai_feedback_items or None,
            'ai_feedback_links': resource.ai_feedback_links or None,
        }

        saved = dict(resource.ai_saved_responses or {})
        saved[key] = entry
        resource.sudo().write({
            'ai_saved_responses': saved,
            'ai_selected_response_key': key,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Response Saved'),
                'message': _('AI response "%s" has been saved.') % self.response_name,
                'type': 'success',
                'sticky': False,
            },
        }
