from odoo import _, api, fields, models


class APSAIRun(models.Model):
    _inherit = 'aps.ai.run'

    submission_id = fields.Many2one('aps.resource.submission', ondelete='cascade', readonly=True)
    resource_id = fields.Many2one('aps.resources', ondelete='cascade', readonly=True)
    request_origin = fields.Selection(
        [('manual', 'Manual'), ('automatic', 'Automatic')],
        string='Request Origin',
        default='manual',
        required=True,
        readonly=True,
    )
    attempt_number = fields.Integer(readonly=True)
    override_model_id = fields.Many2one('aps.ai.model', string='Override Model', readonly=True, ondelete='set null')
    def _get_run_subject_label(self):
        self.ensure_one()
        if self.resource_id:
            return self.resource_id.display_name or _('Resource')
        return self.submission_id.display_name or _('Submission')

    def _process_background(self):
        self.ensure_one()
        if self.state not in ('queued', 'running'):
            return

        super()._process_background()

    def _process_background_domain(self, started_perf):
        if self.resource_id:
            self._process_background_resource(started_perf)
        else:
            self._process_background_submission(started_perf)

    def _process_background_submission(self, started_perf):
        self.ensure_one()
        submission = self.submission_id.with_user(self.requested_by_id)
        self._write_progress({'status_message': _('Waiting for the AI provider response...')})
        ai_model = (
            self.override_model_id.with_user(self.requested_by_id)
            if self.override_model_id
            else self.env['aps.ai.model'].with_user(self.requested_by_id)
        )
        result = ai_model.generate_multi_model_feedback(
            submission,
            ai_run=self,
        )
        self._write_progress({'status_message': _('Writing AI feedback to the submission...')})
        submission._apply_ai_feedback_result(result)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        self._write_progress({
            'state': 'completed',
            'status_message': _('Completed.'),
            'result_message': _('AI feedback was added using %s.') % (
                result.get('model_name') or _('the configured AI model')
            ),
            'finished_at': fields.Datetime.now(),
            'duration_ms': duration_ms,
            'ai_model_id': result.get('model_id') or False,
            'prompt_tokens': result.get('prompt_tokens') or 0,
            'completion_tokens': result.get('completion_tokens') or 0,
            'estimated_cost': result.get('estimated_cost') or 0.0,
            'response_preview': result.get('raw_content') or self.response_preview or False,
        })
        submission.sudo()._finalize_ai_marking_success(
            result,
            request_origin=self.request_origin,
            run=self,
        )

    def _process_background_resource(self, started_perf):
        self.ensure_one()
        resource = self.resource_id.with_user(self.requested_by_id)
        self._write_progress({'status_message': _('Waiting for the AI provider response...')})
        result = self.env['aps.ai.model'].with_user(self.requested_by_id).generate_multi_model_feedback(
            resource,
            ai_run=self,
        )
        self._write_progress({'status_message': _('Writing AI feedback to the resource...')})
        resource._apply_ai_feedback_result(result)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        self._write_progress({
            'state': 'completed',
            'status_message': _('Completed.'),
            'result_message': _('AI feedback was added using %s.') % (
                result.get('model_name') or _('the configured AI model')
            ),
            'finished_at': fields.Datetime.now(),
            'duration_ms': duration_ms,
            'ai_model_id': result.get('model_id') or False,
            'prompt_tokens': result.get('prompt_tokens') or 0,
            'completion_tokens': result.get('completion_tokens') or 0,
            'estimated_cost': result.get('estimated_cost') or 0.0,
            'response_preview': result.get('raw_content') or self.response_preview or False,
        })


