import json
import logging
from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class APSAICallLog(models.Model):
    _name = 'aps.ai.call.log'
    _description = 'APEX AI Call Log'
    _order = 'create_date desc, id desc'

    state = fields.Selection(
        [('success', 'Success'), ('error', 'Error'), ('dry_run', 'Dry Run')],
        required=True,
        readonly=True,
    )
    request_type = fields.Selection(
        [('connection_test', 'Connection Test'), ('submission_feedback', 'Submission Feedback')],
        required=True,
        readonly=True,
    )
    user_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    provider_id = fields.Many2one('aps.ai.provider', readonly=True, ondelete='set null')
    model_id = fields.Many2one('aps.ai.model', readonly=True, ondelete='set null')
    model_key = fields.Char(readonly=True)
    endpoint = fields.Char(readonly=True)
    related_model = fields.Char(readonly=True)
    related_res_id = fields.Integer(readonly=True)
    related_display_name = fields.Char(readonly=True)
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    estimated_cost = fields.Float(readonly=True, digits=(16, 6))
    duration_ms = fields.Integer(readonly=True)
    prompt_names_used = fields.Text(readonly=True)
    request_payload = fields.Text(readonly=True)
    response_body = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)
    request_payload_html = fields.Html(
        compute='_compute_pretty_html', string='Request Payload', sanitize=False
    )
    response_body_html = fields.Html(
        compute='_compute_pretty_html', string='Response Body', sanitize=False
    )

    # Ordered display sections for structured AI feedback responses.
    # summary is always first so the summary paragraph leads the display.
    _AI_RESPONSE_SECTION_ORDER = [
        ('summary', 'Summary'),
        ('detailed_analysis', 'Detailed Analysis'),
        ('results_table', 'Results Table'),
        ('score', 'Score'),
        ('score_comment', 'Score Comment'),
    ]

    @api.depends('request_payload', 'response_body')
    def _compute_pretty_html(self):
        for record in self:
            record.request_payload_html = record._pretty_json_html(record.request_payload)
            record.response_body_html = record._render_response_body_html(record.response_body)

    def _render_response_body_html(self, raw):
        """Render the AI response body with known sections in display order.

        summary is rendered first so the summary paragraph always
        appears at the top of the log viewer.  Any remaining / unknown keys
        are appended afterwards as a raw JSON block.
        """
        if not raw:
            return Markup('<pre class="o_field_text"><em>—</em></pre>')
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._pretty_json_html(raw)
        if not isinstance(parsed, dict):
            return self._pretty_json_html(raw)
        if 'opening_summary' in parsed and 'summary' not in parsed:
            parsed = dict(parsed)
            parsed['summary'] = parsed.pop('opening_summary')

        _pre_style = (
            'white-space:pre-wrap;word-break:break-word;font-size:12px;'
            'background:#f8f9fa;padding:12px;border-radius:4px;overflow:auto;max-height:400px;'
        )
        _h_style = 'font-size:13px;font-weight:600;margin:12px 0 4px;color:#495057;'
        parts = []
        known_keys = {k for k, _ in self._AI_RESPONSE_SECTION_ORDER}
        for key, label in self._AI_RESPONSE_SECTION_ORDER:
            value = parsed.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                # Python string already has real newlines — display directly.
                text = value
            else:
                # Re-serialise non-string scalars/objects, then unescape \n so
                # embedded newlines render as line breaks instead of '\n' text.
                text = json.dumps(value, indent=2, ensure_ascii=False).replace('\\n', '\n')
            parts.append(
                Markup('<div><p style="%s">%s</p><pre style="%s">%s</pre></div>') % (
                    _h_style, label, _pre_style, escape(text)
                )
            )
        remainder = {k: v for k, v in parsed.items() if k not in known_keys}
        if remainder:
            extra = json.dumps(remainder, indent=2, ensure_ascii=False).replace('\\n', '\n')
            parts.append(
                Markup('<div><p style="%s">Other</p><pre style="%s">%s</pre></div>') % (
                    _h_style, _pre_style, escape(extra)
                )
            )
        return Markup('').join(parts)

    def _pretty_json_html(self, raw):
        if not raw:
            return Markup('<pre class="o_field_text"><em>—</em></pre>')
        try:
            parsed = json.loads(raw)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pretty = raw
        # Unescape \n sequences inside JSON string values so they render as
        # real line breaks rather than the literal two characters '\n'.
        pretty = pretty.replace('\\n', '\n')
        return Markup('<pre style="white-space:pre-wrap;word-break:break-word;font-size:12px;background:#f8f9fa;padding:12px;border-radius:4px;overflow:auto;max-height:600px;">%s</pre>') % escape(pretty)

    @api.depends('request_type', 'model_id.display_name', 'create_date', 'state')
    def _compute_display_name(self):
        request_type_labels = dict(self._fields['request_type'].selection)
        state_labels = dict(self._fields['state'].selection)
        for record in self:
            type_label = request_type_labels.get(record.request_type, record.request_type or _('Unknown'))
            state_label = state_labels.get(record.state, record.state or _('Unknown'))
            model_label = record.model_id.display_name or record.model_key or _('No Model')
            created = fields.Datetime.to_string(record.create_date) if record.create_date else ''
            record.display_name = '%s - %s - %s%s' % (
                type_label,
                model_label,
                state_label,
                (' - %s' % created) if created else '',
            )

    @api.model
    def get_dashboard_data(self, days=30):
        days = int(days or 30)
        domain = []
        if days > 0:
            cutoff = fields.Datetime.now() - timedelta(days=days)
            domain.append(('create_date', '>=', fields.Datetime.to_string(cutoff)))

        logs = self.search(domain, order='create_date asc')
        total_queries = len(logs)
        total_cost = 0.0
        total_duration_ms = 0
        success_count = 0
        model_stats_map = {}
        provider_cost_map = defaultdict(float)
        daily_stats_map = {}

        for log in logs:
            total_cost += float(log.estimated_cost or 0.0)
            total_duration_ms += int(log.duration_ms or 0)
            if log.state == 'success':
                success_count += 1

            model_name = log.model_id.display_name or log.model_key or _('Unknown Model')
            provider_name = log.provider_id.name or _('Unknown Provider')
            model_key = log.model_id.id or log.model_key or model_name
            model_stats = model_stats_map.setdefault(model_key, {
                'model_name': model_name,
                'provider_name': provider_name,
                'count': 0,
                'total_cost': 0.0,
                'total_duration_ms': 0,
                'prompt_tokens': 0,
                'completion_tokens': 0,
            })
            model_stats['count'] += 1
            model_stats['total_cost'] += float(log.estimated_cost or 0.0)
            model_stats['total_duration_ms'] += int(log.duration_ms or 0)
            model_stats['prompt_tokens'] += int(log.prompt_tokens or 0)
            model_stats['completion_tokens'] += int(log.completion_tokens or 0)

            provider_cost_map[provider_name] += float(log.estimated_cost or 0.0)

            local_dt = fields.Datetime.context_timestamp(self, log.create_date) if log.create_date else False
            day_key = fields.Date.to_string(local_dt.date()) if local_dt else _('Unknown')
            day_stats = daily_stats_map.setdefault(day_key, {'count': 0, 'cost': 0.0})
            day_stats['count'] += 1
            day_stats['cost'] += float(log.estimated_cost or 0.0)

        model_stats = sorted(
            ({
                **stats,
                'avg_duration_ms': round((stats['total_duration_ms'] / stats['count']), 2) if stats['count'] else 0,
            } for stats in model_stats_map.values()),
            key=lambda item: (-item['count'], -item['total_cost'], item['model_name']),
        )
        top_model = model_stats[0] if model_stats else None
        daily_labels = sorted(daily_stats_map.keys())

        return {
            'summary': {
                'days': days,
                'total_queries': total_queries,
                'total_cost': round(total_cost, 6),
                'avg_duration_ms': round((total_duration_ms / total_queries), 2) if total_queries else 0,
                'success_rate': round((success_count / total_queries) * 100, 1) if total_queries else 0,
                'models_used': len(model_stats),
                'top_model_name': top_model['model_name'] if top_model else _('No AI calls yet'),
                'top_model_count': top_model['count'] if top_model else 0,
            },
            'model_usage': {
                'labels': [item['model_name'] for item in model_stats[:8]],
                'counts': [item['count'] for item in model_stats[:8]],
                'costs': [round(item['total_cost'], 6) for item in model_stats[:8]],
            },
            'provider_cost': {
                'labels': [item[0] for item in sorted(provider_cost_map.items(), key=lambda pair: (-pair[1], pair[0]))[:8]],
                'costs': [round(item[1], 6) for item in sorted(provider_cost_map.items(), key=lambda pair: (-pair[1], pair[0]))[:8]],
            },
            'daily_trend': {
                'labels': daily_labels,
                'counts': [daily_stats_map[label]['count'] for label in daily_labels],
                'costs': [round(daily_stats_map[label]['cost'], 6) for label in daily_labels],
            },
            'model_stats': model_stats[:12],
        }
