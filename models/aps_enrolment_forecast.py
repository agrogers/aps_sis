from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class APSEnrolmentForecast(models.TransientModel):
    _name = 'aps.enrolment.forecast'
    _description = 'Enrolment Forecast'
    _transient_max_hours = 1

    YEAR_CHOICES = (3, 4, 5, 6, 7, 10)
    BASIS_CODES = {
        'confirmed': ('enrolled', 'accepted'),
        'waiting': ('enrolled', 'accepted', 'waiting'),
        'all_expected': ('enrolled', 'accepted', 'waiting', 'inquiry'),
    }

    @api.model
    def _check_forecast_access(self):
        if not self.env.su and not self.env.user.has_group('aps_sis.group_aps_manager'):
            raise AccessError('Only school managers can view enrolment forecasts.')

    @api.model
    def _academic_years(self):
        years = self.env['aps.academic.year'].search(
            [('active', '=', True)],
            order='start_date, id',
        )
        if not years:
            raise UserError('Create an active academic year before opening the enrolment forecast.')
        return years

    @api.model
    def _reference_year_index(self, years, today):
        current = years.filtered('is_current')[:1]
        if not current:
            current = years.filtered(
                lambda year: year.start_date <= today <= year.end_date
            )[:1]
        if not current:
            current = years.filtered(lambda year: year.start_date >= today)[:1]
        if not current:
            current = years[-1:]
        return years.ids.index(current.id)

    @api.model
    def get_options(self):
        self._check_forecast_access()
        years = self._academic_years()
        today = fields.Date.today()
        reference_index = self._reference_year_index(years, today)
        available_years = years[reference_index:]
        return {
            'academic_years': [
                {
                    'id': year.id,
                    'name': year.short_name or year.name,
                }
                for year in available_years
            ],
            'default_year_id': years[reference_index].id,
            'year_choices': list(self.YEAR_CHOICES),
            'basis_choices': [
                {'value': 'confirmed', 'label': 'Confirmed only'},
                {'value': 'waiting', 'label': 'Confirmed + Waiting'},
                {'value': 'all_expected', 'label': 'All expected'},
            ],
        }

    @api.model
    def _make_period(self, year, offset, is_virtual=False):
        start_date = year.start_date
        end_date = year.end_date
        if is_virtual:
            name = f'{start_date.year}-{end_date.year % 100:02d}'
        else:
            name = year.short_name or year.name
        return {
            'year_id': year.id if not is_virtual else False,
            'name': name,
            'start_date': start_date,
            'end_date': end_date,
            'offset': offset,
        }

    @api.model
    def _make_periods(self, years, start_year, number_of_years, reference_index):
        start_index = years.ids.index(start_year.id)
        periods = [
            self._make_period(year, index - reference_index)
            for index, year in enumerate(years[start_index:], start=start_index)
        ][:number_of_years]
        while len(periods) < number_of_years:
            previous = periods[-1]
            start_date = previous['start_date'] + relativedelta(years=1)
            end_date = previous['end_date'] + relativedelta(years=1)
            virtual_year = type('VirtualAcademicYear', (), {
                'start_date': start_date,
                'end_date': end_date,
            })()
            periods.append(self._make_period(
                virtual_year,
                periods[-1]['offset'] + 1,
                is_virtual=True,
            ))
        return periods

    @api.model
    def _validate_options(self, number_of_years, basis):
        try:
            number_of_years = int(number_of_years)
        except (TypeError, ValueError):
            raise ValidationError('Choose a supported number of forecast years.')
        if number_of_years not in self.YEAR_CHOICES:
            raise ValidationError('Choose a supported number of forecast years.')
        if basis not in self.BASIS_CODES:
            raise ValidationError('Choose a supported forecast basis.')
        return number_of_years

    @api.model
    def _offset_for_start_date(self, start_date, years, periods, reference_index):
        for index, year in enumerate(years):
            if start_date <= year.end_date:
                return index - reference_index
        for period in periods:
            if start_date <= period['end_date']:
                return period['offset']
        return None

    @api.model
    def _compute_forecast(self, start_year_id, number_of_years, basis, student_ids=None):
        number_of_years = self._validate_options(number_of_years, basis)
        years = self._academic_years()
        start_year = years.browse(int(start_year_id)).exists()
        if not start_year or start_year not in years:
            raise ValidationError('Choose an active academic year.')

        today = fields.Date.today()
        reference_index = self._reference_year_index(years, today)
        periods = self._make_periods(
            years,
            start_year,
            number_of_years,
            reference_index,
        )
        levels = self.env['aps.level'].search([], order='sequence, name, id')
        level_indexes = {level.id: index for index, level in enumerate(levels)}
        terminal_level_index = len(levels) - 1
        included_codes = self.BASIS_CODES[basis]
        student_domain = [
            ('active', '=', True),
            ('enrolment_status.code', 'in', included_codes),
        ]
        if student_ids is not None:
            student_domain.append(('id', 'in', student_ids))
        students = self.env['aps.student'].search(student_domain)
        student_codes = {student.id: student.enrolment_status.code for student in students}
        actual_students = {}
        for student in students:
            if (
                student_codes[student.id] == 'enrolled'
                and (not student.start_date or student.start_date <= today)
                and (not student.end_date or student.end_date >= today)
                and student.level_id
            ):
                actual_students.setdefault(student.level_id.id, set()).add(student.id)

        projected_by_cell = {}
        incoming_by_cell = {}
        leaving_by_cell = {}
        for period_index, period in enumerate(periods):
            for level in levels:
                cell_key = (period_index, level.id)
                projected_by_cell[cell_key] = set()
                incoming_by_cell[cell_key] = set()
                leaving_by_cell[cell_key] = set()

        for student in students:
            code = student_codes[student.id]
            is_current_enrolment = (
                code == 'enrolled'
                and (not student.start_date or student.start_date <= today)
                and (not student.end_date or student.end_date >= today)
            )
            is_future_start = bool(student.start_date and student.start_date > today)
            base_level = (
                student.level_id if is_current_enrolment and not is_future_start
                else student.entry_grade_id or student.level_id
            )
            if not base_level or base_level.id not in level_indexes:
                continue

            if is_current_enrolment and not is_future_start:
                entry_offset = 0
            elif student.start_date and student.start_date > today:
                entry_offset = self._offset_for_start_date(
                    student.start_date,
                    years,
                    periods,
                    reference_index,
                )
                if entry_offset is None:
                    continue
            else:
                entry_offset = periods[0]['offset']

            base_level_index = level_indexes[base_level.id]
            for period_index, period in enumerate(periods):
                if period['offset'] < entry_offset:
                    continue
                if student.end_date and student.end_date < period['start_date']:
                    continue
                forecast_level_index = (
                    base_level_index + period['offset'] - entry_offset
                )
                if forecast_level_index > terminal_level_index:
                    continue
                forecast_level = levels[forecast_level_index]
                cell_key = (period_index, forecast_level.id)
                projected_by_cell[cell_key].add(student.id)

                has_actual_start = bool(
                    student.start_date
                    and period['start_date'] <= student.start_date <= period['end_date']
                )
                assumed_start = bool(
                    code != 'enrolled'
                    and period_index == 0
                    and (not student.start_date or student.start_date <= today)
                )
                if has_actual_start or assumed_start:
                    incoming_by_cell[cell_key].add(student.id)

                leaves_during_period = bool(
                    student.end_date
                    and period['start_date'] <= student.end_date <= period['end_date']
                )
                if leaves_during_period and forecast_level_index < terminal_level_index:
                    leaving_by_cell[cell_key].add(student.id)

        rows = []
        for level in levels:
            cells = []
            for period_index, period in enumerate(periods):
                cell_key = (period_index, level.id)
                cells.append({
                    'index': period_index,
                    'year_name': period['name'],
                    'count': len(projected_by_cell[cell_key]),
                    'incoming': len(incoming_by_cell[cell_key]),
                    'leaving': len(leaving_by_cell[cell_key]),
                })
            rows.append({
                'level_id': level.id,
                'name': level.short_name or level.name,
                'now': len(actual_students.get(level.id, set())),
                'cells': cells,
            })

        current_total = sum(len(student_ids) for student_ids in actual_students.values())
        period_totals = [
            sum(
                len(projected_by_cell[(period_index, level.id)])
                for level in levels
            )
            for period_index in range(len(periods))
        ]
        incoming_totals = [
            sum(
                len(incoming_by_cell[(period_index, level.id)])
                for level in levels
            )
            for period_index in range(len(periods))
        ]
        leaving_totals = [
            sum(
                len(leaving_by_cell[(period_index, level.id)])
                for level in levels
            )
            for period_index in range(len(periods))
        ]
        return {
            'periods': periods,
            'current_year_name': years[reference_index].short_name or years[reference_index].name,
            'rows': rows,
            'now_total': current_total,
            'period_totals': period_totals,
            'incoming_totals': incoming_totals,
            'leaving_totals': leaving_totals,
            'projected_by_cell': projected_by_cell,
            'incoming_by_cell': incoming_by_cell,
            'leaving_by_cell': leaving_by_cell,
            'actual_students': actual_students,
            'level_ids': levels.ids,
        }

    @api.model
    def get_forecast_data(self, start_year_id, number_of_years=5, basis='confirmed'):
        self._check_forecast_access()
        forecast = self._compute_forecast(start_year_id, number_of_years, basis)
        first_total = forecast['period_totals'][0]
        return {
            'rows': forecast['rows'],
            'periods': [
                {'index': index, 'name': period['name']}
                for index, period in enumerate(forecast['periods'])
            ],
            'now_total': forecast['now_total'],
            'period_totals': forecast['period_totals'],
            'incoming_totals': forecast['incoming_totals'],
            'leaving_totals': forecast['leaving_totals'],
            'summary': {
                'current_students': forecast['now_total'],
                'next_year': first_total,
                'new_students': forecast['incoming_totals'][0],
                'expected_leavers': forecast['leaving_totals'][0],
                'net_change': first_total - forecast['now_total'],
            },
        }

    @api.model
    def action_open_students(
        self,
        start_year_id,
        number_of_years,
        basis,
        year_index,
        level_id,
        movement='projected',
    ):
        self._check_forecast_access()
        forecast = self._compute_forecast(start_year_id, number_of_years, basis)
        try:
            year_index = int(year_index)
            level_id = int(level_id)
        except (TypeError, ValueError):
            raise ValidationError('Choose a valid forecast cell.')
        if year_index < 0 or year_index >= len(forecast['periods']):
            raise ValidationError('Choose a valid forecast year.')
        if level_id and level_id not in forecast['level_ids']:
            raise ValidationError('Choose a valid grade.')
        student_sets = {
            'projected': forecast['projected_by_cell'],
            'incoming': forecast['incoming_by_cell'],
            'leaving': forecast['leaving_by_cell'],
        }
        if movement not in (*student_sets, 'current'):
            raise ValidationError('Choose a valid movement type.')
        if movement == 'current':
            students_by_level = forecast['actual_students']
        else:
            students_by_level = {
                level: student_sets[movement].get((year_index, level), set())
                for level in forecast['level_ids']
            }
        if level_id:
            students_by_level = {level_id: students_by_level.get(level_id, set())}
        forecast_level_by_student = {
            student_id: level
            for level, student_ids in students_by_level.items()
            for student_id in student_ids
        }
        student_ids = sorted(forecast_level_by_student)
        if not student_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No students',
                    'message': 'There are no students in this selection.',
                    'type': 'info',
                },
            }

        period = forecast['periods'][year_index]
        period_name = (
            forecast['current_year_name'] if movement == 'current' else period['name']
        )
        Student = self.env['aps.student']
        detail_values = []
        for student in Student.browse(student_ids):
            detail_values.append({
                'student_id': student.id,
                'roll': student.roll,
                'current_level_id': student.level_id.id,
                'forecast_level_id': forecast_level_by_student[student.id],
                'academic_year_name': period_name,
                'start_date': student.start_date,
                'end_date': student.end_date,
                'enrolment_status_id': student.enrolment_status.id,
                'movement': movement,
            })
        details = self.env['aps.enrolment.forecast.detail'].create(detail_values)
        titles = {
            'current': 'Current Students',
            'projected': 'Projected Students',
            'incoming': 'Incoming Students',
            'leaving': 'Expected Leavers',
        }
        list_view = self.env.ref('aps_sis.aps_enrolment_forecast_detail_list')
        level_name = (
            self.env['aps.level'].browse(level_id).display_name if level_id else 'All Grades'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': f'{titles[movement]}: {period_name} / {level_name}',
            'res_model': 'aps.enrolment.forecast.detail',
            'views': [[list_view.id, 'list']],
            'domain': [('id', 'in', details.ids)],
            'context': {'create': False, 'delete': False},
            'target': 'current',
        }


class APSEnrolmentForecastDetail(models.TransientModel):
    _name = 'aps.enrolment.forecast.detail'
    _description = 'Enrolment Forecast Student Detail'
    _order = 'student_id'
    _rec_name = 'student_id'
    _transient_max_hours = 1

    student_id = fields.Many2one('aps.student', string='Student', readonly=True)
    roll = fields.Char(string='Student Number', readonly=True)
    current_level_id = fields.Many2one('aps.level', string='Current Grade', readonly=True)
    forecast_level_id = fields.Many2one('aps.level', string='Forecast Grade', readonly=True)
    academic_year_name = fields.Char(string='Academic Year', readonly=True)
    start_date = fields.Date(string='Start Date', readonly=True)
    end_date = fields.Date(string='End Date', readonly=True)
    enrolment_status_id = fields.Many2one(
        'aps.student.enrolment.status',
        string='Enrolment Status',
        readonly=True,
    )
    movement = fields.Selection(
        [
            ('current', 'Current'),
            ('projected', 'Projected'),
            ('incoming', 'Incoming'),
            ('leaving', 'Leaving'),
        ],
        readonly=True,
    )