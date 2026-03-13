from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestApsTabFocusConfig(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Config = self.env['aps.tab.focus.config']

    def test_create_config(self):
        """Create a basic config record."""
        cfg = self.Config.create({
            'model_name': 'aps.resources',
            'save_mode': 'per_form',
        })
        self.assertEqual(cfg.model_name, 'aps.resources')
        self.assertEqual(cfg.save_mode, 'per_form')

    def test_unique_model_name(self):
        """Two configs for the same model are not allowed."""
        self.Config.create({'model_name': 'aps.resources', 'save_mode': 'none'})
        with self.assertRaises(Exception):
            self.Config.create({'model_name': 'aps.resources', 'save_mode': 'per_form'})

    def test_tab_priority_valid_json(self):
        """Valid JSON array for tab_priority is accepted."""
        cfg = self.Config.create({
            'model_name': 'aps.resource.task',
            'save_mode': 'per_form',
            'tab_priority': '["tab1", "tab2"]',
        })
        self.assertEqual(cfg.tab_priority, '["tab1", "tab2"]')

    def test_tab_priority_invalid_json_raises(self):
        """Invalid JSON raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.Config.create({
                'model_name': 'aps.resource.task',
                'save_mode': 'per_form',
                'tab_priority': 'not-valid-json',
            })

    def test_tab_priority_non_array_raises(self):
        """JSON that is not an array raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.Config.create({
                'model_name': 'aps.resource.task',
                'save_mode': 'per_form',
                'tab_priority': '{"key": "value"}',
            })


class TestApsTabFocusState(TransactionCase):

    def setUp(self):
        super().setUp()
        self.State = self.env['aps.tab.focus.state']

    def test_save_states_creates_new(self):
        """save_states creates a new state record when none exists."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 42, 'tab_name': 'details'},
        ])
        state = self.State.search([
            ('user_id', '=', self.env.user.id),
            ('model_name', '=', 'aps.resources'),
            ('record_id', '=', 42),
        ])
        self.assertEqual(len(state), 1)
        self.assertEqual(state.tab_name, 'details')

    def test_save_states_updates_existing(self):
        """save_states updates an existing record instead of creating a duplicate."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 1, 'tab_name': 'tab_a'},
        ])
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 1, 'tab_name': 'tab_b'},
        ])
        states = self.State.search([
            ('user_id', '=', self.env.user.id),
            ('model_name', '=', 'aps.resources'),
            ('record_id', '=', 1),
        ])
        self.assertEqual(len(states), 1)
        self.assertEqual(states.tab_name, 'tab_b')

    def test_save_states_skips_incomplete(self):
        """save_states silently skips entries missing model_name or tab_name."""
        self.State.save_states([
            {'record_id': 5, 'tab_name': 'tab_x'},          # missing model_name
            {'model_name': 'aps.resources', 'record_id': 5}, # missing tab_name
        ])
        states = self.State.search([('user_id', '=', self.env.user.id)])
        self.assertEqual(len(states), 0)

    def test_save_states_per_form_record_id_zero(self):
        """record_id=0 is used for per-form (not per-record) state."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 0, 'tab_name': 'summary'},
        ])
        state = self.State.search([
            ('user_id', '=', self.env.user.id),
            ('model_name', '=', 'aps.resources'),
            ('record_id', '=', 0),
        ])
        self.assertEqual(len(state), 1)
        self.assertEqual(state.tab_name, 'summary')

    def test_get_states_for_user_returns_own(self):
        """get_states_for_user returns only the current user's states."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 10, 'tab_name': 'info'},
        ])
        results = self.State.get_states_for_user()
        self.assertTrue(any(
            r['model_name'] == 'aps.resources' and r['record_id'] == 10 and r['tab_name'] == 'info'
            for r in results
        ))

    def test_save_states_batch(self):
        """save_states handles multiple states in a single call."""
        self.State.save_states([
            {'model_name': 'aps.resources', 'record_id': 1, 'tab_name': 'tab_a'},
            {'model_name': 'aps.resources', 'record_id': 2, 'tab_name': 'tab_b'},
            {'model_name': 'aps.resource.task', 'record_id': 0, 'tab_name': 'overview'},
        ])
        states = self.State.search([('user_id', '=', self.env.user.id)])
        self.assertEqual(len(states), 3)
