import copy
import json
import logging
import re
import time
from html import escape
from urllib import error as url_error
from urllib import request as url_request

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .utils import (
    _build_notification_action,
    _exception_to_text,
    _format_test_failure_message,
)

_logger = logging.getLogger(__name__)


class APSAIModel(models.Model):
    _name = 'aps.ai.model'
    _description = 'APEX AI Model'
    _order = 'priority desc, id'
    _rec_name = 'name'

    _PROMPT_TEMPLATE_SECTION_SENTINEL = '__PROMPT_TEMPLATE_SECTION__'

    display_name = fields.Char(compute='_compute_display_name')
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(default=True, help='If disabled, this model will not be used for AI calls.')
    priority = fields.Integer(default=10)
    provider_id = fields.Many2one('aps.ai.provider', required=True, ondelete='cascade')
    model_key = fields.Char(required=True, help='Model identifier sent to the AI router.')
    temperature = fields.Float(default=0.2)
    max_completion_tokens = fields.Integer(default=9600)
    force_json_response = fields.Boolean(
        string='Request JSON Output',
        default=False,
        help='Ask the provider for JSON-only responses when the router supports it.',
    )
    disable_reasoning = fields.Boolean(
        string='Disable Reasoning',
        default=True,
        help='When enabled, reasoning output is never requested from this AI model even if the caller asks for it.',
    )
    input_cost_per_million = fields.Float(
        digits=(16, 6),
        help='Estimated input token cost per 1,000,000 tokens in provider billing units.',
    )
    output_cost_per_million = fields.Float(
        digits=(16, 6),
        help='Estimated output token cost per 1,000,000 tokens in provider billing units.',
    )
    call_log_ids = fields.One2many('aps.ai.call.log', 'model_id', string='Call Logs', readonly=True)
    total_estimated_cost = fields.Float(
        string='Total Estimated Cost',
        compute='_compute_total_estimated_cost',
        digits=(16, 6),
        readonly=True,
    )
    notes = fields.Text()

    @api.depends('name', 'provider_id.display_name', 'model_key', 'input_cost_per_million', 'output_cost_per_million')
    def _compute_display_name(self):
        for record in self:
            base_name = ''
            if record.provider_id and record.name:
                base_name = f'{record.provider_id.display_name} / {record.name}'
            else:
                base_name = record.name or record.model_key or ''

            cost_suffix = ' [In: %.6f | Out: %.6f]' % (
                record.input_cost_per_million or 0.0,
                record.output_cost_per_million or 0.0,
            )
            record.display_name = f'{base_name}{cost_suffix}' if base_name else cost_suffix

    @api.depends('call_log_ids.estimated_cost')
    def _compute_total_estimated_cost(self):
        for record in self:
            record.total_estimated_cost = sum(record.call_log_ids.mapped('estimated_cost'))

    def action_test_connection(self):
        self.ensure_one()
        try:
            result = self._run_connection_test()
        except Exception as exc:
            return _build_notification_action(
                _('AI Test Failed'),
                _format_test_failure_message(self.display_name, _exception_to_text(exc)),
                notification_type='warning',
                sticky=True,
            )

        return _build_notification_action(
            _('AI Test Passed'),
            _('Model: %s. Prompt tokens: %s. Completion tokens: %s. Estimated cost: %s') % (
                self.display_name,
                result['prompt_tokens'],
                result['completion_tokens'],
                f"{result['estimated_cost']:.6f}",
            ),
            notification_type='success',
            sticky=False,
        )

    def _run_connection_test(self):
        self.ensure_one()
        result = self._execute_logged_router_call(self._build_test_payload(), request_type='connection_test')
        try:
            response_json = result['response_json']
            raw_content = self._extract_message_content(response_json)
            if 'TEST_OK' not in raw_content.upper():
                raise UserError(_('The AI model responded, but the test reply was unexpected: %s') % raw_content)
        except Exception as exc:
            self._update_call_log_error(result.get('log_record'), exc)
            raise
        return result

    def _get_retry_max_completion_tokens(self, requested_tokens):
        base_tokens = int(requested_tokens or self.max_completion_tokens or 0)
        if base_tokens <= 0:
            return False
        return min(max(base_tokens * 2, base_tokens + 800), 4096)

    @api.model
    def _get_generation_candidates(self, resource=None):
        if resource and resource.ai_model_id:
            model = resource.ai_model_id.sudo()
            if not model.exists():
                raise UserError(_('The selected AI model no longer exists.'))
            if not model.enabled or not model.provider_id.enabled:
                raise UserError(_('The selected AI model is disabled or its provider is disabled.'))
            return model

        return self.sudo().search(
            [('enabled', '=', True), ('provider_id.enabled', '=', True)],
        ).sorted(key=lambda rec: (-(rec.priority or 0), -(rec.provider_id.priority or 0), rec.id))

    @api.model
    def _build_dynamic_prompt_sections(
        self,
        instructions='',
        out_of_marks=False,
        use_question=False,
        question='',
        use_model_answer=False,
        model_answer='',
        use_note=False,
        notes='',
        student_answer='',
        student_answer_chunks=None,
        targeted_feedback=False,
        inject_response_format=True,
        prior_phase_context='',
        detailed_feedback='',
    ):
        dynamic_sections = []

        if instructions and instructions.strip():
            dynamic_sections.append(('Specific Instructions', instructions.strip()))
        if out_of_marks:
            dynamic_sections.append(('Maximum Mark', '## MAXIMUM MARK:\n%s' % out_of_marks))
        if use_question and question.strip():
            dynamic_sections.append(('Question', '## QUESTION:\n%s' % question.strip()))
        if use_model_answer:
            dynamic_sections.append(('Model Answer', '## MODEL ANSWER:\n%s' % (model_answer.strip() or 'No model answer provided.')))
        if use_note and notes.strip():
            dynamic_sections.append(('Notes', '## NOTES:\n%s' % notes.strip()))
        if prior_phase_context and prior_phase_context.strip():
            dynamic_sections.append(('Detailed Feedback', '## DETAILED FEEDBACK:\n%s' % prior_phase_context.strip()))
        if detailed_feedback and detailed_feedback.strip():
            dynamic_sections.append(('Summarise Feedback', '## DETAILED FEEDBACK:\n%s' % detailed_feedback.strip()))
        if targeted_feedback and student_answer_chunks:
            dynamic_sections.append((
                'Student Answer',
                'Student Answer Chunks:\n%s' % json.dumps(student_answer_chunks, indent=2, ensure_ascii=False),
            ))
            dynamic_sections.append(('Targeted Feedback', self._PROMPT_TEMPLATE_SECTION_SENTINEL))
        else:
            dynamic_sections.append(('Student Answer', 'Student Answer:\n%s' % student_answer.strip()))
            # if inject_response_format:
            #     dynamic_sections.append((
            #         'Response Format',
            #         'Return ONLY valid JSON with these keys:\n'
            #         '{"feedback_html": string, "score": number|null, "score_comment": string|null}.\n'
            #         'feedback_html must be an HTML fragment using tags such as <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.\n'
            #         'If you cannot determine a mark, set score to null and explain why in score_comment.',
            #     ))

        return dynamic_sections

    def _assemble_chat_payload(
        self,
        instructions='',
        external_prompt='',
        prompt_records=None,
        out_of_marks=False,
        use_question=False,
        question='',
        use_model_answer=False,
        model_answer='',
        use_note=False,
        notes='',
        student_answer='',
        student_answer_chunks=None,
        targeted_feedback=False,
        include_reasoning=False,
        inject_response_format=True,
        prior_phase_context='',
        detailed_feedback='',
    ):
        """Build an OpenAI-compatible chat payload from resolved prompt components."""
        prompt_sections = []
        prompt_names_used = []
        dynamic_sections = self._build_dynamic_prompt_sections(
            instructions=instructions,
            out_of_marks=out_of_marks,
            use_question=use_question,
            question=question,
            use_model_answer=use_model_answer,
            model_answer=model_answer,
            use_note=use_note,
            notes=notes,
            student_answer=student_answer,
            student_answer_chunks=student_answer_chunks,
            targeted_feedback=targeted_feedback,
            inject_response_format=inject_response_format,
            prior_phase_context=prior_phase_context,
            detailed_feedback=detailed_feedback,
        )

        dynamic_section_map = {
            self._normalize_prompt_name(name): (name, content)
            for name, content in dynamic_sections
            if content
        }
        used_dynamic_keys = set()

        for prompt in prompt_records or self.env['ai_prompts']:
            prompt_name = (prompt.prompt_name or '').strip()
            prompt_key = self._normalize_prompt_name(prompt_name)
            if prompt_key in dynamic_section_map and prompt_key not in used_dynamic_keys:
                section_name, section_content = dynamic_section_map[prompt_key]
                if section_content == self._PROMPT_TEMPLATE_SECTION_SENTINEL:
                    section_content = (prompt.prompt or '').strip()
                if not section_content:
                    used_dynamic_keys.add(prompt_key)
                    continue
                prompt_sections.append(section_content)
                prompt_names_used.append(section_name)
                used_dynamic_keys.add(prompt_key)
                continue

            if prompt.placeholder:
                continue

            prompt_text = (prompt.prompt or '').strip()
            if prompt_text:
                prompt_sections.append(prompt_text)
                prompt_names_used.append(prompt_name or 'Prompt Template')

        if external_prompt and prompt_records:
            prompt_sections.append('## Prompt Template:\n%s' % external_prompt.strip())
            prompt_names_used.append('Prompt Template')

        payload = {
            'model': self.model_key,
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'You are an expert teacher assistant. Follow the supplied instructions exactly, '
                        'produce constructive teacher feedback for students, and when possible determine a mark.'
                        + (' Do not return reasoning, chain-of-thought, or thinking text. Return only the final answer.' if self.disable_reasoning else '')
                    ),
                },
                {
                    'role': 'user',
                    'content': '\n\n'.join(section for section in prompt_sections if section),
                },
            ],
            'temperature': self.temperature,
            'max_completion_tokens': self.max_completion_tokens,
        }
        if self.disable_reasoning:
            payload['reasoning'] = {
                'enabled': False,
                'exclude': True,
            }
        elif include_reasoning:
            payload['reasoning'] = {
                'enabled': True,
                'exclude': False,
                'effort': 'low',
            }
        if self.force_json_response:
            payload['response_format'] = {'type': 'json_object'}
        return payload, prompt_names_used

    @api.model
    def _normalize_prompt_name(self, prompt_name):
        return re.sub(r'\s+', ' ', (prompt_name or '').strip()).casefold()

    def _collect_applicable_prompts(self, selected_prompts, db_model_name):
        self.ensure_one()
        self.env['ai_prompts'].sudo().ensure_default_targeted_feedback_prompt()
        selected = (selected_prompts or self.env['ai_prompts']).filtered(lambda rec: rec.enabled and (rec.prompt or rec.prompt_name))
        always = self.env['ai_prompts'].sudo().search([
            ('enabled', '=', True),
            ('always_include', '=', True),
        ])
        placeholders = self.env['ai_prompts'].sudo().search([
            ('enabled', '=', True),
            ('placeholder', '=', True),
        ])
        candidates = (selected | always | placeholders)

        applicable = candidates.filtered(
            lambda rec: (
                not rec.applies_to_ai_models or self in rec.applies_to_ai_models
            ) and (
                not rec.applies_to_db_models or db_model_name in rec.applies_to_db_models.mapped('model')
            )
        )

        return applicable.sorted(key=lambda rec: ((rec.sequence or 0), rec.id))

    def _build_test_payload(self):
        payload = {
            'model': self.model_key,
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'You are a connectivity test endpoint. '
                        'Do not explain anything. Do not include reasoning. '
                        'Reply using the exact text TEST_OK.'
                    ),
                },
                {
                    'role': 'user',
                    'content': 'Return exactly TEST_OK and nothing else.',
                },
            ],
            'temperature': 0,
            # Connection tests need a slightly larger budget so reasoning-capable models
            # still have room to emit the final answer token.
            'max_completion_tokens': max(64, min(self.max_completion_tokens or 64, 128)),
        }
        return payload

    def _execute_logged_router_call(self, payload, request_type, related_record=None, stream_callback=None, prompt_names_used=None, phase=None):
        self.ensure_one()
        request_payload = json.dumps(payload, indent=2, sort_keys=True)
        endpoint = self._get_router_endpoint()

        # Create a pending log record immediately and commit so it's visible in the
        # AI > Logs list before the (potentially slow) provider call starts.
        log_record = self._create_call_log(
            request_type=request_type,
            phase=phase,
            endpoint=endpoint,
            request_payload=request_payload,
            response_text='Waiting...',
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost=0.0,
            duration_ms=0,
            related_record=related_record,
            error_message=None,
            prompt_names_used=prompt_names_used,
            pending=True,
        )

        response_json = None
        response_text = False
        prompt_tokens = 0
        completion_tokens = 0
        estimated_cost = 0.0
        error_message = False
        started_at = time.perf_counter()
        result = None
        caught_exc = None

        try:
            if stream_callback:
                response_text, response_json = self._perform_streaming_router_request(payload, stream_callback)
            else:
                response_text = self._perform_router_request(payload)
                response_json = self._parse_router_response_json(response_text)
            response_json = self._strip_reasoning_from_response(response_json)
            response_text = json.dumps(response_json)
            usage = response_json.get('usage') or {}
            prompt_tokens = int(usage.get('prompt_tokens') or usage.get('input_tokens') or 0)
            completion_tokens = int(usage.get('completion_tokens') or usage.get('output_tokens') or 0)
            estimated_cost = self._estimate_usage_cost(prompt_tokens, completion_tokens)
            result = {
                'response_json': response_json,
                'response_text': response_text,
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'estimated_cost': estimated_cost,
            }
        except Exception as exc:
            error_message = _exception_to_text(exc)
            caught_exc = exc

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        self._update_call_log(
            log_record,
            response_text=response_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=estimated_cost,
            duration_ms=duration_ms,
            error_message=error_message,
        )

        if result is not None:
            result['log_record'] = log_record
            return result
        raise caught_exc

    def _create_call_log(
        self,
        request_type,
        endpoint,
        request_payload,
        response_text,
        prompt_tokens,
        completion_tokens,
        estimated_cost,
        duration_ms,
        related_record=None,
        error_message=None,
        prompt_names_used=None,
        pending=False,
        phase=None,
    ):
        self.ensure_one()
        vals = {
            'state': 'pending' if pending else ('error' if error_message else 'success'),
            'request_type': request_type,
            'phase': phase or False,
            'user_id': self.env.user.id,
            'provider_id': self.provider_id.id,
            'model_id': self.id,
            'model_key': self.model_key,
            'endpoint': endpoint,
            'prompt_tokens': prompt_tokens or 0,
            'completion_tokens': completion_tokens or 0,
            'estimated_cost': estimated_cost or 0.0,
            'duration_ms': duration_ms or 0,
            'prompt_names_used': '\n'.join(prompt_names_used) if prompt_names_used else False,
            'request_payload': request_payload,
            'response_body': response_text or False,
            'error_message': error_message or False,
        }
        if related_record:
            vals.update({
                'related_model': related_record._name,
                'related_res_id': related_record.id,
                'related_display_name': related_record.display_name,
            })
        try:
            record = self.env['aps.ai.call.log'].sudo().create(vals)
            if pending:
                self.env.cr.commit()
            return record
        except Exception:
            _logger.exception('Failed to create AI call log for model %s', self.display_name)
        return False

    def _update_call_log(self, log_record, response_text, prompt_tokens, completion_tokens, estimated_cost, duration_ms, error_message):
        """Update a pending call log with the final response data and commit immediately."""
        if not log_record:
            return
        try:
            log_record.sudo().write({
                'state': 'error' if error_message else 'success',
                'response_body': response_text or False,
                'prompt_tokens': prompt_tokens or 0,
                'completion_tokens': completion_tokens or 0,
                'estimated_cost': estimated_cost or 0.0,
                'duration_ms': duration_ms or 0,
                'error_message': error_message or False,
            })
            self.env.cr.commit()
        except Exception:
            _logger.exception('Failed to update AI call log %s for model %s', log_record.id, self.display_name)

    def _update_call_log_error(self, log_record, exc):
        self.ensure_one()
        if not log_record:
            return
        try:
            log_record.sudo().write({
                'state': 'error',
                'error_message': _exception_to_text(exc),
            })
            self.env.cr.commit()
        except Exception:
            _logger.exception('Failed to update AI call log %s for model %s', log_record.id, self.display_name)

    def _get_router_endpoint(self):
        self.ensure_one()
        provider = self.provider_id
        base_url = (provider.api_base_url or '').rstrip('/')
        path = provider.chat_completions_path or '/chat/completions'
        if not path.startswith('/'):
            path = '/%s' % path
        return '%s%s' % (base_url, path)

    def _perform_router_request(self, payload):
        self.ensure_one()
        provider = self.provider_id
        endpoint = self._get_router_endpoint()
        headers = {'Content-Type': 'application/json'}
        if provider.api_key:
            headers[provider.api_key_header or 'Authorization'] = '%s%s' % (
                provider.api_key_prefix or '',
                provider.api_key,
            )

        request_data = json.dumps(payload).encode('utf-8')
        request = url_request.Request(endpoint, data=request_data, headers=headers, method='POST')
        try:
            with url_request.urlopen(request, timeout=provider.timeout_seconds or 90) as response:
                return response.read().decode('utf-8')
        except url_error.HTTPError as exc:
            error_text = exc.read().decode('utf-8', errors='ignore') if hasattr(exc, 'read') else str(exc)
            raise UserError(_('AI router request failed: %s') % error_text)
        except url_error.URLError as exc:
            raise UserError(_('Could not reach the AI router: %s') % exc)

    def _perform_streaming_router_request(self, payload, stream_callback):
        self.ensure_one()
        provider = self.provider_id
        endpoint = self._get_router_endpoint()
        headers = {'Content-Type': 'application/json'}
        if provider.api_key:
            headers[provider.api_key_header or 'Authorization'] = '%s%s' % (
                provider.api_key_prefix or '',
                provider.api_key,
            )

        stream_payload = dict(payload)
        stream_payload['stream'] = True
        stream_payload['stream_options'] = {'include_usage': True}
        request_data = json.dumps(stream_payload).encode('utf-8')
        request = url_request.Request(endpoint, data=request_data, headers=headers, method='POST')

        try:
            with url_request.urlopen(request, timeout=provider.timeout_seconds or 90) as response:
                return self._consume_streaming_response(response, stream_callback)
        except url_error.HTTPError as exc:
            error_text = exc.read().decode('utf-8', errors='ignore') if hasattr(exc, 'read') else str(exc)
            raise UserError(_('AI router request failed: %s') % error_text)
        except url_error.URLError as exc:
            raise UserError(_('Could not reach the AI router: %s') % exc)

    def _consume_streaming_response(self, response, stream_callback):
        aggregated = {
            'id': False,
            'object': 'chat.completion',
            'created': False,
            'model': self.model_key,
            'provider': False,
            'system_fingerprint': False,
            'choices': [{
                'index': 0,
                'logprobs': None,
                'finish_reason': False,
                'native_finish_reason': False,
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'reasoning': '',
                },
            }],
            'usage': {},
        }
        content_parts = []
        reasoning_parts = []

        for raw_line in response:
            line = raw_line.decode('utf-8', errors='ignore').strip()
            if not line or not line.startswith('data:'):
                continue

            data = line[5:].strip()
            if data == '[DONE]':
                break

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get('id'):
                aggregated['id'] = chunk.get('id')
            if chunk.get('created'):
                aggregated['created'] = chunk.get('created')
            if chunk.get('model'):
                aggregated['model'] = chunk.get('model')
            if chunk.get('provider'):
                aggregated['provider'] = chunk.get('provider')
            if chunk.get('system_fingerprint'):
                aggregated['system_fingerprint'] = chunk.get('system_fingerprint')
            if chunk.get('usage'):
                aggregated['usage'] = chunk.get('usage') or {}

            choices = chunk.get('choices') or []
            if not choices:
                continue

            choice = choices[0] or {}
            delta = choice.get('delta') or {}
            if delta.get('role'):
                aggregated['choices'][0]['message']['role'] = delta.get('role')
            finish_reason = choice.get('finish_reason') or choice.get('native_finish_reason')
            if finish_reason:
                aggregated['choices'][0]['finish_reason'] = choice.get('finish_reason') or finish_reason
                aggregated['choices'][0]['native_finish_reason'] = choice.get('native_finish_reason') or finish_reason

            content_piece = self._extract_stream_content_piece(delta, choice)
            if content_piece:
                content_parts.append(content_piece)
            reasoning_piece = self._extract_stream_reasoning_piece(delta, choice)
            if reasoning_piece:
                reasoning_parts.append(reasoning_piece)

            aggregated['choices'][0]['message']['content'] = ''.join(content_parts)
            aggregated['choices'][0]['message']['reasoning'] = ''.join(reasoning_parts)
            stream_callback(''.join(reasoning_parts), ''.join(content_parts))

        message = aggregated['choices'][0]['message']
        if not message.get('content'):
            message['content'] = None
        if not message.get('reasoning'):
            message['reasoning'] = None
        response_json = aggregated
        response_text = json.dumps(response_json)
        return response_text, response_json

    def _strip_reasoning_from_response(self, response_json):
        if not self.disable_reasoning or not isinstance(response_json, dict):
            return response_json

        cleaned = copy.deepcopy(response_json)
        choices = cleaned.get('choices') or []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get('message')
            if isinstance(message, dict):
                message.pop('reasoning', None)
                message.pop('reasoning_details', None)
            choice.pop('reasoning', None)
            choice.pop('reasoning_details', None)

        return cleaned

    def _extract_stream_content_piece(self, delta, choice):
        return (
            self._coerce_content_to_text(delta.get('content'))
            or self._coerce_content_to_text(delta.get('output_text'))
            or self._coerce_content_to_text(choice.get('text'))
            or ''
        )

    def _extract_stream_reasoning_piece(self, delta, choice):
        return (
            self._coerce_content_to_text(delta.get('reasoning'))
            or self._coerce_reasoning_details_to_text(delta.get('reasoning_details'))
            or self._coerce_content_to_text(choice.get('reasoning'))
            or self._coerce_reasoning_details_to_text(choice.get('reasoning_details'))
            or ''
        )

    def _parse_router_response_json(self, response_text):
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise UserError(_('The AI router returned invalid JSON: %s') % exc)

    def _call_openai_compatible_router(self, payload):
        return self._parse_router_response_json(self._perform_router_request(payload))

    def _extract_message_content(self, response_json):
        content = False
        reasoning_text = False
        finish_reason = False

        choices = response_json.get('choices') or []
        if choices:
            choice = choices[0] or {}
            message = choice.get('message') or {}
            finish_reason = choice.get('finish_reason') or choice.get('native_finish_reason')
            content = self._coerce_content_to_text(message.get('content'))
            if not content:
                content = self._coerce_content_to_text(message.get('output_text'))
            if not content:
                content = self._coerce_content_to_text(choice.get('text'))
            if not content:
                content = self._coerce_content_to_text(choice.get('delta'))
            reasoning_text = self._coerce_content_to_text(message.get('reasoning'))
            if not reasoning_text:
                reasoning_text = self._coerce_reasoning_details_to_text(message.get('reasoning_details'))

        if not content:
            content = self._coerce_content_to_text(response_json.get('output_text'))

        if not content:
            output_items = response_json.get('output') or []
            text_parts = []
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                item_text = self._coerce_content_to_text(item.get('text'))
                if item_text:
                    text_parts.append(item_text)
                content_items = item.get('content') or []
                content_text = self._coerce_content_to_text(content_items)
                if content_text:
                    text_parts.append(content_text)
            if text_parts:
                content = '\n'.join(text_parts)

        if not content:
            if reasoning_text and finish_reason == 'length':
                raise UserError(_(
                    'The AI model used its completion token budget on reasoning and did not return the final answer. '
                    'Increase Max Completion Tokens above %s for this model or use a less reasoning-heavy model.'
                ) % (self.max_completion_tokens or 0))
            if reasoning_text:
                raise UserError(_(
                    'The AI model returned reasoning but did not return the final answer content. '
                    'Open AI > Logs and inspect Response Body for the raw provider response.'
                ))
            raise UserError(_('The AI router returned an empty completion.'))
        return content.strip()

    def _is_reasoning_only_truncation(self, response_json):
        choices = response_json.get('choices') or []
        if not choices:
            return False

        choice = choices[0] or {}
        message = choice.get('message') or {}
        finish_reason = choice.get('finish_reason') or choice.get('native_finish_reason')
        content = (
            self._coerce_content_to_text(message.get('content'))
            or self._coerce_content_to_text(message.get('output_text'))
            or self._coerce_content_to_text(choice.get('text'))
            or self._coerce_content_to_text(choice.get('delta'))
        )
        reasoning_text = self._coerce_content_to_text(message.get('reasoning'))
        if not reasoning_text:
            reasoning_text = self._coerce_reasoning_details_to_text(message.get('reasoning_details'))
        return finish_reason == 'length' and bool(reasoning_text) and not bool(content)

    def _coerce_reasoning_details_to_text(self, reasoning_details):
        if not isinstance(reasoning_details, list):
            return False

        text_parts = []
        for item in reasoning_details:
            if not isinstance(item, dict):
                continue
            text_value = item.get('text')
            if text_value:
                text_parts.append(text_value)

        return '\n'.join(part for part in text_parts if part) or False

    def _coerce_content_to_text(self, content):
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if content.get('text'):
                return content.get('text')
            if content.get('content'):
                return self._coerce_content_to_text(content.get('content'))
            return False
        if not isinstance(content, list):
            return False

        text_parts = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get('type')
                if item_type in ('text', 'output_text') and item.get('text'):
                    text_parts.append(item.get('text'))
                elif item.get('text'):
                    text_parts.append(item.get('text'))
            elif isinstance(item, str):
                text_parts.append(item)

        return '\n'.join(part for part in text_parts if part) or False

    def _parse_structured_response(self, raw_content):
        text = (raw_content or '').strip()
        if text.startswith('```'):
            lines = [line for line in text.splitlines() if not line.strip().startswith('```')]
            text = '\n'.join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def _extract_string(self, parsed, key):
        if isinstance(parsed, dict):
            value = parsed.get(key)
            if value not in (None, ''):
                return value
        return None

    def _extract_score(self, parsed):
        if isinstance(parsed, dict):
            score = parsed.get('score')
            if score not in (None, ''):
                try:
                    return float(score)
                except (TypeError, ValueError):
                    pass
        return None

    def _normalize_feedback_html(self, feedback_html):
        text = (feedback_html or '').strip()
        if not text:
            return '<p>No feedback was returned by the AI model.</p>'
        if '<' in text and '>' in text:
            return text
        paragraphs = [segment.strip() for segment in text.split('\n\n') if segment.strip()]
        if not paragraphs:
            paragraphs = [text]
        return ''.join('<p>%s</p>' % escape(paragraph).replace('\n', '<br/>') for paragraph in paragraphs)

    def _html_to_text(self, html_value):
        if not html_value:
            return ''
        text = str(html_value)
        text = text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
        for tag in ('</p>', '</div>', '</li>', '</h1>', '</h2>', '</h3>', '</h4>'):
            text = text.replace(tag, '\n')
        text = re.sub(r'<[^>]+>', '', text)
        return text.replace('&nbsp;', ' ').strip()

    def _estimate_usage_cost(self, prompt_tokens, completion_tokens):
        input_cost = (prompt_tokens / 1000000.0) * (self.input_cost_per_million or 0.0)
        output_cost = (completion_tokens / 1000000.0) * (self.output_cost_per_million or 0.0)
        return input_cost + output_cost

    # ------------------------------------------------------------------
    # Phase-aware feedback engine  (shared by all record types)
    # ------------------------------------------------------------------

    def _split_prompts_by_phase(self, prompts):
        """Split a prompts recordset into {0: unphased, 1: phase1, 2: phase2, 3: phase3}.

        A prompt with multiple phase tags is assigned to the lowest phase number.
        Prompts with no phase tag go to bucket 0 and are included in all phases.
        """
        result = {n: self.env['ai_prompts'] for n in (0, 1, 2, 3)}
        for prompt in prompts:
            tag_names = set(prompt.tag_ids.mapped('name'))
            assigned = False
            for n in (1, 2, 3):
                if ('Phase %d' % n) in tag_names:
                    result[n] |= prompt
                    assigned = True
                    break
            if not assigned:
                result[0] |= prompt
        return result

    def _execute_phase_call(self, payload, phase_label, related_record, progress_callback, prompt_names_used=None):
        """Execute one AI phase call with reasoning-truncation retry.

        Returns ``(raw_content, result)`` where *result* is the dict from
        ``_execute_logged_router_call``.
        """
        result = self._execute_logged_router_call(
            payload,
            request_type='submission_feedback',
            phase=phase_label,
            related_record=related_record,
            stream_callback=progress_callback,
            prompt_names_used=prompt_names_used,
        )
        try:
            raw_content = self._extract_message_content(result['response_json'])
        except Exception as exc:
            self._update_call_log_error(result.get('log_record'), exc)
            if self._is_reasoning_only_truncation(result.get('response_json')):
                retry_payload = dict(payload)
                retry_payload['max_completion_tokens'] = self._get_retry_max_completion_tokens(
                    payload.get('max_completion_tokens')
                )
                result = self._execute_logged_router_call(
                    retry_payload,
                    request_type='submission_feedback',
                    phase='%s_retry' % phase_label,
                    related_record=related_record,
                    stream_callback=progress_callback,
                )
                try:
                    raw_content = self._extract_message_content(result['response_json'])
                except Exception as retry_exc:
                    self._update_call_log_error(result.get('log_record'), retry_exc)
                    raise
            else:
                raise
        return raw_content, result

    def _build_chat_payload_from_ctx(self, ctx, prompt_records, answer_chunk_data=None):
        """Assemble a single-phase chat payload from a feedback context dict.

        Returns ``(payload, prompt_names_used)``.  Raises ``UserError`` if the
        student answer is empty.
        """
        student_answer = ctx.get('student_answer', '')
        if not student_answer.strip():
            raise UserError(ctx.get('empty_answer_error') or _('No student answer provided.'))
        return self._assemble_chat_payload(
            instructions=ctx['instructions'],
            prompt_records=prompt_records,
            out_of_marks=ctx['out_of_marks'],
            use_question=ctx['use_question'],
            question=ctx['question'],
            use_model_answer=ctx['use_model_answer'],
            model_answer=ctx['model_answer'],
            use_note=ctx['use_note'],
            notes=ctx['notes'],
            student_answer=student_answer,
            student_answer_chunks=answer_chunk_data['chunks'] if answer_chunk_data else None,
            targeted_feedback=ctx['ai_targeted_feedback'],
            include_reasoning=ctx['include_reasoning'],
        )

    def _build_phase1_payload_from_ctx(self, ctx, phase1_prompts, unphased_prompts):
        """Phase 1: detailed HTML-only.  No JSON format is injected."""
        student_answer = ctx.get('student_answer', '')
        if not student_answer.strip():
            raise UserError(ctx.get('empty_answer_error') or _('No student answer provided.'))
        combined = (unphased_prompts | phase1_prompts).sorted(key=lambda r: ((r.sequence or 0), r.id))
        return self._assemble_chat_payload(
            instructions=ctx['instructions'],
            prompt_records=combined,
            out_of_marks=ctx['out_of_marks'],
            use_question=ctx['use_question'],
            question=ctx['question'],
            use_model_answer=ctx['use_model_answer'],
            model_answer=ctx['model_answer'],
            use_note=ctx['use_note'],
            notes=ctx['notes'],
            student_answer=student_answer,
            targeted_feedback=False,
            inject_response_format=False,
            include_reasoning=ctx['include_reasoning'],
        )

    def _build_phase2_payload_from_ctx(self, ctx, phase2_prompts, unphased_prompts, answer_chunk_data, phase1_html):
        """Phase 2: JSON + chunk linking.  Phase 1 HTML is injected as prior context."""
        student_answer = ctx.get('student_answer', '')
        if not student_answer.strip():
            raise UserError(ctx.get('empty_answer_error') or _('No student answer provided.'))
        combined = (unphased_prompts | phase2_prompts).sorted(key=lambda r: ((r.sequence or 0), r.id))
        return self._assemble_chat_payload(
            instructions=ctx['instructions'],
            prompt_records=combined,
            out_of_marks=ctx['out_of_marks'],
            use_question=ctx['use_question'],
            question=ctx['question'],
            use_model_answer=ctx['use_model_answer'],
            model_answer=ctx['model_answer'],
            use_note=ctx['use_note'],
            notes=ctx['notes'],
            student_answer=student_answer,
            student_answer_chunks=answer_chunk_data['chunks'] if answer_chunk_data else None,
            targeted_feedback=ctx['ai_targeted_feedback'],
            prior_phase_context=phase1_html,
            include_reasoning=ctx['include_reasoning'],
        )

    def _build_phase3_payload_from_ctx(self, ctx, phase3_prompts, phase1_html):
        """Phase 3 (optional): summary HTML.  Only the Phase 3 prompts and Phase 1 context are used."""
        combined = phase3_prompts.sorted(key=lambda r: ((r.sequence or 0), r.id))
        return self._assemble_chat_payload(
            instructions=ctx['instructions'],
            prompt_records=combined,
            detailed_feedback=phase1_html,
            targeted_feedback=False,
            inject_response_format=False,
            include_reasoning=ctx['include_reasoning'],
        )

    def _generate_feedback_multiphase(self, ctx, phase_map, related_record, ai_run=None):
        """Generic multi-phase AI feedback orchestrator.

        Phase 1 — detailed HTML feedback (optional; runs when phase1_prompts exist).
        Phase 2 — JSON + chunk linking using Phase 1 HTML as reference (required).
        Phase 3 — optional summary HTML prepended above the Phase 1 detail.

        *ctx* is a dict produced by ``_build_submission_feedback_context`` or
        ``_build_resource_feedback_context``; *related_record* is used only for
        call-log linking and the streaming callback source.

        Returns the standard feedback result dict.
        """
        self.ensure_one()
        progress_callback = ai_run._build_stream_callback() if ai_run else None

        phase1_prompts = phase_map.get(1, self.env['ai_prompts'])
        phase2_prompts = phase_map.get(2, self.env['ai_prompts'])
        phase3_prompts = phase_map.get(3, self.env['ai_prompts'])
        unphased_prompts = phase_map.get(0, self.env['ai_prompts'])
        # unphased_prompts = None

        if not phase2_prompts:
            raise UserError(_(
                'Multi-phase feedback mode requires at least one prompt tagged "Phase 2" '
                'to generate structured feedback with chunk links.'
            ))

        answer_chunk_data = (
            self._build_submission_answer_chunks(ctx['student_answer_html'])
            if ctx['ai_targeted_feedback'] else None
        )

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0

        # --- Phase 1: detailed HTML ---
        phase1_html = ''
        if phase1_prompts:
            payload1, names1 = self._build_phase1_payload_from_ctx(ctx, phase1_prompts, unphased_prompts)
            phase1_raw, result1 = self._execute_phase_call(payload1, 'phase1', related_record, progress_callback, names1)
            parsed1 = self._parse_structured_response(phase1_raw)
            phase1_html = self._extract_string(parsed1, 'html')
            phase1_html_plain_text = self._html_to_text(phase1_html)
            score = self._extract_score(parsed1)
            score_comment = self._extract_string(parsed1, 'score_comment')
            # phase1_html = self._normalize_feedback_html(phase1_raw)

            total_prompt_tokens += result1.get('prompt_tokens', 0) or 0
            total_completion_tokens += result1.get('completion_tokens', 0) or 0
            total_cost += result1.get('estimated_cost', 0.0) or 0.0

        # --- Phase 2: JSON + chunk linking ---
        payload2, names2 = self._build_phase2_payload_from_ctx(
            ctx, 
            phase2_prompts, unphased_prompts, 
            answer_chunk_data,phase1_html_plain_text
        )
        phase2_raw, result2 = self._execute_phase_call(payload2, 'phase2', related_record, progress_callback, names2)
        total_prompt_tokens += result2.get('prompt_tokens', 0) or 0
        total_completion_tokens += result2.get('completion_tokens', 0) or 0
        total_cost += result2.get('estimated_cost', 0.0) or 0.0

        parsed2 = self._parse_structured_response(phase2_raw)
        targeted_result = self._extract_targeted_feedback(parsed2, phase2_raw, answer_chunk_data)
        # score = self._extract_score(parsed2)
        

        # --- Phase 3: optional summary ---
        phase3_raw = ''
        if phase3_prompts:
            payload3, names3 = self._build_phase3_payload_from_ctx(ctx, phase3_prompts, phase1_html_plain_text)
            phase3_raw, result3 = self._execute_phase_call(payload3, 'phase3', related_record, progress_callback, names3)
            parsed3 = self._parse_structured_response(phase3_raw)
            phase3_html = self._extract_string(parsed3, 'html')
            phase3_html = self._normalize_feedback_html(phase3_html)
            # Treat error responses as empty (e.g., "No content provided to summarise")
            
            # if phase3_html and phase3_html.startswith("'<p>{ &quot;error&quot"):
            #     phase3_html = ''
            total_prompt_tokens += result3.get('prompt_tokens', 0) or 0
            total_completion_tokens += result3.get('completion_tokens', 0) or 0
            total_cost += result3.get('estimated_cost', 0.0) or 0.0

        if phase3_html and phase1_html:
            feedback_html = phase3_html + '<hr class="aps-ai-phase-separator mt-3 mb-3"/>' + phase1_html
        else:
            feedback_html = phase3_html or phase1_html

        return {
            'feedback_html': feedback_html,
            'score': score,
            'answer_chunks': targeted_result['answer_chunks'],
            'answer_chunked_html': targeted_result['answer_chunked_html'],
            'feedback_items': targeted_result['feedback_items'],
            'feedback_links': targeted_result['feedback_links'],
            'targeted_feedback': targeted_result['targeted_feedback'],
            'prompt_tokens': total_prompt_tokens,
            'completion_tokens': total_completion_tokens,
            'estimated_cost': total_cost,
            'model_id': self.id,
            'model_name': self.display_name,
            'raw_content': phase2_raw,
        }

        self._log_ai_result(result)
        return result

    def _log_ai_result(self, result):
        """Log AI result for debugging."""
        _logger.debug('AI result keys: %s', list(result.keys()))
        _logger.debug('AI result feedback_html length: %s', len(result.get('feedback_html') or ''))
        _logger.debug('AI result score: %s', result.get('score'))
        _logger.debug('AI result answer_chunks: %s', result.get('answer_chunks'))
        _logger.debug('AI result feedback_items: %s', result.get('feedback_items'))
        _logger.debug('AI result feedback_links: %s', result.get('feedback_links'))
