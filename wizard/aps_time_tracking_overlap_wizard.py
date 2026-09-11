from odoo import _, api, fields, models
from odoo.exceptions import UserError


class APSTimeTrackingOverlapWizard(models.TransientModel):
    _name = 'aps.time.tracking.overlap.wizard'
    _description = 'Resolve Time Tracking Overlaps'

    record_ids = fields.Many2many(
        'aps.time.tracking',
        string='Time Entries',
        required=True,
        default=lambda self: self._default_record_ids(),
    )
    overlap_count = fields.Integer(
        string='Overlaps Found',
        readonly=True,
    )
    overlap_minutes = fields.Float(
        string='Overlapping Minutes',
        readonly=True,
    )
    partner_names = fields.Char(
        string='People with Overlaps',
        readonly=True,
    )

    @api.model
    def _context_record_ids(self):
        default_record_ids = self.env.context.get('default_record_ids')
        if isinstance(default_record_ids, (list, tuple)):
            if all(isinstance(record_id, int) for record_id in default_record_ids):
                return list(default_record_ids)
            for command in default_record_ids:
                if (
                    isinstance(command, (list, tuple))
                    and len(command) >= 3
                    and command[0] == 6
                ):
                    return list(command[2])
        return self.env.context.get('active_ids', [])

    @api.model
    def _default_record_ids(self):
        return self._context_record_ids()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self._context_record_ids()
        if active_ids:
            summary = self.env['aps.time.tracking'].with_context(
                active_ids=active_ids
            ).action_check_overlaps()
            if 'overlap_count' in fields_list:
                res['overlap_count'] = summary['overlap_count']
            if 'overlap_minutes' in fields_list:
                res['overlap_minutes'] = summary['overlap_minutes']
            if 'partner_names' in fields_list:
                res['partner_names'] = ', '.join(summary['partner_names'])
        return res

    def action_fix(self):
        """Resolve the overlaps and show a toast summarising what changed."""
        self.ensure_one()
        if not self.record_ids:
            raise UserError(_("No time entries selected."))

        result = self.env['aps.time.tracking'].browse(
            self.record_ids.ids
        ).action_resolve_overlaps(self.record_ids.ids)

        adjusted = result['adjusted_count']
        remaining = result['remaining_overlaps']

        if adjusted:
            message = _('Adjusted %d time entry(ies) to remove overlaps.') % adjusted
        else:
            message = _('No time entries needed adjusting.')

        if remaining:
            message += _(' %d overlap(s) could not be resolved automatically.') % remaining

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Overlaps Resolved'),
                'message': message,
                'type': 'success' if not remaining else 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }