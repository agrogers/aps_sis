from odoo import api, fields, models


class APSAISampleComparison(models.Model):
    _name = 'aps.ai.sample.comparison'
    _description = 'AI Sample Comparison Evidence'
    _order = 'create_date, id'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    submission_id = fields.Many2one(
        'aps.resource.submission',
        string='Submission',
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    resource_id = fields.Many2one(
        'aps.resources',
        string='Resource Test',
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    run_id = fields.Many2one('aps.ai.run', ondelete='set null', index=True, readonly=True)
    benchmark_resource_id = fields.Many2one(
        'aps.resources',
        string='Benchmark Resource',
        ondelete='set null',
        index=True,
        readonly=True,
    )
    benchmark_name = fields.Char(string='Benchmark Name', readonly=True)
    model_name = fields.Char(string='Model Name', readonly=True)
    official_score = fields.Float(string='Official Score', digits=(16, 2), readonly=True)
    benchmark_maximum = fields.Float(string='Benchmark Maximum', digits=(16, 2), readonly=True)
    result = fields.Selection(
        [('better', 'Better'), ('same', 'Same'), ('worse', 'Worse')],
        readonly=True,
    )
    fitted_result = fields.Selection(
        [('better', 'Better'), ('same', 'Same'), ('worse', 'Worse')],
        string='Monotonic Fit',
        readonly=True,
    )
    status = fields.Selection(
        [('complete', 'Complete'), ('invalid', 'Invalid Response'), ('error', 'Call Failed')],
        required=True,
        readonly=True,
    )
    reason = fields.Text(readonly=True)
    raw_response = fields.Text(readonly=True)
    model_id = fields.Many2one('aps.ai.model', ondelete='set null', readonly=True)
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    estimated_cost = fields.Float(digits=(16, 6), readonly=True)
    prompt_name = fields.Char(readonly=True)
    prompt_version = fields.Char(default='comparison-v1', readonly=True)
    anomaly = fields.Boolean(readonly=True)
    anomaly_severity = fields.Float(digits=(5, 4), readonly=True)
    compared_at = fields.Datetime(default=fields.Datetime.now, readonly=True, required=True)

    @api.depends('submission_id.display_name', 'resource_id.display_name', 'benchmark_resource_id.display_name', 'result')
    def _compute_display_name(self):
        for record in self:
            target = record.submission_id or record.resource_id
            target_label = target.display_name if target else 'AI Marking'
            benchmark_label = record.benchmark_resource_id.display_name if record.benchmark_resource_id else 'Benchmark'
            result_label = dict(record._fields['result'].selection).get(record.result, record.status or 'Pending')
            record.display_name = '%s — %s — %s' % (target_label, benchmark_label, result_label)