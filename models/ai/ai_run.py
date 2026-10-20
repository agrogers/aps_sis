import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class APSAIRun(models.Model):
    _name = 'aps.ai.run'
    _description = 'APEX AI Background Run'
    _rec_name = 'display_name'
    _inherit = ['aps.ai.run.mixin']
    _order = 'create_date desc, id desc'

    import_id = fields.Many2one('aps.exam.paper.import', ondelete='cascade', readonly=True)
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
    queued_for_dispatch = fields.Boolean(default=False, readonly=True, copy=False, index=True)
    override_model_id = fields.Many2one('aps.ai.model', string='Override Model', readonly=True, ondelete='set null')
    processor_key = fields.Selection(
        [
            ('standard', 'Standard AI Marking'),
            ('submission_ocr', 'Submission OCR'),
        ],
        default='standard', required=True, readonly=True,
    )
    fingerprint = fields.Char(readonly=True, copy=False, index=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)
    related_record_id = fields.Integer(compute='_compute_related_record_id')

    @api.depends('import_id', 'submission_id', 'resource_id')
    def _compute_related_record_id(self):
        for record in self:
            target = record.import_id or record.submission_id or record.resource_id
            record.related_record_id = target.id if target else False

    def action_view_related_runs(self):
        self.ensure_one()
        if self.import_id:
            target_field = 'import_id'
            target_record = self.import_id
        elif self.submission_id:
            target_field = 'submission_id'
            target_record = self.submission_id
        elif self.resource_id:
            target_field = 'resource_id'
            target_record = self.resource_id
        else:
            return False

        return {
            'type': 'ir.actions.act_window',
            'name': _('Other AI Runs for %s') % target_record.display_name,
            'res_model': 'aps.ai.run',
            'views': [[False, 'list'], [False, 'form']],
            'domain': [
                (target_field, '=', target_record.id),
                ('id', '!=', self.id),
            ],
            'target': 'current',
        }

    @api.depends('submission_id.display_name', 'resource_id.display_name', 'state', 'create_date', 'processor_key')
    def _compute_display_name(self):
        state_labels = dict(self._fields['state'].selection)
        for record in self:
            if record.processor_key != 'standard':
                subject_label = record._get_processor_display_name()
            elif record.resource_id:
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

    @api.model
    def cron_dispatch_automatic_runs(self, limit=20):
        return self.env['aps.ai.quick.run'].sudo().cron_dispatch_queued_ai_runs(limit=limit)

    def _get_processor_display_name(self):
        return _('AI Job')

    def _get_ai_queue_key(self):
        self.ensure_one()
        if self.submission_id and self.submission_id.student_id:
            return 'student:res.partner:%s' % self.submission_id.student_id.id
        if self.import_id:
            return 'record:aps.exam.paper.import:%s' % self.import_id.id
        if self.resource_id:
            return 'record:aps.resources:%s' % self.resource_id.id
        return super()._get_ai_queue_key()

    def _on_ai_queue_run_start(self):
        super()._on_ai_queue_run_start()
        self.ensure_one()
        if not self.submission_id.exists():
            return
        submission = self.submission_id.sudo()
        if self.processor_key == 'submission_ocr':
            if submission._get_submission_ocr_fingerprint() != self.fingerprint:
                self.write({
                    'state': 'failed',
                    'status_message': _('Skipped because the answer changed.'),
                    'error_message': _('A newer answer superseded this OCR run.'),
                    'finished_at': fields.Datetime.now(),
                })
                submission._queue_submission_answer_ocr()
                return
            submission.write({'submission_ocr_state': 'running'})
            return
        if submission._has_pending_submission_ocr():
            self.write({
                'state': 'failed',
                'status_message': _('Waiting for submission OCR.'),
                'error_message': _('The marking run was stopped because required OCR is not complete.'),
                'finished_at': fields.Datetime.now(),
            })
            if self.request_origin == 'automatic':
                submission.write({
                    'ai_auto_mark_state': 'pending',
                    'ai_auto_mark_run_id': False,
                })
            return
        if self.request_origin == 'automatic' and submission.ai_last_model_id:
            self.write({
                'state': 'failed',
                'status_message': _('Skipped before processing.'),
                'error_message': _('The submission was already marked before this run started.'),
                'finished_at': fields.Datetime.now(),
            })
            submission.write({'ai_auto_mark_state': 'completed'})
            return
        if self.request_origin == 'automatic' and not submission._is_auto_ai_marking_enabled():
            self.write({
                'state': 'failed',
                'status_message': _('Skipped before processing.'),
                'error_message': _('Automatic AI marking is no longer enabled for this submission.'),
                'finished_at': fields.Datetime.now(),
            })
            submission._reset_auto_ai_marking_state()
            return
        if (
            self.request_origin == 'automatic'
            and submission._get_ai_context_content_status(submission.answer, student_answer=True) == 'absent'
        ):
            self.write({
                'state': 'failed',
                'status_message': _('Skipped before processing.'),
                'error_message': _('The submission no longer has an answer to mark.'),
                'finished_at': fields.Datetime.now(),
            })
            submission.write({
                'ai_auto_mark_state': 'pending',
                'ai_auto_mark_attempt_count': max(0, submission.ai_auto_mark_attempt_count - 1),
            })
            return
        content_preflight = submission._get_ai_marking_content_preflight()
        if content_preflight:
            self.write({
                'state': 'failed',
                'status_message': _('Marking context is missing.'),
                'error_message': content_preflight['error_text'],
                'finished_at': fields.Datetime.now(),
            })
            feedback_html = content_preflight['feedback_html']
            if submission.ai_action == 'mark_scanned_exam' and submission.feedback:
                feedback_html = '%s<hr/>%s' % (submission.feedback, feedback_html)
            submission.write({'feedback': feedback_html})
            if self.request_origin == 'automatic':
                submission.write({
                    'ai_auto_mark_state': 'failed',
                    'ai_auto_mark_last_error': content_preflight['error_text'],
                    'ai_auto_mark_run_id': self.id,
                })
            return
        if self.request_origin != 'automatic':
            return
        progress_values = {
            'ai_auto_mark_state': 'running',
            'ai_auto_mark_run_id': self.id,
        }
        if submission.ai_action != 'mark_scanned_exam' or not submission.feedback:
            progress_values['feedback'] = submission._build_auto_ai_progress_feedback(self.attempt_number)
        submission.write(progress_values)
        submission._post_auto_ai_note(
            _('Automatic AI marking attempt %s has started.') % self.attempt_number
        )

    def _on_ai_queue_run_failure(self, error):
        super()._on_ai_queue_run_failure(error)
        self.ensure_one()
        if self.processor_key == 'submission_ocr' and self.submission_id.exists():
            submission = self.submission_id.sudo()
            if submission.submission_ocr_fingerprint == self.fingerprint:
                submission.write({
                    'submission_ocr_state': 'failed',
                    'submission_ocr_error': str(error),
                })
                submission._apply_deferred_submission_actions()
                submission._queue_auto_ai_marking_after_submit()
            return
        if self.request_origin == 'automatic' and self.submission_id.exists():
            self.submission_id.sudo()._handle_auto_ai_run_failure(self, str(error))

    def _process_background(self):
        self.ensure_one()
        if self.state not in ('queued', 'running'):
            return

        if self.processor_key == 'submission_ocr':
            self._process_submission_ocr_background()
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
            if self.processor_key != 'standard':
                self._process_specialised_background(started_perf)
            elif self.resource_id or self.submission_id:
                self._process_background_record(started_perf)
            else:
                raise UserError(_('This standard AI run is not linked to a resource or submission.'))
        except Exception as exc:
            from .utils import _exception_to_text
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            error_text = _exception_to_text(exc)
            self._recover_background_failure(exc, started_perf)
            if self.request_origin == 'automatic' and self.submission_id.exists():
                self.submission_id.sudo()._handle_auto_ai_run_failure(self, error_text)
                self._commit_background_work()

    def _process_specialised_background(self, started_perf):
        raise UserError(_('No processor is registered for AI run type %s.') % self.processor_key)

    def _process_submission_ocr_background(self):
        self.ensure_one()
        submission = self.submission_id.sudo()
        started_perf = time.perf_counter()
        started_at = fields.Datetime.now()
        self._write_progress({
            'state': 'running',
            'status_message': _('Transcribing the submitted answer...'),
            'started_at': started_at,
            'finished_at': False,
            'error_message': False,
        })
        outcome = 'failed'
        error_text = False
        try:
            if not submission.exists():
                raise UserError(_('The submission for this OCR run no longer exists.'))
            if submission._get_submission_ocr_fingerprint() != self.fingerprint:
                outcome = 'failed'
                error_text = _('The answer changed before OCR started.')
            else:
                applied = submission._process_answer_image_ocr(expected_fingerprint=self.fingerprint)
                outcome = 'succeeded' if applied else 'failed'
                if not applied:
                    error_text = _('OCR did not return transcription text.')
        except Exception as exc:
            error_text = str(exc)
            _logger.exception('Background submission OCR failed for submission %s', submission.id)

        if submission.exists() and submission.submission_ocr_fingerprint == self.fingerprint:
            submission.write({
                'submission_ocr_state': outcome,
                'submission_ocr_error': error_text,
            })
            submission._apply_deferred_submission_actions()
            submission._queue_auto_ai_marking_after_submit()

        self._write_progress({
            'state': 'completed' if outcome == 'succeeded' else 'failed',
            'status_message': _('Completed.') if outcome == 'succeeded' else _('OCR attempt failed.'),
            'result_message': _('A text version was added to the submission.') if outcome == 'succeeded' else False,
            'error_message': error_text,
            'finished_at': fields.Datetime.now(),
            'duration_ms': int((time.perf_counter() - started_perf) * 1000),
        })

    def _process_background_record(self, started_perf):
        self.ensure_one()
        record = (self.resource_id or self.submission_id).with_user(self.requested_by_id)
        is_resource = record._name == 'aps.resources'
        target_label = _('resource') if is_resource else _('submission')
        self._write_progress({'status_message': _('Waiting for the AI provider response...')})
        result = record._generate_ai_feedback_result(ai_run=self)
        self.invalidate_recordset(['state'])
        if self.state not in ('queued', 'running'):
            return
        if (
            not is_resource
            and record._has_pending_submission_ocr()
        ):
            error_text = _('The answer requires OCR before it can be marked.')
            self._write_progress({
                'state': 'failed',
                'status_message': _('Stopped because submission OCR is pending.'),
                'error_message': error_text,
                'finished_at': fields.Datetime.now(),
                'duration_ms': int((time.perf_counter() - started_perf) * 1000),
            })
            if self.request_origin == 'automatic':
                record.sudo().write({
                    'ai_auto_mark_state': 'pending',
                    'ai_auto_mark_attempt_count': max(0, record.ai_auto_mark_attempt_count - 1),
                    'ai_auto_mark_run_id': False,
                })
            return
        result['reasoning_text'] = result.get('reasoning_text') or self.thinking_text or ''
        self._write_progress({
            'status_message': _('Writing AI feedback to the %s...') % target_label,
        })
        record._apply_ai_feedback_result(result)
        self._commit_background_work()
        record._on_ai_feedback_run_success(
            result,
            request_origin=self.request_origin,
            run=self,
        )
        self._commit_background_work()
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
            'thinking_text': result.get('reasoning_text') or self.thinking_text or False,
            'response_preview': result.get('raw_content') or self.response_preview or False,
        })
