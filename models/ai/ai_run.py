import time

from odoo import _, api, fields, models
from odoo.tools import html2plaintext


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
        [('standard', 'Standard AI Marking')],
        default='standard', required=True, readonly=True,
    )
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
        limit = max(0, int(limit or 0))
        if not limit:
            return 0

        self.env.cr.execute(
            f"""
                SELECT id
                  FROM {self._table}
                 WHERE state = 'queued'
                   AND queued_for_dispatch IS TRUE
                 ORDER BY create_date, id
                 LIMIT %s
                 FOR UPDATE SKIP LOCKED
            """,
            [limit],
        )
        run_ids = [row[0] for row in self.env.cr.fetchall()]
        runs = self.sudo().browse(run_ids)
        dispatched = 0

        for run in runs:
            submission = run.submission_id.sudo()
            if not submission.exists():
                run.write({
                    'state': 'failed',
                    'status_message': _('Skipped before processing.'),
                    'error_message': _('The linked submission no longer exists.'),
                    'finished_at': fields.Datetime.now(),
                })
                continue

            if submission.ai_last_model_id:
                run.write({
                    'state': 'failed',
                    'status_message': _('Skipped before processing.'),
                    'error_message': _('The submission was already marked before this run started.'),
                    'finished_at': fields.Datetime.now(),
                })
                submission.write({'ai_auto_mark_state': 'completed'})
                continue

            if not submission._is_auto_ai_marking_enabled():
                run.write({
                    'state': 'failed',
                    'status_message': _('Skipped before processing.'),
                    'error_message': _('Automatic AI marking is no longer enabled for this submission.'),
                    'finished_at': fields.Datetime.now(),
                })
                submission._reset_auto_ai_marking_state()
                continue

            if not html2plaintext(submission.answer or '').strip():
                run.write({
                    'state': 'failed',
                    'status_message': _('Skipped before processing.'),
                    'error_message': _('The submission no longer has an answer to mark.'),
                    'finished_at': fields.Datetime.now(),
                })
                submission.write({
                    'ai_auto_mark_state': 'pending',
                    'ai_auto_mark_attempt_count': max(0, submission.ai_auto_mark_attempt_count - 1),
                })
                continue

            submission.write({
                'ai_auto_mark_state': 'running',
                'ai_auto_mark_run_id': run.id,
                'feedback': submission._build_auto_ai_progress_feedback(run.attempt_number),
            })
            submission._post_auto_ai_note(
                _('Automatic AI marking attempt %s has started.') % run.attempt_number
            )
            run.write({
                'state': 'running',
                'status_message': _('Preparing AI marking...'),
                'started_at': fields.Datetime.now(),
            })
            run._queue_background_processing()
            dispatched += 1

        return dispatched

    def _get_processor_display_name(self):
        return _('AI Job')

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
            if self.processor_key != 'standard':
                self._process_specialised_background(started_perf)
            elif self.resource_id:
                self._process_background_resource(started_perf)
            else:
                self._process_background_submission(started_perf)
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
        self._commit_background_work()
        submission.sudo()._finalize_ai_marking_success(
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
            'response_preview': result.get('raw_content') or self.response_preview or False,
        })

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
            'response_preview': result.get('raw_content') or self.response_preview or False,
        })


