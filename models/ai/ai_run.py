import logging
import threading
import time

from odoo import _, api, fields, models

from .utils import _run_ai_background_job

_logger = logging.getLogger(__name__)


class APSAIRun(models.Model):
    _name = 'aps.ai.run'
    _description = 'APEX AI Background Run'
    _order = 'create_date desc, id desc'

    submission_id = fields.Many2one('aps.resource.submission', ondelete='cascade', readonly=True)
    resource_id = fields.Many2one('aps.resources', ondelete='cascade', readonly=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', required=True, readonly=True)
    request_origin = fields.Selection(
        [('manual', 'Manual'), ('automatic', 'Automatic')],
        string='Request Origin',
        default='manual',
        required=True,
        readonly=True,
    )
    attempt_number = fields.Integer(readonly=True)
    state = fields.Selection(
        [
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='queued',
        required=True,
        readonly=True,
    )
    status_message = fields.Char(readonly=True)
    result_message = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)
    thinking_text = fields.Text(readonly=True)
    response_preview = fields.Text(readonly=True)
    ai_model_id = fields.Many2one('aps.ai.model', string='AI Model', readonly=True, ondelete='set null')
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    estimated_cost = fields.Float(readonly=True, digits=(16, 6))
    duration_ms = fields.Integer(readonly=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
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

    def _queue_background_processing(self):
        self.ensure_one()
        db_name = self.env.cr.dbname
        run_id = self.id
        user_id = self.requested_by_id.id
        context = dict(self.env.context or {})

        @self.env.cr.postcommit.add
        def _start_background_run():
            thread = threading.Thread(
                target=_run_ai_background_job,
                args=(db_name, run_id, user_id, context),
                daemon=True,
                name='aps_ai_run_%s' % run_id,
            )
            thread.start()

    def _write_progress(self, values):
        self.ensure_one()
        self.sudo().write(values)
        self.env.cr.commit()

    def _serialize_status(self):
        self.ensure_one()
        return {
            'id': self.id,
            'state': self.state,
            'status_message': self.status_message or '',
            'result_message': self.result_message or '',
            'error_message': self.error_message or '',
            'thinking_text': self.thinking_text or '',
            'response_preview': self.response_preview or '',
            'duration_ms': self.duration_ms or 0,
            'prompt_tokens': self.prompt_tokens or 0,
            'completion_tokens': self.completion_tokens or 0,
            'estimated_cost': self.estimated_cost or 0.0,
            'started_at': fields.Datetime.to_string(self.started_at) if self.started_at else False,
            'finished_at': fields.Datetime.to_string(self.finished_at) if self.finished_at else False,
            'ai_model_name': self.ai_model_id.display_name or False,
            'is_terminal': self.state in ('completed', 'failed'),
        }

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
        result = self.env['aps.ai.model'].with_user(self.requested_by_id).generate_submission_feedback(
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
        result = self.env['aps.ai.model'].with_user(self.requested_by_id).generate_resource_test_feedback(
            resource,
            ai_run=self,
        )
        self._write_progress({'status_message': _('Writing AI feedback to the resource...')})
        resource.sudo().write({'ai_feedback': result.get('feedback_html') or ''})
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

    def _build_stream_callback(self):
        self.ensure_one()
        last_publish = {'ts': 0.0, 'thinking': '', 'content': ''}

        def _callback(thinking_text='', content_text=''):
            now = time.perf_counter()
            thinking_text_value = (thinking_text or '').strip()
            content_text_value = (content_text or '').strip()
            should_publish = (
                now - last_publish['ts'] >= 1.0
                or abs(len(thinking_text_value) - len(last_publish['thinking'])) >= 200
                or abs(len(content_text_value) - len(last_publish['content'])) >= 200
            )
            if not should_publish:
                return

            values = {}
            if thinking_text_value != last_publish['thinking']:
                values['thinking_text'] = thinking_text_value or False
            if content_text_value != last_publish['content']:
                values['response_preview'] = content_text_value or False
            if thinking_text_value:
                values['status_message'] = _('Streaming AI reasoning...')
            elif content_text_value:
                values['status_message'] = _('Streaming AI response...')
            if values:
                self._write_progress(values)
                last_publish['ts'] = now
                last_publish['thinking'] = thinking_text_value
                last_publish['content'] = content_text_value

        return _callback
