from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAPSTimeTracking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.TimeTracking = cls.env['aps.time.tracking']
        cls.partner = cls.env.user.partner_id
        cls.subject = cls.env['aps.subject'].create({
            'name': 'Timer Test Subject',
        })
        cls.other_subject = cls.env['aps.subject'].create({
            'name': 'Timer Other Subject',
        })

    def _vals(self, start, stop, subject=None, partner=None):
        return {
            'partner_id': (partner or self.partner).id,
            'subject_id': (subject or self.subject).id,
            'start_time': start,
            'stop_time': stop,
        }

    def test_adjacent_entries_are_allowed(self):
        first = self.TimeTracking.create(self._vals(
            '2026-09-11 08:00:00', '2026-09-11 09:00:00'
        ))
        second = self.TimeTracking.create(self._vals(
            '2026-09-11 09:00:00', '2026-09-11 10:00:00',
            subject=self.other_subject,
        ))
        self.assertTrue(first and second)

    def test_overlapping_create_is_rejected(self):
        self.TimeTracking.create(self._vals(
            '2026-09-11 10:00:00', '2026-09-11 11:00:00'
        ))
        with self.assertRaises(ValidationError):
            self.TimeTracking.create(self._vals(
                '2026-09-11 10:30:00', '2026-09-11 11:30:00',
                subject=self.other_subject,
            ))

    def test_overlapping_write_is_rejected_but_self_edit_is_allowed(self):
        entry = self.TimeTracking.create(self._vals(
            '2026-09-11 12:00:00', '2026-09-11 13:00:00'
        ))
        entry.write({'notes': 'Self edit'})
        with self.assertRaises(ValidationError):
            entry.write({'start_time': '2026-09-11 11:30:00'})

    def test_interval_validation_returns_conflict_details(self):
        entry = self.TimeTracking.create(self._vals(
            '2026-09-11 14:00:00', '2026-09-11 15:00:00'
        ))
        result = self.TimeTracking.validate_timer_interval(
            self.partner.id,
            '2026-09-11 14:30:00',
            '2026-09-11 15:30:00',
        )
        self.assertFalse(result['valid'])
        self.assertEqual(result['conflicts'][0]['id'], entry.id)
        self.assertEqual(result['conflicts'][0]['subject_name'], self.subject.name)

    def test_timeline_returns_local_partner_entries(self):
        entry = self.TimeTracking.create(self._vals(
            '2026-09-11 16:00:00', '2026-09-11 17:00:00'
        ))
        timeline = self.TimeTracking.get_timer_timeline(
            '2026-09-11', self.partner.id
        )
        entry_ids = [item['id'] for item in timeline['entries']]
        self.assertIn(entry.id, entry_ids)
        payload = next(item for item in timeline['entries'] if item['id'] == entry.id)
        self.assertEqual(payload['subject_name'], self.subject.name)
        self.assertTrue(payload['color'])
