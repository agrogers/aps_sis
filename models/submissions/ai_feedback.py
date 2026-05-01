import logging
from html import escape

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .model import sentinel_zero


_logger = logging.getLogger(__name__)

_AUTO_MARK_ENABLED_ACTIONS = ('mark_submission', 'mark_submission_use_answer')
_AUTO_MARK_MAX_ATTEMPTS = 3
_AUI_SKIP_CHANNEL_FORWARD_CTX = 'aui_skip_channel_forward'


class APSResourceSubmissionAIFeedback(models.Model):
    _inherit = 'aps.resource.submission'

    ai_action = fields.Selection(related='resource_id.ai_action', readonly=True)
    ai_instructions = fields.Html(related='resource_id.ai_instructions', readonly=True)
    ai_prompt_ids = fields.Many2many('ai_prompts', related='resource_id.ai_prompt_ids', readonly=True)
    ai_use_model_answer = fields.Boolean(related='resource_id.ai_use_model_answer', readonly=True)
    ai_use_question = fields.Boolean(related='resource_id.ai_use_question', readonly=True)
    ai_use_notes = fields.Boolean(related='resource_id.ai_use_notes', readonly=True)
    ai_last_model_id = fields.Many2one('aps.ai.model', string='Last AI Model', readonly=True, copy=False)
    ai_last_prompt_tokens = fields.Integer(string='Last AI Prompt Tokens', readonly=True, copy=False)
    ai_last_completion_tokens = fields.Integer(string='Last AI Completion Tokens', readonly=True, copy=False)
    ai_last_estimated_cost = fields.Float(string='Last AI Estimated Cost', digits=(16, 6), readonly=True, copy=False)
    ai_auto_mark_state = fields.Selection(
        [
            ('idle', 'Idle'),
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('retry', 'Retry Scheduled'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        string='Automatic AI Marking',
        default='idle',
        readonly=True,
        copy=False,
    )
    ai_auto_mark_attempt_count = fields.Integer(string='Automatic AI Attempts', default=0, readonly=True, copy=False)
    ai_auto_mark_last_error = fields.Text(string='Automatic AI Error', readonly=True, copy=False)
    ai_auto_mark_run_id = fields.Many2one('aps.ai.run', string='Automatic AI Run', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._queue_auto_ai_marking_after_submit()
        return records

    def write(self, vals):
        state_changed = 'state' in vals
        result = super().write(vals)
        if state_changed:
            self._queue_auto_ai_marking_after_submit()
            self.filtered(lambda rec: rec.state != 'submitted')._reset_auto_ai_marking_state()
        return result

    def _validate_ai_marking_request(self):
        self.ensure_one()
        faculty = self._get_current_faculty()
        if not faculty:
            raise UserError(_('Only faculty members can mark submissions with AI.'))

        if self.ai_action in ('none'):
            raise UserError(_('AI marking is not enabled for this resource.'))

    def _is_auto_ai_marking_enabled(self):
        self.ensure_one()
        return self.state == 'submitted' and self.ai_action in _AUTO_MARK_ENABLED_ACTIONS

    def _reset_auto_ai_marking_state(self):
        records = self.filtered(
            lambda rec: rec.ai_auto_mark_state != 'idle'
            or rec.ai_auto_mark_attempt_count
            or rec.ai_auto_mark_last_error
            or rec.ai_auto_mark_run_id
        )
        if not records:
            return
        records.sudo().write({
            'ai_auto_mark_state': 'idle',
            'ai_auto_mark_attempt_count': 0,
            'ai_auto_mark_last_error': False,
            'ai_auto_mark_run_id': False,
        })

    def _queue_auto_ai_marking_after_submit(self):
        for record in self:
            if not record._is_auto_ai_marking_enabled():
                continue
            if record.ai_last_model_id or record.ai_auto_mark_state in ('pending', 'running', 'retry', 'completed'):
                continue
            record.sudo().write({
                'ai_auto_mark_state': 'pending',
                'ai_auto_mark_attempt_count': 0,
                'ai_auto_mark_last_error': False,
                'ai_auto_mark_run_id': False,
            })
            record._post_auto_ai_note(_('Automatic AI marking was queued when the submission was submitted.'))

    def _build_auto_ai_progress_feedback(self, attempt_number):
        dots = '.' * max(3, int(attempt_number or 1) + 2)
        message = _('This submission is being marked by AI%s') % dots
        detail = _('Automatic attempt %s of %s is in progress.') % (attempt_number, _AUTO_MARK_MAX_ATTEMPTS)
        return '<p><em>%s</em></p><p><em>%s</em></p>' % (message, detail)

    def _build_auto_ai_failure_feedback(self, error_text):
        message = _('Automatic AI marking failed after %s attempts.') % _AUTO_MARK_MAX_ATTEMPTS
        detail = escape(error_text or _('No error details were returned.'))
        return '<p><em>%s</em></p><p><strong>%s</strong></p>' % (message, detail)

    def _build_auto_ai_requeued_feedback(self):
        self.ensure_one()
        return '<p><em>%s</em></p>' % escape(
            _('Automatic AI marking has been manually requeued and will run on the next cron pass.')
        )

    def _post_auto_ai_note(self, body):
        self.ensure_one()
        self.with_context(**{_AUI_SKIP_CHANNEL_FORWARD_CTX: True}).message_post(
            body=Markup(body or ''),
            subtype_xmlid='mail.mt_note',
        )

    def _build_ai_completion_note_body(self, result, prefix_text=None):
        self.ensure_one()
        model_label = escape(result.get('model_name') or _('the configured AI model'))
        estimated_cost = float(result.get('estimated_cost') or 0.0)
        parts = []
        if prefix_text:
            parts.append('<p>%s</p>' % escape(prefix_text))
        parts.append('<p>%s</p>' % escape(_('This submission was marked by AI.')))
        parts.append('<ul>')
        parts.append('<li><strong>%s</strong> %s</li>' % (escape(_('Model:')), model_label))
        parts.append('<li><strong>%s</strong> %.6f</li>' % (escape(_('Estimated cost:')), estimated_cost))
        parts.append('</ul>')
        return ''.join(parts)

    def _get_ai_completion_prefix_text(self, request_origin):
        self.ensure_one()
        if request_origin == 'automatic':
            return _('Automatic AI marking completed successfully.')
        return _('Manual AI marking completed successfully.')

    def _finalize_ai_marking_success(self, result, request_origin='manual', run=None):
        self.ensure_one()
        if request_origin == 'automatic':
            self.sudo().write({
                'ai_auto_mark_state': 'completed',
                'ai_auto_mark_last_error': False,
                'ai_auto_mark_run_id': run.id if run else self.ai_auto_mark_run_id.id,
            })

        actor_record = self
        if run and run.requested_by_id:
            actor_record = self.with_user(run.requested_by_id)

        actor_record._post_auto_ai_note(
            actor_record._build_ai_completion_note_body(
                result,
                prefix_text=actor_record._get_ai_completion_prefix_text(request_origin),
            )
        )

        if request_origin == 'automatic':
            actor_record._send_auto_ai_success_dm()

    def _get_submission_url(self, student_view=False):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        if not base_url:
            return False
        view_xmlid = 'aps_sis.view_aps_resource_submission_form_for_students' if student_view else 'aps_sis.view_aps_resource_submission_form'
        view = self.env.ref(view_xmlid, raise_if_not_found=False)
        view_part = '&view_id=%s' % view.id if view else ''
        return '%s/web#id=%s&model=%s&view_type=form%s' % (base_url, self.id, self._name, view_part)

    def _send_auto_ai_success_dm(self):
        self.ensure_one()
        if not self.student_id:
            return
        student_partner = self.student_id
        author_partner = self.env.user.partner_id
        if not author_partner or author_partner == student_partner:
            return
        record_url = self._get_submission_url(student_view=True) or self._get_submission_url(student_view=False) or ''
        link_html = (
            '<a href="%s">%s</a>' % (record_url, escape(self.display_name or self.submission_name or _('submission')))
            if record_url else escape(self.display_name or self.submission_name or _('submission'))
        )
        body = _('<p>Your %s has been marked automatically and feedback is now available.</p>') % link_html
        try:
            channel = self.env['discuss.channel'].channel_get(
                partners_to=[author_partner.id, student_partner.id],
                pin=False,
            )
            channel.with_context(**{_AUI_SKIP_CHANNEL_FORWARD_CTX: True}).message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        except Exception:
            _logger.exception('Failed to send automatic AI completion DM for submission %s', self.id)

    def _notify_auto_ai_failure_to_managers(self, error_text):
        self.ensure_one()
        manager_group = self.env.ref('aps_sis.group_aps_manager', raise_if_not_found=False)
        manager_partners = manager_group.users.mapped('partner_id') if manager_group else self.env['res.partner']
        manager_partners = manager_partners.filtered(lambda partner: partner)
        if not manager_partners:
            return
        record_url = self._get_submission_url(student_view=False) or ''
        link_html = (
            '<a href="%s">%s</a>' % (record_url, escape(self.display_name or self.submission_name or _('submission')))
            if record_url else escape(self.display_name or self.submission_name or _('submission'))
        )
        body = _(
            '<p>Automatic AI marking failed for %s after %s attempts.</p><p><strong>Last error:</strong> %s</p>'
        ) % (link_html, _AUTO_MARK_MAX_ATTEMPTS, escape(error_text or _('No error details were returned.')))
        try:
            self.with_context(**{_AUI_SKIP_CHANNEL_FORWARD_CTX: True}).message_post(
                body=body,
                partner_ids=manager_partners.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        except Exception:
            _logger.exception('Failed to notify APEX managers about automatic AI failure for submission %s', self.id)

    def _get_ai_run_requested_by_id(self, request_origin):
        self.ensure_one()
        if request_origin == 'automatic':
            # Automatic runs execute as the cron user that is running the scheduler job.
            return self.env.user.id
        return self.env.user.id

    def _get_active_ai_run(self):
        self.ensure_one()
        return self.env['aps.ai.run'].sudo().search([
            ('submission_id', '=', self.id),
            ('state', 'in', ('queued', 'running')),
        ], limit=1, order='create_date desc, id desc')

    def _start_ai_marking_background_run(self, request_origin='manual', attempt_number=0):
        self.ensure_one()
        active_run = self._get_active_ai_run()
        if active_run:
            return active_run, False

        run = self.env['aps.ai.run'].sudo().create({
            'submission_id': self.id,
            'requested_by_id': self._get_ai_run_requested_by_id(request_origin),
            'state': 'queued',
            'status_message': _('Queued and waiting to start...'),
            'request_origin': request_origin,
            'attempt_number': attempt_number or 0,
        })
        if request_origin == 'automatic':
            self.sudo().write({'ai_auto_mark_run_id': run.id})
        run._queue_background_processing()
        return run, True

    def _start_automatic_ai_marking(self):
        self.ensure_one()
        if not self._is_auto_ai_marking_enabled() or self.ai_last_model_id:
            return False
        if self.ai_auto_mark_attempt_count >= _AUTO_MARK_MAX_ATTEMPTS:
            return False

        attempt_number = (self.ai_auto_mark_attempt_count or 0) + 1
        self.sudo().write({
            'ai_auto_mark_state': 'running',
            'ai_auto_mark_attempt_count': attempt_number,
            'ai_auto_mark_last_error': False,
            'feedback': self._build_auto_ai_progress_feedback(attempt_number),
        })
        self._post_auto_ai_note(
            _('Automatic AI marking attempt %s of %s has started.') % (attempt_number, _AUTO_MARK_MAX_ATTEMPTS)
        )
        run, _created = self._start_ai_marking_background_run(
            request_origin='automatic',
            attempt_number=attempt_number,
        )
        return run

    def action_requeue_auto_ai_marking(self):
        self.ensure_one()
        faculty = self._get_current_faculty()
        if not faculty:
            raise UserError(_('Only faculty members can requeue automatic AI marking.'))
        if not self._is_auto_ai_marking_enabled():
            raise UserError(_('Automatic AI marking is not enabled for this submission.'))

        active_run = self._get_active_ai_run()
        if active_run:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Automatic AI Marking In Progress'),
                    'message': _('Automatic AI marking is already running for this submission.'),
                    'type': 'info',
                }
            }

        self.sudo().write({
            'ai_last_model_id': False,
            'ai_last_prompt_tokens': 0,
            'ai_last_completion_tokens': 0,
            'ai_last_estimated_cost': 0.0,
            'ai_auto_mark_state': 'pending',
            'ai_auto_mark_attempt_count': 0,
            'ai_auto_mark_last_error': False,
            'ai_auto_mark_run_id': False,
            'feedback': self._build_auto_ai_requeued_feedback(),
        })
        self._post_auto_ai_note(_('Automatic AI marking was manually requeued.'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Automatic AI Marking Requeued'),
                'message': _('Automatic AI marking will run again on the next cron pass.'),
                'type': 'success',
            }
        }

    @api.model
    def cron_process_auto_ai_marking(self):
        submissions = self.search([
            ('state', '=', 'submitted'),
            ('ai_auto_mark_state', 'in', ('pending', 'retry', 'running')),
        ], order='write_date asc, id asc', limit=20)
        for submission in submissions:
            try:
                submission._cron_process_one_auto_ai_marking()
            except Exception:
                _logger.exception('Automatic AI marking cron failed for submission %s', submission.id)

    def _cron_process_one_auto_ai_marking(self):
        self.ensure_one()
        if not self._is_auto_ai_marking_enabled():
            self._reset_auto_ai_marking_state()
            return False
        if self.ai_last_model_id:
            self.sudo().write({
                'ai_auto_mark_state': 'completed',
                'ai_auto_mark_last_error': False,
            })
            return False

        active_run = self._get_active_ai_run()
        if active_run:
            if self.ai_auto_mark_state != 'running' or self.ai_auto_mark_run_id != active_run:
                self.sudo().write({
                    'ai_auto_mark_state': 'running',
                    'ai_auto_mark_run_id': active_run.id,
                })
            return active_run

        if self.ai_auto_mark_attempt_count >= _AUTO_MARK_MAX_ATTEMPTS:
            if self.ai_auto_mark_state != 'failed':
                self._handle_auto_ai_run_failure(None, self.ai_auto_mark_last_error or _('Automatic AI marking exceeded the retry limit.'))
            return False
        return self._start_automatic_ai_marking()

    def _handle_auto_ai_run_success(self, run, result):
        self.ensure_one()
        self._finalize_ai_marking_success(result, request_origin='automatic', run=run)

    def _handle_auto_ai_run_failure(self, run, error_text):
        self.ensure_one()
        error_text = error_text or _('The AI call failed without returning an error message.')
        vals = {
            'ai_auto_mark_last_error': error_text,
            'ai_auto_mark_run_id': run.id if run else self.ai_auto_mark_run_id.id,
        }
        if self.ai_auto_mark_attempt_count >= _AUTO_MARK_MAX_ATTEMPTS:
            vals.update({
                'ai_auto_mark_state': 'failed',
                'feedback': self._build_auto_ai_failure_feedback(error_text),
            })
            self.sudo().write(vals)
            self._post_auto_ai_note(
                _('Automatic AI marking failed after %s attempts. Managers have been notified. Last error: %s')
                % (_AUTO_MARK_MAX_ATTEMPTS, escape(error_text))
            )
            self._notify_auto_ai_failure_to_managers(error_text)
            return

        vals['ai_auto_mark_state'] = 'retry'
        self.sudo().write(vals)
        self._post_auto_ai_note(
            _('Automatic AI marking attempt %s of %s failed and will retry on the next cron run. Last error: %s')
            % (self.ai_auto_mark_attempt_count, _AUTO_MARK_MAX_ATTEMPTS, escape(error_text))
        )

    def _apply_ai_feedback_result(self, result):
        self.ensure_one()
        feedback_html = result.get('feedback_html') or '<p>No feedback was returned by the AI model.</p>'
        score = result.get('score')
        vals = {
            'feedback': feedback_html,
            'ai_last_model_id': result.get('model_id'),
            'ai_last_prompt_tokens': result.get('prompt_tokens') or 0,
            'ai_last_completion_tokens': result.get('completion_tokens') or 0,
            'ai_last_estimated_cost': result.get('estimated_cost') or 0.0,
        }

        if self.out_of_marks and self.out_of_marks > 0 and self.out_of_marks != sentinel_zero:
            if score is None:
                vals['feedback'] = '%s<p><em>No mark was returned by the AI model.</em></p>' % feedback_html
            else:
                vals['score'] = max(0.0, min(round(float(score), 2), self.out_of_marks))

        self.write(vals)

    def _build_ai_failure_notification(self, error_text):
        message = error_text or _('The AI call failed.')
        normalized_message = message.lower()
        if 'empty completion' in normalized_message or 'did not return the final answer' in normalized_message:
            message = _(
                '%s\n\nIf AI > Logs only shows connection tests, clear that filter or apply the Submission Feedback filter.'
            ) % message
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Marking Failed'),
                'message': message,
                'type': 'warning',
                'sticky': True,
            }
        }

    def action_mark_with_ai(self):
        self.ensure_one()
        self._validate_ai_marking_request()

        try:
            result = self.env['aps.ai.model'].generate_submission_feedback(self)
        except Exception as exc:
            error_text = exc.args[0] if getattr(exc, 'args', False) else str(exc)
            return self._build_ai_failure_notification(error_text)

        self._apply_ai_feedback_result(result)
        self._finalize_ai_marking_success(result, request_origin='manual')

        message = _('AI feedback was added using %s.') % (result.get('model_name') or _('the configured AI model'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Marking Complete'),
                'message': message,
                'type': 'success',
            }
        }

    def action_start_mark_with_ai(self):
        self.ensure_one()
        self._validate_ai_marking_request()

        active_run, created = self._start_ai_marking_background_run(request_origin='manual')
        if not created:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AI Marking In Progress'),
                    'message': _('AI marking is already running in the background for this submission.'),
                    'type': 'info',
                    'run_id': active_run.id,
                }
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Marking Started'),
                'message': _('AI marking is running in the background. You can close the progress dialog at any time.'),
                'type': 'info',
                'run_id': active_run.id,
            }
        }

    def action_get_ai_run_status(self, run_id):
        self.ensure_one()
        run = self.env['aps.ai.run'].sudo().browse(run_id)
        if not run.exists() or run.submission_id.id != self.id:
            raise UserError(_('The requested AI run does not belong to this submission.'))
        return run._serialize_status()