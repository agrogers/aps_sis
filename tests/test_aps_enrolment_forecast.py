from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestAPSEnrolmentForecast(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['aps.academic.year'].with_context(active_test=False).search([]).write({
            'active': False,
            'is_current': False,
        })
        cls.env['aps.level'].with_context(active_test=False).search([]).write({'active': False})
        cls.forecast = cls.env['aps.enrolment.forecast']
        cls.statuses = {
            code: cls.env['aps.student.enrolment.status'].search(
                [('code', '=', code)],
                limit=1,
            )
            for code in ('enrolled', 'accepted', 'waiting', 'inquiry', 'left', 'withdrawn')
        }
        cls.levels = {
            name: cls.env['aps.level'].create({
                'name': name,
                'sequence': sequence,
            })
            for name, sequence in (
                ('Forecast Foundation', 10),
                ('Forecast Year 1', 20),
                ('Forecast Year 2', 30),
                ('Forecast Year 3', 40),
                ('Forecast Year 11', 150),
            )
        }
        cls.reference_start = fields.Date.today().replace(month=6, day=1)
        if fields.Date.today().month < 6:
            cls.reference_start = cls.reference_start.replace(year=cls.reference_start.year - 1)
        cls.reference_end = cls.reference_start.replace(year=cls.reference_start.year + 1) - timedelta(days=1)
        cls.current_year = cls.env['aps.academic.year'].create({
            'name': f'Forecast Current {cls.reference_start.year}',
            'short_name': f'FY{cls.reference_start.year}-{str(cls.reference_end.year)[-2:]}',
            'start_date': cls.reference_start,
            'end_date': cls.reference_end,
            'is_current': True,
        })
        cls.next_year = cls.env['aps.academic.year'].create({
            'name': f'Forecast Next {cls.reference_start.year + 1}',
            'short_name': f'FY{cls.reference_start.year + 1}-{str(cls.reference_end.year + 1)[-2:]}',
            'start_date': cls.reference_start.replace(year=cls.reference_start.year + 1),
            'end_date': cls.reference_end.replace(year=cls.reference_end.year + 1),
        })

    def _create_student(self, name, level, status='enrolled', **values):
        partner = self.env['res.partner'].with_context(skip_student_sync=True).create({
            'name': name,
            'is_student': True,
        })
        student = self.env['aps.student'].create({
            'partner_id': partner.id,
            'level_id': level.id,
            'enrolment_status': self.statuses[status].id,
            **values,
        })
        self.student_ids.append(student.id)
        return student

    def setUp(self):
        super().setUp()
        self.student_ids = []

    def _get_data(self, basis='confirmed', years=3):
        forecast = self.forecast._compute_forecast(
            self.current_year.id,
            years,
            basis,
            student_ids=self.student_ids,
        )
        forecast['summary'] = {
            'current_students': forecast['now_total'],
            'next_year': forecast['period_totals'][0],
            'new_students': forecast['incoming_totals'][0],
            'expected_leavers': forecast['leaving_totals'][0],
            'net_change': forecast['period_totals'][0] - forecast['now_total'],
        }
        return forecast

    def _row(self, data, name):
        return next(row for row in data['rows'] if row['name'] == name)

    def test_current_students_progress_once_per_academic_year(self):
        self._create_student(
            'Forecast Current Student',
            self.levels['Forecast Year 1'],
            start_date='2020-01-01',
        )

        data = self._get_data()

        row = self._row(data, 'Forecast Year 1')
        self.assertEqual(row['now'], 1)
        self.assertEqual([cell['count'] for cell in row['cells']], [1, 0, 0])
        self.assertEqual(
            [cell['count'] for cell in self._row(data, 'Forecast Year 2')['cells']],
            [0, 1, 0],
        )
        action = self.forecast.action_open_students(
            self.current_year.id,
            3,
            'confirmed',
            0,
            False,
            'current',
        )
        details = self.env['aps.enrolment.forecast.detail'].browse(action['domain'][0][2])
        self.assertEqual(details.student_id.roll, False)
        self.assertEqual(details.forecast_level_id, self.levels['Forecast Year 1'])
        self.assertEqual(details.academic_year_name, self.current_year.short_name)

    def test_future_start_direct_entry_progression_and_movements(self):
        first_forecast_start = self.next_year.start_date
        self._create_student(
            'Forecast Future Entry',
            self.levels['Forecast Foundation'],
            status='accepted',
            entry_grade_id=self.levels['Forecast Year 2'].id,
            start_date=first_forecast_start,
        )

        data = self._get_data()

        year_two = self._row(data, 'Forecast Year 2')
        year_three = self._row(data, 'Forecast Year 3')
        self.assertEqual([cell['count'] for cell in year_two['cells']], [0, 1, 0])
        self.assertEqual([cell['incoming'] for cell in year_two['cells']], [0, 1, 0])
        self.assertEqual([cell['count'] for cell in year_three['cells']], [0, 0, 1])
        self.assertEqual(data['incoming_totals'], [0, 1, 0])
        self.assertEqual(data['summary']['new_students'], 0)

    def test_departures_are_counted_once_and_excluded_after_the_end_date(self):
        self._create_student(
            'Forecast Leaving Student',
            self.levels['Forecast Year 1'],
            start_date='2020-01-01',
            end_date=self.next_year.start_date.replace(day=15),
        )

        data = self._get_data()
        year_two = self._row(data, 'Forecast Year 2')
        self.assertEqual([cell['count'] for cell in year_two['cells']], [0, 1, 0])
        self.assertEqual([cell['leaving'] for cell in year_two['cells']], [0, 1, 0])
        self.assertEqual(data['leaving_totals'], [0, 1, 0])

    def test_missing_start_dates_waiting_and_terminal_grade(self):
        self._create_student(
            'Forecast Waiting Student',
            self.levels['Forecast Foundation'],
            status='waiting',
            entry_grade_id=self.levels['Forecast Year 1'].id,
        )
        self._create_student(
            'Forecast Year 11 Student',
            self.levels['Forecast Year 11'],
            start_date='2020-01-01',
        )
        self._create_student(
            'Forecast Left Student',
            self.levels['Forecast Year 1'],
            status='left',
        )

        confirmed = self._get_data()
        waiting = self._get_data(basis='waiting')

        self.assertEqual(self._row(confirmed, 'Forecast Year 1')['cells'][0]['count'], 0)
        self.assertEqual(self._row(waiting, 'Forecast Year 1')['cells'][0]['count'], 1)
        self.assertEqual(self._row(waiting, 'Forecast Year 1')['cells'][0]['incoming'], 1)
        self.assertEqual(self._row(waiting, 'Forecast Year 11')['cells'][0]['count'], 1)
        self.assertEqual(self._row(waiting, 'Forecast Year 11')['cells'][1]['count'], 0)
        self.assertEqual(self._row(waiting, 'Forecast Year 11')['cells'][0]['leaving'], 0)

    def test_future_start_and_end_overlap_one_academic_year(self):
        start_date = self.next_year.start_date.replace(month=10, day=1)
        end_date = self.next_year.end_date.replace(month=3, day=1)
        self._create_student(
            'Forecast Short Enrolment',
            self.levels['Forecast Foundation'],
            status='accepted',
            entry_grade_id=self.levels['Forecast Year 1'].id,
            start_date=start_date,
            end_date=end_date,
        )

        data = self._get_data()
        year_one = self._row(data, 'Forecast Year 1')
        self.assertEqual([cell['count'] for cell in year_one['cells']], [0, 1, 0])
        self.assertEqual([cell['incoming'] for cell in year_one['cells']], [0, 1, 0])
        self.assertEqual([cell['leaving'] for cell in year_one['cells']], [0, 1, 0])

    def test_not_yet_enrolled_student_with_stale_start_date_enters_first_year(self):
        self._create_student(
            'Forecast Accepted With Stale Start',
            self.levels['Forecast Foundation'],
            status='accepted',
            entry_grade_id=self.levels['Forecast Year 1'].id,
            start_date='2020-06-01',
        )

        data = self._get_data()
        year_one = self._row(data, 'Forecast Year 1')
        year_two = self._row(data, 'Forecast Year 2')

        self.assertEqual([cell['count'] for cell in year_one['cells']], [1, 0, 0])
        self.assertEqual([cell['incoming'] for cell in year_one['cells']], [1, 0, 0])
        self.assertEqual([cell['count'] for cell in year_two['cells']], [0, 1, 0])

    def test_virtual_periods_use_academic_year_boundaries_and_total_unique_students(self):
        self._create_student(
            'Forecast Enrolled Student',
            self.levels['Forecast Foundation'],
            start_date='2020-01-01',
        )
        self._create_student(
            'Forecast Future Student',
            self.levels['Forecast Foundation'],
            status='accepted',
            entry_grade_id=self.levels['Forecast Foundation'].id,
            start_date=self.next_year.start_date,
        )

        data = self._get_data(years=4)

        self.assertEqual(len(data['periods']), 4)
        self.assertEqual(data['periods'][2]['name'], f'{self.reference_start.year + 2}-{str(self.reference_start.year + 3)[-2:]}')
        self.assertEqual(data['period_totals'], [1, 2, 2, 2])
        self.assertEqual(data['now_total'], 1)

    def test_all_expected_basis_totals_and_incoming_student_drilldown(self):
        accepted_student = self._create_student(
            'Forecast Accepted Without Date',
            self.levels['Forecast Foundation'],
            status='accepted',
            entry_grade_id=self.levels['Forecast Foundation'].id,
        )
        self._create_student(
            'Forecast Waiting Without Date',
            self.levels['Forecast Year 1'],
            status='waiting',
            entry_grade_id=self.levels['Forecast Year 1'].id,
        )
        inquiry_student = self._create_student(
            'Forecast Inquiry With Date',
            self.levels['Forecast Year 2'],
            status='inquiry',
            entry_grade_id=self.levels['Forecast Year 2'].id,
            start_date=self.next_year.start_date,
        )
        self._create_student(
            'Forecast Withdrawn Student',
            self.levels['Forecast Foundation'],
            status='withdrawn',
        )
        self._create_student(
            'Forecast Left Student',
            self.levels['Forecast Foundation'],
            status='left',
        )

        data = self._get_data(basis='all_expected')
        year_index = 1
        action = self.forecast.action_open_students(
            self.current_year.id,
            3,
            'all_expected',
            year_index,
            False,
            'incoming',
        )

        self.assertEqual(data['period_totals'], [2, 3, 3])
        self.assertEqual(data['incoming_totals'], [2, 1, 0])
        self.assertEqual(action['res_model'], 'aps.enrolment.forecast.detail')
        detail_ids = action['domain'][0][2]
        details = self.env['aps.enrolment.forecast.detail'].browse(detail_ids)
        self.assertEqual(len(details), 1)
        self.assertEqual(details.student_id, inquiry_student)
        self.assertEqual(details.forecast_level_id, self.levels['Forecast Year 2'])