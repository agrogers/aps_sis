from odoo import _, models
from odoo.exceptions import UserError


class APSResourceAIFeedback(models.Model):
    _name = 'aps.resources'
    _inherit = ['aps.resources', 'aps.ai.feedback.storage.mixin']

    def _get_ai_run_link_field(self):
        return 'resource_id'

    def _get_ai_feedback_storage_field_name(self):
        self.ensure_one()
        return 'ai_feedback'

    def _build_ai_feedback_ctx(self, include_reasoning=False):
        """Return the standardised AI feedback context dict for this resource.

        Used by the generic engine (``aps.ai.model.generate_feedback``).
        ``student_answer_html`` is taken from the test-answer field ``ai_answer``.
        """
        self.ensure_one()
        return {
            'instructions': self.ai_instructions or '',
            'out_of_marks': self.marks if self.marks and self.marks > 0 else False,
            'use_question': bool(self.ai_use_question),
            'question': self.question or '',
            'use_model_answer': bool(self.ai_use_model_answer),
            'model_answer': self.answer or '',
            'use_note': False,
            'notes': '',
            'student_answer_html': self.ai_answer or '',
            'ai_targeted_feedback': bool(self.ai_targeted_feedback),
            'include_reasoning': include_reasoning,
            'empty_answer_error': _(
                'Please enter a test answer in the "Test Answer" field before running the AI mark.'
            ),
            'prompt_ids': self.ai_active_prompts,
        }

    def _get_ai_feedback_result_write_vals(self, result):
        vals = super()._get_ai_feedback_result_write_vals(result)
        score = result.get('score')
        vals['ai_score'] = float(score) if score is not None else 0.0
        vals['ai_score_comment'] = result.get('score_comment') or False
        return vals

    def _apply_ai_feedback_result(self, result):
        self.ensure_one()
        self.sudo().write(self._get_ai_feedback_result_write_vals(result))

    def action_preview_prompt(self):
        """Open a popup showing the fully compiled prompt that would be sent to the AI."""
        self.ensure_one()
        if self.ai_action == 'none':
            raise UserError(_('AI Action must not be "None" to preview the prompt.'))

        AIModel = self.env['aps.ai.model']
        candidates = AIModel._get_generation_candidates(resource=self)
        if not candidates:
            raise UserError(_('No enabled AI models are configured.'))
        model = candidates[0]

        # Use ai_dry_run=True so _perform_request raises DryRunPayloadError
        # instead of calling the provider. We duck-type the exception to avoid
        # a cross-addon import of DryRunPayloadError.
        payload = None
        try:
            model.with_context(ai_dry_run=True)._run_feedback(self)
        except Exception as exc:
            if hasattr(exc, 'payload'):
                payload = exc.payload
            else:
                raise

        if not payload:
            raise UserError(_('Could not assemble the prompt. Check that this resource has a valid AI configuration.'))

        messages = payload.get('messages', [])
        lines = []
        for msg in messages:
            role = (msg.get('role') or '').upper()
            content = msg.get('content') or ''
            lines.append('─' * 60)
            lines.append(f'[{role}]')
            lines.append(content)
        prompt_text = '\n'.join(lines)

        wizard = self.env['aps.prompt.preview.wizard'].create({'prompt_text': prompt_text})
        return {
            'type': 'ir.actions.act_window',
            'name': _('AI Prompt Preview'),
            'res_model': 'aps.prompt.preview.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
