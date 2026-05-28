import time

from odoo import _, api, fields, models


class APSAIRun(models.Model):
    _name = 'aps.ai.run'
    _description = 'APEX AI Background Run'
    _inherit = ['aps.ai.run.mixin']
    _order = 'create_date desc, id desc'

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
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('submission_id.display_name', 'resource_id.display_name', 'state', 'create_date')
    def _compute_display_name(self):
        state_labels = dict(self._fields['state'].selection)
        for record in self:
            if record.resource_id:
                subject_label = record.resource_id.display_name or _('Resource')
            else:
                subject_label = record.submission_id.display_name or _('Submission')
            state_label = state_labels.get(record.state, record.state or _('Unknown'))
            created = fields.Datetime.to_string(record.create_date) if record.create_date else ''
            record.display_name = '%s - %s%s' % (
                subject_label,
                state_label,
                (' - %s' % created) if created else '',
            )

    def _process_background(self):
        self.ensure_one()
        if self.state not in ('queued', 'running'):
            return

        started_at = fields.Datetime.now()
        started_perf = time.perf_counter()
        self._write_progress({
            'state': 'running',
            'status_message': _('Preparing AI marking...'),
            'started_at': started_at,
            'finished_at': False,
            'result_message': False,
            'error_message': False,
            'thinking_text': False,
            'response_preview': False,
            'ai_model_id': False,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'estimated_cost': 0.0,
            'duration_ms': 0,
        })

        try:
            if self.resource_id:
                self._process_background_resource(started_perf)
            else:
                self._process_background_submission(started_perf)
        except Exception as exc:
            from .utils import _exception_to_text
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            self._write_progress({
                'state': 'failed',
                'status_message': _('Failed.'),
                'error_message': _exception_to_text(exc),
                'finished_at': fields.Datetime.now(),
                'duration_ms': duration_ms,
            })
            if self.request_origin == 'automatic' and self.submission_id.exists():
                self.submission_id.sudo()._handle_auto_ai_run_failure(self, _exception_to_text(exc))

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


