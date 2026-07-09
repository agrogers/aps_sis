"""Quick test for the vote round mass update wizard."""
from odoo.tests import common


class TestVoteRoundMassUpdate(common.TransactionCase):
    def test_wizard_create_and_update(self):
        """Test the wizard can be created and perform updates."""
        # Create test vote rounds
        cat = self.env['aps.award.category'].create({
            'name': 'Test Category',
        })
        rounds = self.env['aps.award.vote.round'].create([
            {'name': 'Test Round Alpha', 'status': 'draft', 'datetime_start': '2026-01-01 00:00:00', 'datetime_end': '2026-01-31 00:00:00'},
            {'name': 'Test Round Beta', 'status': 'draft', 'datetime_start': '2026-02-01 00:00:00', 'datetime_end': '2026-02-28 00:00:00'},
        ])
        self.assertEqual(len(rounds), 2)

        # Create wizard with context simulating list selection
        wizard = self.env['aps.award.vote.round.mass.update.wizard'].with_context(
            active_ids=rounds.ids
        ).create({})
        self.assertEqual(len(wizard.vote_round_ids), 2)
        self.assertCountEqual(wizard.vote_round_ids.ids, rounds.ids)

        # Perform update - name and status
        wizard.update_name = True
        wizard.name_value = 'Updated Round'
        wizard.update_status = True
        wizard.status_value = 'open'
        wizard.update_recurring_days = True
        wizard.recurring_days_value = 7

        result = wizard.action_update()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'success')

        # Verify updates applied
        for r in rounds:
            self.assertEqual(r.name, 'Updated Round')
            self.assertEqual(r.status, 'open')
            self.assertEqual(r.recurring_days, 7)

        # Test error case: no updates selected
        wizard2 = self.env['aps.award.vote.round.mass.update.wizard'].create({
            'vote_round_ids': [(6, 0, rounds.ids)],
        })
        with self.assertRaises(Exception):
            wizard2.action_update()