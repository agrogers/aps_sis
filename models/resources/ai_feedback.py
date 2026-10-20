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

    def _get_freeform_assessment_prompts(self):
        self.ensure_one()
        return self.ai_prompt_ids.filtered(
            lambda prompt: (
                prompt.enabled
                and 'freeform assessment' in (prompt.prompt_name or '').casefold()
            )
        ).sorted(key=lambda prompt: (prompt.sequence or 0, prompt.id))

    def _build_ai_feedback_ctx(self, include_reasoning=False, student_answer_html=None, out_of_marks=None):
        """Return the standardised AI feedback context dict for this resource.

        Used by the generic engine (``aps.ai.model.generate_feedback``).
        ``student_answer_html`` defaults to the test-answer field ``ai_answer``;
        submissions pass their answer to use the same marking configuration.
        """
        self.ensure_one()
        student_answer = (
            self.ai_answer or ''
            if student_answer_html is None
            else student_answer_html or ''
        )
        if not student_answer and self.env.context.get('ai_preview_prompt'):
            student_answer = '<p>[Sample student answer — preview only]</p>'
        marking_prompts = self._get_ai_feedback_marking_prompts()
        maximum = self.marks if out_of_marks is None else out_of_marks
        return {
            'instructions': self.ai_instructions or '',
            'out_of_marks': maximum if maximum and maximum > 0 else False,
            'use_question': bool(self.ai_use_question),
            'question': self.question or '',
            'use_model_answer': bool(
                self.ai_use_model_answer or self.ai_action == 'mark_submission_use_answer'
            ),
            'model_answer': self.answer or '',
            'use_note': bool(self.ai_use_notes),
            'notes': self.notes or '',
            'student_answer_html': student_answer,
            'ai_targeted_feedback': bool(self.ai_targeted_feedback),
            'include_reasoning': include_reasoning,
            'empty_answer_error': _('The marking request has no student answer to mark.'),
            'prompt_ids': marking_prompts,
            'image_prompt_names': marking_prompts.mapped('prompt_name'),
            'image_sources': {
                'student_answer': student_answer,
                'question': self.question or '',
                'model_answer': self.answer or '',
                'instructions': self.ai_instructions or '',
                'notes': self.notes or '',
            },
        }

    def _get_ai_feedback_result_write_vals(self, result):
        vals = super()._get_ai_feedback_result_write_vals(result)
        score = result.get('score')
        vals['ai_score'] = self._normalize_ai_feedback_score(score) if score is not None else 0.0
        vals['ai_score_comment'] = result.get('score_comment') or False
        return vals

    def _write_ai_feedback_result(self, vals):
        self.ensure_one()
        self.sudo().write(vals)

    def _on_ai_feedback_run_success(self, result, request_origin, run):
        self.ensure_one()
        if result.get('sample_comparison_audit_html'):
            self._post_sample_comparison_audit_note(result)
        else:
            self._post_sample_scaling_audit_note(result)

    def action_preview_prompt(self):
        """Open a popup showing the fully compiled prompt that would be sent to the AI."""
        self.ensure_one()
        if self.ai_action == 'none':
            raise UserError(_('AI Action must not be "None" to preview the prompt.'))

        if self.ai_action == 'mark_scanned_exam':
            prompts = self._get_freeform_assessment_prompts().filtered(
                lambda prompt: (prompt.prompt or '').strip()
            )
            instructions = '\n\n'.join(
                '[%s]\n%s' % (prompt.prompt_name, prompt.prompt.strip())
                for prompt in prompts
            )
            submission_model = self.env['aps.resource.submission']
            prompt_text = '\n\n'.join([
                'PAGE ANALYSIS SYSTEM PROMPT',
                submission_model._build_freeform_assessment_system_prompt(instructions, 'page'),
                'PAGE ANALYSIS USER MESSAGE',
                'Analyze one page image at a time. The request includes prior page analyses as text context.',
                'FINAL AGGREGATION SYSTEM PROMPT',
                submission_model._build_freeform_assessment_system_prompt(instructions, 'final'),
                'FINAL AGGREGATION USER MESSAGE',
                '[The complete accumulated page-by-page feedback is inserted here.]',
            ])
            wizard = self.env['aps.prompt.preview.wizard'].create({'prompt_text': prompt_text})
            return {
                'type': 'ir.actions.act_window',
                'name': _('AI Prompt Preview'),
                'res_model': 'aps.prompt.preview.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        AIModel = self.env['aps.ai.model']
        context = self._build_ai_feedback_ctx(include_reasoning=False)
        candidates = AIModel._get_generation_candidates(
            resource=self,
            require_vision=AIModel._feedback_context_requires_vision(context),
        )
        if not candidates:
            if AIModel._feedback_context_requires_vision(context):
                raise UserError(_(
                    'Images are present, but no enabled vision-capable AI model is configured.'
                ))
            raise UserError(_('No enabled AI models are configured.'))
        model = candidates[0]

        # Use ai_dry_run=True so _perform_request raises DryRunPayloadError
        # instead of calling the provider. We duck-type the exception to avoid
        # a cross-addon import of DryRunPayloadError.
        # ai_preview_prompt=True tells _build_ai_feedback_ctx to supply a dummy
        # student answer when ai_answer is empty, so the prompt can be previewed
        # without requiring a test answer to be entered first.
        payload = None
        try:
            model.with_context(ai_dry_run=True, ai_preview_prompt=True)._run_feedback(self)
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
            if isinstance(content, list):
                preview_parts = []
                for part in content:
                    if (part or {}).get('type') == 'image_url':
                        preview_parts.append('[image content redacted from preview]')
                    else:
                        preview_parts.append((part or {}).get('text') or '')
                content = '\n'.join(preview_parts)
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
