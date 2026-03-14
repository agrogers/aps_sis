from lxml import etree

from odoo import models, fields, api, exceptions


class ApsTabFocusFormTab(models.Model):
    """A single notebook tab discovered on a particular Odoo form view."""

    _name = 'aps.tab.focus.form.tab'
    _description = 'Tab Focus – Form Tab'
    _order = 'form_id, sequence, id'
    _rec_name = 'tab_string'

    form_id = fields.Many2one(
        'aps.tab.focus.forms',
        string='Form',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    tab_string = fields.Char(
        string='Tab Label',
        required=True,
        help='The visible string label of the notebook tab.',
    )
    tab_name = fields.Char(
        string='Tab name attribute',
        help='The HTML name attribute of the tab, if the page defines one.',
    )


class ApsTabFocusForms(models.Model):
    """Registry of Odoo form views that contain notebooks.

    Populated automatically the first time any user visits a form that has at
    least one notebook page.  Stores the list of tabs so that the Tab Focus
    configuration UI can present them as a dropdown / draggable list.
    """

    _name = 'aps.tab.focus.forms'
    _description = 'Tab Focus – Form Registry'
    _order = 'model_name, form_name'

    model_name = fields.Char(string='Model Name', required=True, index=True, readonly=True)
    form_name = fields.Char(
        string='Form Name',
        required=True,
        readonly=True,
        help='Identifier for the specific form view (view XML-ID or numeric view ID).',
    )
    display_name = fields.Char(compute='_compute_display_name')

    @api.depends('form_name', 'model_name')
    def _compute_display_name(self):
        for rec in self:
            raw = rec.form_name or ''
            # If form_name is numeric, look up the ir.ui.view name
            if raw.isdigit():
                view = self.env['ir.ui.view'].browse(int(raw))
                if view.exists():
                    raw = view.name or raw
            # Convert dotted/underscored name to title case
            rec.display_name = raw.replace('.', ' ').replace('_', ' ').strip().title()
    tab_ids = fields.One2many(
        'aps.tab.focus.form.tab',
        'form_id',
        string='Tabs',
    )
    user_ids = fields.Many2many(
        'res.users',
        'aps_tab_focus_forms_users_rel',
        'form_id',
        'user_id',
        string='Users',
        help='Users who have visited this form at least once.',
    )
    config_ids = fields.One2many(
        'aps.tab.focus.config',
        'forms_id',
        string='Configuration',
    )

    _sql_constraints = [
        (
            'model_form_uniq',
            'unique(model_name, form_name)',
            'A form registry entry for this model/form already exists.',
        ),
    ]

    @api.model
    def register_form(self, model_name, form_name, tabs):
        """Register or update a form and its tabs.

        Called from the browser the first time (or whenever new tabs appear).

        ``tabs`` is a list of dicts, each with:
          - ``string``  (str, required) – the visible tab label
          - ``name``    (str, optional) – the HTML name attribute of the tab

        Returns the ID of the ``aps.tab.focus.forms`` record.
        """
        user = self.env.user
        rec = self.search([
            ('model_name', '=', model_name),
            ('form_name', '=', form_name),
        ], limit=1)

        if not rec:
            tab_vals = [
                {
                    'sequence': i * 10,
                    'tab_string': t.get('string', ''),
                    'tab_name': t.get('name', '') or '',
                }
                for i, t in enumerate(tabs)
                if t.get('string')
            ]
            rec = self.create({
                'model_name': model_name,
                'form_name': form_name,
                'tab_ids': [(0, 0, v) for v in tab_vals],
                'user_ids': [(4, user.id)],
            })
        else:
            # Add the current user if not already in the list.
            if user not in rec.user_ids:
                rec.write({'user_ids': [(4, user.id)]})
            # Append any tabs that weren't recorded before.
            existing_strings = set(rec.tab_ids.mapped('tab_string'))
            new_tabs = [t for t in tabs if t.get('string') and t['string'] not in existing_strings]
            if new_tabs:
                max_seq = max(rec.tab_ids.mapped('sequence') or [0])
                rec.tab_ids.create([
                    {
                        'form_id': rec.id,
                        'sequence': max_seq + (i + 1) * 10,
                        'tab_string': t.get('string', ''),
                        'tab_name': t.get('name', '') or '',
                    }
                    for i, t in enumerate(new_tabs)
                ])

        return rec.id

    def action_sync_tabs_from_arch(self):
        """Parse the raw view arch XML and sync all <page> tabs into the registry.

        This captures every notebook page defined in the view, including those
        that may be invisible to certain users or record states.
        """
        self.ensure_one()
        view = None
        form_name = self.form_name or ''
        if form_name.isdigit():
            view = self.env['ir.ui.view'].browse(int(form_name))
        else:
            # form_name may be an XML-ID like "module.view_name_form"
            view = self.env.ref(form_name, raise_if_not_found=False)
        if not view or not view.exists():
            return

        # Get the combined arch (with all inherited views applied)
        arch_str = view.get_combined_arch()
        if isinstance(arch_str, str):
            arch = etree.fromstring(arch_str.encode('utf-8'))
        else:
            arch = arch_str
        pages = arch.iter('page')

        existing_strings = {t.tab_string: t for t in self.tab_ids}
        existing_names = {t.tab_name: t for t in self.tab_ids if t.tab_name}
        max_seq = max(self.tab_ids.mapped('sequence') or [0])
        new_tab_vals = []

        for page in pages:
            page_string = page.get('string', '').strip()
            page_name = page.get('name', '').strip()
            if not page_string:
                continue
            # Skip if already registered (by string or by name)
            if page_string in existing_strings:
                # Update the name attr if it was missing
                if page_name and not existing_strings[page_string].tab_name:
                    existing_strings[page_string].tab_name = page_name
                continue
            if page_name and page_name in existing_names:
                continue
            max_seq += 10
            new_tab_vals.append({
                'form_id': self.id,
                'sequence': max_seq,
                'tab_string': page_string,
                'tab_name': page_name,
            })

        if new_tab_vals:
            self.env['aps.tab.focus.form.tab'].create(new_tab_vals)


class ApsTabFocusConfigTab(models.Model):
    """An entry in the ordered tab-priority list for a Tab Focus configuration."""

    _name = 'aps.tab.focus.config.tab'
    _description = 'Tab Focus Config – Tab Priority Entry'
    _order = 'config_id, sequence, id'

    config_id = fields.Many2one(
        'aps.tab.focus.config',
        string='Configuration',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    tab_id = fields.Many2one(
        'aps.tab.focus.form.tab',
        string='Tab',
        required=True,
        ondelete='cascade',
    )
    tab_string = fields.Char(
        related='tab_id.tab_string',
        string='Tab Label',
        readonly=True,
        store=True,
    )


class ApsTabFocusConfig(models.Model):
    _name = 'aps.tab.focus.config'
    _description = 'Tab Focus Configuration'
    _order = 'model_name, form_name'

    forms_id = fields.Many2one(
        'aps.tab.focus.forms',
        string='Form',
        required=True,
        ondelete='cascade',
        index=True,
        help='The form view this configuration applies to.',
    )
    model_name = fields.Char(
        related='forms_id.model_name',
        string='Model Name',
        store=True,
        readonly=True,
    )
    form_name = fields.Char(
        related='forms_id.form_name',
        string='Form Name',
        store=True,
        readonly=True,
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
    default_tab_id = fields.Many2one(
        'aps.tab.focus.form.tab',
        string='Default Tab',
        ondelete='set null',
        domain="[('form_id', '=', forms_id)]",
        help=(
            'The tab to show when no saved state is available. '
            'Leave blank to use the form\'s own first/active tab.'
        ),
    )
    tab_priority_ids = fields.One2many(
        'aps.tab.focus.config.tab',
        'config_id',
        string='Tab Priority',
        help=(
            'Ordered list of tabs tried when no saved state is available. '
            'The first visible tab in this list is used. '
            'Drag rows to reorder. Useful when some tabs may be hidden for '
            'certain users or record states.'
        ),
    )

    _sql_constraints = [
        (
            'forms_uniq',
            'unique(forms_id)',
            'A Tab Focus configuration for this form already exists.',
        ),
    ]

    def action_sync_tabs_from_arch(self):
        self.ensure_one()
        self.forms_id.action_sync_tabs_from_arch()

    @api.model
    def get_configs_for_js(self):
        """Return all tab focus configs in a JS-friendly format.

        Returns a dict keyed by ``"model_name|form_name"`` with the fields
        needed by the browser-side tab-focus feature.
        """
        configs = self.search([])
        result = {}
        for c in configs:
            key = f"{c.model_name}|{c.form_name}"
            result[key] = {
                'save_mode': c.save_mode,
                'default_tab': (
                    {
                        'string': c.default_tab_id.tab_string,
                        'name': c.default_tab_id.tab_name,
                    }
                    if c.default_tab_id
                    else False
                ),
                'tab_priority': [
                    {'string': t.tab_id.tab_string, 'name': t.tab_id.tab_name}
                    for t in c.tab_priority_ids
                ],
            }
        return result


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
          - ``tab_string`` (str, required) – the visible tab label

        Only the calling user's records are written.
        """
        user_id = self.env.user.id
        for state in states:
            model_name = state.get('model_name')
            record_id = int(state.get('record_id') or 0)
            tab_string = state.get('tab_string')
            if not model_name or not tab_string:
                continue
            existing = self.search([
                ('user_id', '=', user_id),
                ('model_name', '=', model_name),
                ('record_id', '=', record_id),
            ], limit=1)
            if existing:
                existing.write({'tab_name': tab_string})
            else:
                self.create({
                    'user_id': user_id,
                    'model_name': model_name,
                    'record_id': record_id,
                    'tab_name': tab_string,
                })
        return True

    @api.model
    def get_states_for_user(self):
        """Return all tab focus states for the current user.

        Returns a list of dicts: [{model_name, record_id, tab_string}, ...].
        """
        records = self.search([('user_id', '=', self.env.user.id)])
        return [
            {
                'model_name': r.model_name,
                'record_id': r.record_id,
                'tab_string': r.tab_name,
            }
            for r in records
        ]
