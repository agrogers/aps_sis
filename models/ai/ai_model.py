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

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(default=True, help='If disabled, this model will not be used for AI calls.')
    priority = fields.Integer(default=10)
    provider_id = fields.Many2one('aps.ai.provider', required=True, ondelete='cascade')
    model_key = fields.Char(required=True, help='Model identifier sent to the AI router.')
    temperature = fields.Float(default=0.2)
    max_completion_tokens = fields.Integer(default=1200)
    force_json_response = fields.Boolean(
        string='Request JSON Output',
        default=False,
        help='Ask the provider for JSON-only responses when the router supports it.',
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
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'provider_id.display_name', 'model_key')
    def _compute_display_name(self):
        for record in self:
            if record.provider_id and record.name:
                record.display_name = f'{record.provider_id.display_name} / {record.name}'
            else:
                record.display_name = record.name or record.model_key or ''

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

    def _assemble_chat_payload(
        self,
        instructions='',
        external_prompt='',
        out_of_marks=False,
        use_question=False,
        question='',
        use_model_answer=False,
        model_answer='',
        use_note=False,
        notes='',
        student_answer='',
        include_reasoning=False,
    ):
        """Build an OpenAI-compatible chat payload from resolved prompt components."""
        prompt_sections = []
        if instructions:
            prompt_sections.append('AI Instructions:\n%s' % instructions.strip())
        if external_prompt:
            prompt_sections.append('Prompt Template:\n%s' % external_prompt.strip())
        if out_of_marks:
            prompt_sections.append('Maximum Mark:\n%s' % out_of_marks)
        if use_question and question.strip():
            prompt_sections.append('Question:\n%s' % question.strip())
        if use_model_answer:
            prompt_sections.append('Model Answer:\n%s' % (model_answer.strip() or 'No model answer provided.'))
        if use_note and notes.strip():
            prompt_sections.append('Notes:\n%s' % notes.strip())
        prompt_sections.append('Student Answer:\n%s' % student_answer.strip())
        prompt_sections.append(
            'Return ONLY valid JSON with these keys:\n'
            '{"feedback_html": string, "score": number|null, "score_comment": string|null}.\n'
            'feedback_html must be an HTML fragment using tags such as <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, and <br>.\n'
            'If you cannot determine a mark, set score to null and explain why in score_comment.'
        )

        payload = {
            'model': self.model_key,
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'You are an expert teacher assistant. Follow the supplied instructions exactly, '
                        'produce constructive teacher feedback for students, and when possible determine a mark.'
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
        if include_reasoning:
            payload['reasoning'] = {
                'enabled': True,
                'exclude': False,
                'effort': 'low',
            }
        if self.force_json_response:
            payload['response_format'] = {'type': 'json_object'}
        return payload

    def _collect_applicable_prompt_text(self, selected_prompts, db_model_name):
        self.ensure_one()
        selected = (selected_prompts or self.env['ai_prompts']).filtered(lambda rec: rec.enabled and rec.prompt)
        always = self.env['ai_prompts'].sudo().search([
            ('enabled', '=', True),
            ('always_include', '=', True),
            ('prompt', '!=', False),
        ])
        candidates = (selected | always)

        applicable = candidates.filtered(
            lambda rec: (
                not rec.applies_to_ai_models or self in rec.applies_to_ai_models
            ) and (
                not rec.applies_to_db_models or db_model_name in rec.applies_to_db_models.mapped('model')
            )
        )

        return '\n\n'.join(self._html_to_text(prompt.prompt) for prompt in applicable if prompt.prompt)

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

    def _execute_logged_router_call(self, payload, request_type, related_record=None, stream_callback=None):
        self.ensure_one()
        request_payload = json.dumps(payload, indent=2, sort_keys=True)
        response_json = None
        response_text = False
        prompt_tokens = 0
        completion_tokens = 0
        estimated_cost = 0.0
        error_message = False
        started_at = time.perf_counter()
        endpoint = self._get_router_endpoint()
        result = None
        caught_exc = None

        try:
            if stream_callback:
                response_text, response_json = self._perform_streaming_router_request(payload, stream_callback)
            else:
                response_text = self._perform_router_request(payload)
                response_json = self._parse_router_response_json(response_text)
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
        log_record = self._create_call_log(
            request_type=request_type,
            endpoint=endpoint,
            request_payload=request_payload,
            response_text=response_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=estimated_cost,
            duration_ms=duration_ms,
            related_record=related_record,
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
    ):
        self.ensure_one()
        vals = {
            'state': 'error' if error_message else 'success',
            'request_type': request_type,
            'user_id': self.env.user.id,
            'provider_id': self.provider_id.id,
            'model_id': self.id,
            'model_key': self.model_key,
            'endpoint': endpoint,
            'prompt_tokens': prompt_tokens or 0,
            'completion_tokens': completion_tokens or 0,
            'estimated_cost': estimated_cost or 0.0,
            'duration_ms': duration_ms or 0,
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
            return self.env['aps.ai.call.log'].sudo().create(vals)
        except Exception:
            _logger.exception('Failed to create AI call log for model %s', self.display_name)
        return False

    def _update_call_log_error(self, log_record, exc):
        self.ensure_one()
        if not log_record:
            return
        try:
            log_record.sudo().write({
                'state': 'error',
                'error_message': _exception_to_text(exc),
            })
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

    def _extract_score(self, parsed, raw_content):
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
