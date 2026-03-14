from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


def _make_forms_record(env, model_name='aps.resources', form_name='view_default', tabs=None):
    """Helper: create an aps.tab.focus.forms record with optional tabs."""
    tabs = tabs or [
        {'tab_string': 'General', 'tab_name': 'general', 'sequence': 10},
        {'tab_string': 'Details', 'tab_name': 'details', 'sequence': 20},
    ]
    return env['aps.tab.focus.forms'].create({
        'model_name': model_name,
        'form_name': form_name,
        'tab_ids': [(0, 0, t) for t in tabs],
    })


class TestApsTabFocusForms(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Forms = self.env['aps.tab.focus.forms']
        self.FormTab = self.env['aps.tab.focus.form.tab']

    def test_register_form_creates_new(self):
        """register_form creates a new record with tabs on first call."""
        tabs = [
            {'string': 'General', 'name': 'general'},
            {'string': 'Details', 'name': 'details'},
        ]
        form_id = self.Forms.register_form('aps.resources', 'view_res_form', tabs)
        rec = self.Forms.browse(form_id)
        self.assertEqual(rec.model_name, 'aps.resources')
        self.assertEqual(rec.form_name, 'view_res_form')
        self.assertEqual(len(rec.tab_ids), 2)
        self.assertIn(self.env.user, rec.user_ids)

    def test_register_form_idempotent(self):
        """Calling register_form twice with the same args does not duplicate records."""
        tabs = [{'string': 'Summary', 'name': 'summary'}]
        id1 = self.Forms.register_form('aps.resource.task', 'view_task_form', tabs)
        id2 = self.Forms.register_form('aps.resource.task', 'view_task_form', tabs)
        self.assertEqual(id1, id2)
        rec = self.Forms.browse(id1)
        self.assertEqual(len(rec.tab_ids), 1)

    def test_register_form_appends_new_tabs(self):
        """Subsequent register_form calls only add tabs that were not previously recorded."""
        tabs_v1 = [{'string': 'Tab A', 'name': 'tab_a'}]
        form_id = self.Forms.register_form('aps.resources', 'view_test_form', tabs_v1)
        tabs_v2 = [
            {'string': 'Tab A', 'name': 'tab_a'},
            {'string': 'Tab B', 'name': 'tab_b'},
        ]
        self.Forms.register_form('aps.resources', 'view_test_form', tabs_v2)
        rec = self.Forms.browse(form_id)
        self.assertEqual(len(rec.tab_ids), 2)
        self.assertEqual(
            sorted(rec.tab_ids.mapped('tab_string')),
            ['Tab A', 'Tab B'],
        )

    def test_register_form_skips_empty_string(self):
        """Tabs with an empty string label are silently skipped."""
        tabs = [{'string': '', 'name': 'no_label'}, {'string': 'Real Tab', 'name': 'real'}]
        form_id = self.Forms.register_form('aps.resources', 'view_skip_form', tabs)
        rec = self.Forms.browse(form_id)
        self.assertEqual(len(rec.tab_ids), 1)
        self.assertEqual(rec.tab_ids.tab_string, 'Real Tab')

    def test_model_form_unique_constraint(self):
        """Direct creation of two aps.tab.focus.forms with same model+form raises."""
        self.Forms.create({'model_name': 'aps.resources', 'form_name': 'dup_form'})
        with self.assertRaises(Exception):
            self.Forms.create({'model_name': 'aps.resources', 'form_name': 'dup_form'})


class TestApsTabFocusConfig(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Config = self.env['aps.tab.focus.config']
        self.forms_rec = _make_forms_record(self.env)

    def test_create_config(self):
        """Create a basic config record linked to a form."""
        cfg = self.Config.create({
            'forms_id': self.forms_rec.id,
            'save_mode': 'per_form',
        })
        self.assertEqual(cfg.model_name, 'aps.resources')
        self.assertEqual(cfg.form_name, 'view_default')
        self.assertEqual(cfg.save_mode, 'per_form')

    def test_unique_forms_id(self):
        """Two configs for the same form are not allowed."""
        self.Config.create({
            'forms_id': self.forms_rec.id,
            'save_mode': 'none',
        })
        with self.assertRaises(Exception):
            self.Config.create({
                'forms_id': self.forms_rec.id,
                'save_mode': 'per_form',
            })

    def test_default_tab_id_accepted(self):
        """Config accepts a default_tab_id from the linked form's tabs."""
        tab = self.forms_rec.tab_ids[0]
        cfg = self.Config.create({
            'forms_id': self.forms_rec.id,
            'save_mode': 'per_form',
            'default_tab_id': tab.id,
        })
        self.assertEqual(cfg.default_tab_id.tab_string, 'General')

    def test_tab_priority_ids(self):
        """Config accepts an ordered One2many of tab priority entries."""
        tabs = self.forms_rec.tab_ids
        cfg = self.Config.create({
            'forms_id': self.forms_rec.id,
            'save_mode': 'per_form',
            'tab_priority_ids': [
                (0, 0, {'tab_id': tabs[1].id, 'sequence': 10}),
                (0, 0, {'tab_id': tabs[0].id, 'sequence': 20}),
            ],
        })
        priority_strings = cfg.tab_priority_ids.sorted('sequence').mapped('tab_string')
        self.assertEqual(priority_strings, ['Details', 'General'])

    def test_get_configs_for_js(self):
        """get_configs_for_js returns a dict keyed by model_name|form_name."""
        tabs = self.forms_rec.tab_ids
        cfg = self.Config.create({
            'forms_id': self.forms_rec.id,
            'save_mode': 'per_record',
            'default_tab_id': tabs[0].id,
            'tab_priority_ids': [
                (0, 0, {'tab_id': tabs[1].id, 'sequence': 10}),
                (0, 0, {'tab_id': tabs[0].id, 'sequence': 20}),
            ],
        })
        result = self.Config.get_configs_for_js()
        key = 'aps.resources|view_default'
        self.assertIn(key, result)
        entry = result[key]
        self.assertEqual(entry['save_mode'], 'per_record')
        self.assertEqual(entry['default_tab']['string'], 'General')
        self.assertEqual(len(entry['tab_priority']), 2)
        self.assertEqual(entry['tab_priority'][0]['string'], 'Details')  # sequence 10


class TestApsTabFocusState(TransactionCase):

    def setUp(self):
        super().setUp()
        self.State = self.env['aps.tab.focus.state']

    def test_save_states_creates_new(self):
        """save_states creates a new state record when none exists."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 42, 'tab_string': 'Details'},
        ])
        state = self.State.search([
            ('user_id', '=', self.env.user.id),
            ('model_name', '=', 'aps.resources'),
            ('record_id', '=', 42),
        ])
        self.assertEqual(len(state), 1)
        self.assertEqual(state.tab_name, 'Details')

    def test_save_states_updates_existing(self):
        """save_states updates an existing record instead of creating a duplicate."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 1, 'tab_string': 'Tab A'},
        ])
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 1, 'tab_string': 'Tab B'},
        ])
        states = self.State.search([
            ('user_id', '=', self.env.user.id),
            ('model_name', '=', 'aps.resources'),
            ('record_id', '=', 1),
        ])
        self.assertEqual(len(states), 1)
        self.assertEqual(states.tab_name, 'Tab B')

    def test_save_states_skips_incomplete(self):
        """save_states silently skips entries missing model_name or tab_string."""
        self.State.save_states([
            {'record_id': 5, 'tab_string': 'Tab X'},          # missing model_name
            {'model_name': 'aps.resources', 'record_id': 5},  # missing tab_string
        ])
        states = self.State.search([('user_id', '=', self.env.user.id)])
        self.assertEqual(len(states), 0)

    def test_save_states_per_form_record_id_zero(self):
        """record_id=0 is used for per-form (not per-record) state."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 0, 'tab_string': 'Summary'},
        ])
        state = self.State.search([
            ('user_id', '=', self.env.user.id),
            ('model_name', '=', 'aps.resources'),
            ('record_id', '=', 0),
        ])
        self.assertEqual(len(state), 1)
        self.assertEqual(state.tab_name, 'Summary')

    def test_get_states_for_user_returns_own(self):
        """get_states_for_user returns only the current user's states."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 10, 'tab_string': 'Info'},
        ])
        results = self.State.get_states_for_user()
        self.assertTrue(any(
            r['model_name'] == 'aps.resources' and r['record_id'] == 10 and r['tab_string'] == 'Info'
            for r in results
        ))

    def test_save_states_batch(self):
        """save_states handles multiple states in a single call."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 1, 'tab_string': 'Tab A'},
            {'model_name': 'aps.resources', 'record_id': 2, 'tab_string': 'Tab B'},
            {'model_name': 'aps.resource.task', 'record_id': 0, 'tab_string': 'Overview'},
        ])
        states = self.State.search([('user_id', '=', self.env.user.id)])
        self.assertEqual(len(states), 3)

