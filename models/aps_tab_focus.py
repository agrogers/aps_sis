import json
from odoo import models, fields, api, exceptions


class ApsTabFocusConfig(models.Model):
    _name = 'aps.tab.focus.config'
    _description = 'Tab Focus Configuration'
    _order = 'model_name'

    model_name = fields.Char(
        string='Model Name',
        required=True,
        help='Technical name of the Odoo model (e.g. aps.resources)',
    )
    save_mode = fields.Selection(
        [
            ('none', 'No Saving (default)'),
            ('per_form', 'Per Form – remember last tab across all records'),
            ('per_record', 'Per Record – remember last tab per record'),
        ],
        string='Save Mode',
        default='none',
        required=True,
        help=(
            'Controls how the last-focused notebook tab is persisted for this form.\n'
            '• No Saving: tab focus is not remembered.\n'
            '• Per Form: the last tab the user clicked on ANY record of this model is '
            'restored whenever they open the form.\n'
            '• Per Record: each individual record remembers its own last tab. '
            'Falls back to Per-Form state when no record-level state exists.'
        ),
    )
    default_tab = fields.Char(
        string='Default Tab',
        help=(
            'Name attribute of the notebook page to show when no saved state is available. '
            'Leave blank to use the form\'s own first/active tab.'
        ),
    )
    tab_priority = fields.Text(
        string='Tab Priority (JSON)',
        help=(
            'Optional JSON array of tab names in preference order, e.g. ["summary","details"]. '
            'When no saved state is available the first visible tab from this list is used. '
            'Useful when some tabs may be hidden for certain users or record states.'
        ),
    )

    _sql_constraints = [
        (
            'model_name_uniq',
            'unique(model_name)',
            'A Tab Focus configuration for this model already exists.',
        ),
    ]

    @api.constrains('tab_priority')
    def _check_tab_priority_json(self):
        for record in self:
            if record.tab_priority:
                try:
                    parsed = json.loads(record.tab_priority)
                    if not isinstance(parsed, list):
                        raise ValueError('Must be a JSON array')
                except (ValueError, TypeError):
                    raise exceptions.ValidationError(
                        'Tab Priority must be a valid JSON array of tab name strings, '
                        'e.g. ["tab1", "tab2"]'
                    )


class ApsTabFocusState(models.Model):
    _name = 'aps.tab.focus.state'
    _description = 'Tab Focus State'
    _order = 'user_id, model_name, record_id'

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        ondelete='cascade',
        index=True,
    )
    model_name = fields.Char(string='Model Name', required=True, index=True)
    record_id = fields.Integer(
        string='Record ID',
        default=0,
        help='0 means per-form (not per-record) state.',
    )
    tab_name = fields.Char(string='Tab Name', required=True)

    _sql_constraints = [
        (
            'user_model_record_uniq',
            'unique(user_id, model_name, record_id)',
            'A Tab Focus state for this user/model/record already exists.',
        ),
    ]

    @api.model
    def save_states(self, states):
        """Batch-save tab focus states sent from the browser.

        ``states`` is a list of dicts, each with:
          - ``model_name`` (str, required)
          - ``record_id``  (int, 0 for per-form)
          - ``tab_name``   (str, required)

        Only the calling user's records are written.
        """
        user_id = self.env.user.id
        for state in states:
            model_name = state.get('model_name')
            record_id = int(state.get('record_id') or 0)
            tab_name = state.get('tab_name')
            if not model_name or not tab_name:
                continue
            existing = self.search([
                ('user_id', '=', user_id),
                ('model_name', '=', model_name),
                ('record_id', '=', record_id),
            ], limit=1)
            if existing:
                existing.write({'tab_name': tab_name})
            else:
                self.create({
                    'user_id': user_id,
                    'model_name': model_name,
                    'record_id': record_id,
                    'tab_name': tab_name,
                })
        return True

    @api.model
    def get_states_for_user(self):
        """Return all tab focus states for the current user.

        Returns a list of dicts: [{model_name, record_id, tab_name}, ...].
        """
        records = self.search([('user_id', '=', self.env.user.id)])
        return [
            {
                'model_name': r.model_name,
                'record_id': r.record_id,
                'tab_name': r.tab_name,
            }
            for r in records
        ]
