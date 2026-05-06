from odoo import _, models
from odoo.exceptions import UserError


class APSResourceAISavedResponses(models.Model):
    _inherit = 'aps.resources'

    # ------------------------------------------------------------------
    # Button actions – AI saved responses
    # ------------------------------------------------------------------

    def action_ai_save_response(self):
        """Open a wizard to name and save the current AI test response."""
        self.ensure_one()
        if not self.ai_feedback:
            raise UserError(
                _('There is no AI response to save. Please run the AI test first.')
            )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Save AI Response'),
            'res_model': 'aps.ai.save.response.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': self._name,
            },
        }

    def action_ai_load_response(self):
        """Load the selected saved AI response into the resource test-prompt fields."""
        self.ensure_one()
        key = self.ai_selected_response_key
        if not key:
            raise UserError(_('Please select a saved response to load.'))

        saved = self.ai_saved_responses or {}
        entry = saved.get(key)
        if not entry:
            raise UserError(
                _('The selected saved response could not be found. It may have been deleted.')
            )

        self.sudo().write({
            'ai_answer': entry.get('ai_answer') or False,
            'ai_feedback': entry.get('ai_feedback') or False,
            'ai_score': entry.get('ai_score') or 0.0,
            'ai_score_comment': entry.get('ai_score_comment') or False,
            'ai_answer_chunks': entry.get('ai_answer_chunks') or False,
            'ai_answer_chunked_html': entry.get('ai_answer_chunked_html') or False,
            'ai_feedback_items': entry.get('ai_feedback_items') or False,
            'ai_feedback_links': entry.get('ai_feedback_links') or False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Response Loaded'),
                'message': _('AI response "%s" has been loaded.') % entry.get('name', key),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_ai_delete_response(self):
        """Delete the selected saved AI response from the JSON store."""
        self.ensure_one()
        key = self.ai_selected_response_key
        if not key:
            raise UserError(_('Please select a saved response to delete.'))

        saved = dict(self.ai_saved_responses or {})
        entry = saved.get(key)
        if not entry:
            raise UserError(
                _('The selected saved response could not be found. It may have already been deleted.')
            )

        name = entry.get('name', key)
        del saved[key]

        # Clear the selection if the deleted entry was selected
        self.sudo().write({
            'ai_saved_responses': saved or False,
            'ai_selected_response_key': False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Response Deleted'),
                'message': _('AI response "%s" has been deleted.') % name,
                'type': 'warning',
                'sticky': False,
            },
        }
