import base64
from datetime import datetime

import pytz
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAPSTimeTracking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.TimeTracking = cls.env['aps.time.tracking']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Timer Test Student',
            'is_student': True,
        })
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

    def _create_calendar_day(self, date, code):
        date_type = self.env['aps.calendar.date.type'].search(
            [('code', '=', code)], limit=1
        )
        if not date_type:
            date_type = self.env['aps.calendar.date.type'].create({
                'code': code,
                'name': code.replace('_', ' ').title(),
            })
        self.env['aps.school.calendar'].create({
            'date': date,
            'date_type_id': date_type.id,
        })

    def _local_datetime_utc(self, date, hour, minute):
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        local_dt = user_tz.localize(datetime.fromisoformat(
            f'{date} {hour:02d}:{minute:02d}:00'
        ))
        return local_dt.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

    def test_timer_defaults_outside_school_hours_from_calendar_and_time(self):
        self._create_calendar_day('2099-09-21', 'school_day')
        self._create_calendar_day('2099-09-22', 'school_day')
        self._create_calendar_day('2099-09-23', 'school_day')
        self._create_calendar_day('2099-09-24', 'public_holiday')

        cases = [
            ('2099-09-21', 9, 0, False),
            ('2099-09-22', 8, 40, True),
            ('2099-09-23', 15, 25, True),
            ('2099-09-24', 9, 0, True),
        ]
        for date, hour, minute, expected in cases:
            start = self._local_datetime_utc(date, hour, minute)
            stop = self._local_datetime_utc(date, hour + 1, minute)
            entry = self.TimeTracking.create(self._vals(start, stop))
            self.assertEqual(entry.is_outside_school_hours, expected, date)

    def test_stale_outside_flag_does_not_mark_other_school_day_entries(self):
        self._create_calendar_day('2099-09-25', 'school_day')
        start = self._local_datetime_utc('2099-09-25', 7, 0)
        stop = self._local_datetime_utc('2099-09-25', 8, 0)
        self.TimeTracking.create({
            **self._vals(start, stop),
            'is_outside_school_hours': True,
        })

        start = self._local_datetime_utc('2099-09-25', 9, 0)
        stop = self._local_datetime_utc('2099-09-25', 10, 0)
        entry = self.TimeTracking.create(self._vals(start, stop))

        self.assertFalse(entry.is_outside_school_hours)

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

    def test_daily_flow_returns_seven_days_and_default_scale(self):
        self.TimeTracking.create(self._vals(
            '2026-09-07 08:00:00', '2026-09-07 09:30:00'
        ))
        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-09', 'monday', self.partner.id, False, 30, '30'
        )
        self.assertEqual(flow['range_start'], '2026-09-07')
        self.assertEqual(flow['range_end'], '2026-09-13')
        self.assertEqual(len(flow['days']), 7)
        self.assertEqual(flow['scale']['start'], '2026-09-07T08:00')
        self.assertEqual(flow['scale']['end'], '2026-09-07T16:00')
        self.assertEqual(flow['days'][0]['total_minutes'], 90.0)
        self.assertEqual(flow['days'][0]['subject_count'], 1)
        self.assertEqual(flow['days'][0]['submission_count'], 0)

    def test_daily_flow_home_hours_only_include_outside_school_entries(self):
        home_start = self._local_datetime_utc('2026-09-07', 9, 0)
        home_stop = self._local_datetime_utc('2026-09-07', 10, 30)
        regular_start = self._local_datetime_utc('2026-09-07', 10, 30)
        regular_stop = self._local_datetime_utc('2026-09-07', 11, 0)
        self.TimeTracking.create({
            **self._vals(home_start, home_stop),
            'is_outside_school_hours': True,
        })
        self.TimeTracking.create(self._vals(regular_start, regular_stop))

        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-09', 'monday', self.partner.id, False, 30, '30'
        )

        self.assertEqual(flow['days'][0]['total_minutes'], 120.0)
        self.assertEqual(flow['total_hours'], 2.0)
        self.assertEqual(flow['home_hours'], 1.5)

        home_flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-09', 'monday', self.partner.id, False, 30, '30', True
        )
        self.assertEqual(home_flow['days'][0]['total_minutes'], 90.0)
        self.assertEqual(home_flow['total_hours'], 2.0)
        self.assertEqual(home_flow['home_hours'], 1.5)
        self.assertEqual(len(home_flow['days'][0]['entries']), 1)
        self.assertTrue(home_flow['days'][0]['entries'][0]['is_outside_school_hours'])

    def test_daily_flow_groups_student_submissions_by_fifteen_minutes(self):
        student = self.env['res.partner'].create({
            'name': 'Daily Flow Student',
            'is_student': True,
        })
        resource = self.env['aps.resources'].create({
            'name': 'Daily Flow Submission Resource',
            'subjects': [(6, 0, [self.subject.id])],
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submissions = self.env['aps.resource.submission'].create([
            {
                'task_id': task.id,
                'submission_name': f'Submission {index}',
                'date_assigned': '2026-09-07',
            }
            for index in range(6)
        ])
        timestamps = []
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        for index, submission in enumerate(submissions):
            local_time = user_tz.localize(
                datetime(2026, 9, 7, 9, index * 2)
            )
            submitted_at = local_time.astimezone(pytz.utc).strftime(
                '%Y-%m-%d %H:%M:%S'
            )
            timestamps.append((submitted_at, submission.id))
            submission.write({'state': 'submitted'})
        excluded_tag = self.env['aps.resource.tags'].create({
            'name': 'Exclude from Daily Flow',
        })
        excluded_resource = self.env['aps.resources'].create({
            'name': 'Excluded Daily Flow Resource',
            'subjects': [(6, 0, [self.subject.id])],
            'tag_ids': [(6, 0, [excluded_tag.id])],
        })
        excluded_task = self.env['aps.resource.task'].create({
            'resource_id': excluded_resource.id,
            'student_id': student.id,
        })
        excluded_submission = self.env['aps.resource.submission'].create({
            'task_id': excluded_task.id,
            'submission_name': 'Excluded Submission',
            'state': 'submitted',
        })
        timestamps.append((
            timestamps[-1][0],
            excluded_submission.id,
        ))
        self.env.cr.executemany(
            'UPDATE aps_resource_submission SET time_submitted = %s WHERE id = %s',
            timestamps,
        )
        submissions.invalidate_recordset(['time_submitted'])

        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-09', 'monday', student.id, False, 30, '30'
        )

        day = flow['days'][0]
        self.assertEqual(day['submission_count'], 6)
        self.assertEqual(day['subject_count'], 0)
        self.assertEqual(len(day['submission_buckets']), 1)
        bucket = day['submission_buckets'][0]
        self.assertEqual(bucket['key'], '09:00')
        self.assertEqual(len(bucket['submissions']), 5)
        self.assertEqual(bucket['overflow_count'], 1)
        self.assertEqual(bucket['overflow_ids'], [submissions[5].id])
        self.assertEqual(bucket['submissions'][0]['subject_name'], self.subject.name)
        subject_summary = next(
            item for item in flow['subjects'] if item['id'] == self.subject.id
        )
        self.assertEqual(subject_summary['hours'], 0.0)
        self.assertEqual(
            bucket['submissions'][0]['color'],
            self.env['aps.subject'].get_subject_colors_map()[self.subject.id],
        )
        self.assertEqual(flow['scale']['start'], '2026-09-07T08:00')
        self.assertEqual(flow['scale']['end'], '2026-09-07T16:00')

    def test_daily_flow_last_seven_days_uses_selected_date_as_start(self):
        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-09', 'last_7_days', self.partner.id, False, 30, '30'
        )
        self.assertEqual(flow['range_start'], '2026-09-03')
        self.assertEqual(flow['range_end'], '2026-09-09')

    def test_daily_flow_expands_scale_for_outside_hours(self):
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        local_start = user_tz.localize(datetime(2026, 9, 7, 6, 30))
        local_stop = user_tz.localize(datetime(2026, 9, 7, 18, 15))
        self.TimeTracking.create(self._vals(
            local_start.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S'),
            local_stop.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S'),
        ))
        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-07', 'monday', self.partner.id, False, 30, '30'
        )
        self.assertEqual(flow['scale']['start'], '2026-09-07T06:30')
        self.assertEqual(flow['scale']['end'], '2026-09-07T18:15')

    def test_daily_flow_returns_subject_legend_and_entry_domain(self):
        entry = self.TimeTracking.create(self._vals(
            '2026-09-07 10:00:00', '2026-09-07 11:00:00'
        ))
        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-07', 'monday', self.partner.id, False, 30, '30'
        )
        payload = flow['days'][0]['entries'][0]
        self.assertEqual(payload['id'], entry.id)
        self.assertIn(('partner_id', '=', self.partner.id), payload['domain'])
        self.assertIn(('subject_id', '=', self.subject.id), payload['domain'])
        self.assertEqual(flow['subjects'][0]['id'], self.subject.id)

    def test_daily_flow_keeps_icon_for_subject_only_in_previous_week(self):
        self.subject.write({'icon': base64.b64encode(b'test-icon')})
        self.TimeTracking.create(self._vals(
            '2026-09-07 10:00:00', '2026-09-07 11:00:00'
        ))
        flow = self.TimeTracking.get_daily_flow_data(
            '2026-09-14', 'monday', self.partner.id, False, 30, '30'
        )

        subject = next(
            item for item in flow['subjects'] if item['id'] == self.subject.id
        )
        self.assertEqual(subject['minutes'], 0.0)
        self.assertEqual(
            subject['icon_url'],
            f'/web/image/aps.subject/{self.subject.id}/icon',
        )
