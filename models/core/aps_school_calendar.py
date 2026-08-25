from odoo import api, fields, models


class ApsSchoolCalendar(models.Model):
    _name = 'aps.school.calendar'
    _description = 'School Calendar'
    _rec_name = 'description'
    _order = 'date, date_type, id'

    DATE_TYPE = [
        ('school_day', 'School Day'),
        ('event', 'Event'),
        ('public_holiday', 'Public Holiday'),
        ('school_holiday', 'School Holiday'),
        ('student_free', 'Student Free Day'),
        ('weekend', 'Weekend'),
    ]

    date = fields.Date(string='Date', required=True, index=True)
    date_display = fields.Char(
        string='Day',
        compute='_compute_date_display',
    )
    date_type = fields.Selection(
        DATE_TYPE,
        string='Type',
        required=True,
    )
    repeating = fields.Boolean(
        string='Repeats Annually',
        default=False,
        help='If set, this entry will be automatically re-created when generating the calendar for the following year.',
    )
    description = fields.Char(string='Description')
    notes = fields.Text(string='Notes')
    applies_to_level_ids = fields.Many2many(
        'aps.level',
        string='Applies to Levels',
        relation='aps_school_calendar_level_rel',
        column1='calendar_id',
        column2='level_id',
        help='Leave blank to apply to all levels.',
    )

    # Calendar colour index per date_type
    # Odoo palette: 0=grey, 1=red, 2=orange, 3=yellow, 4=teal, 5=purple,
    #               6=salmon, 7=blue, 8=pink, 10=green, 11=dark-blue
    _DATE_TYPE_COLOR = {
        'school_day':    10,   # green
        'event':          7,   # blue
        'public_holiday': 3,   # yellow
        'school_holiday': 2,   # orange
        'student_free':   6,   # salmon
        'weekend':        0,   # grey
    }

    color = fields.Integer(
        string='Color',
        compute='_compute_color',
        store=True,
    )

    @api.depends('date_type')
    def _compute_color(self):
        for rec in self:
            rec.color = self._DATE_TYPE_COLOR.get(rec.date_type, 0)

    @api.depends('date')
    def _compute_date_display(self):
        for rec in self:
            if rec.date:
                date_value = fields.Date.to_date(rec.date)
                rec.date_display = (
                    f'{date_value.strftime("%A")} '
                    f'{date_value.day} {date_value.strftime("%B")} {date_value.strftime("%Y")}'
                )
            else:
                rec.date_display = False

    # Computed: which academic week does this date fall in?
    week_id = fields.Many2one(
        'aps.academic.week',
        string='Academic Week',
        compute='_compute_week_id',
        store=True,
    )

    @api.depends('date')
    def _compute_week_id(self):
        Week = self.env['aps.academic.week']
        for rec in self:
            if rec.date:
                week = Week.search([
                    ('date_start', '<=', rec.date),
                    ('date_stop', '>=', rec.date),
                ], limit=1)
                rec.week_id = week
            else:
                rec.week_id = False

    @api.depends('date', 'description', 'week_id.short_name', 'week_id.academic_term_id.short_name')
    def _compute_display_name(self):
        for rec in self:
            term_code = rec.week_id.academic_term_id.short_name if rec.week_id and rec.week_id.academic_term_id else None
            week_code = rec.week_id.short_name if rec.week_id else None
            if term_code and week_code:
                rec.display_name = f'{term_code}-{week_code}'
            elif week_code:
                rec.display_name = week_code
            elif rec.date:
                rec.display_name = rec.date.strftime('%d %b')
            else:
                rec.display_name = '(no date)'
            if rec.description:
                rec.display_name = f'{rec.display_name} ({rec.description})'

    @api.model
    def get_calendar_report_data(self, year_start, year_end):
        """Build per-month calendar data for the printable academic calendar.

        Returns a list of month dicts (chronological) each containing:
          - label: e.g. 'Aug-26'
          - weeks: list of week rows; each row is a list of cell dicts
            ({'day': int|None, 'color': hex str}) Monday-first, 5 columns
            plus an optional trailing Saturday cell when a school day falls
            on that Saturday.
          - events: grouped event list entries {'dates': '13,21,28', 'title': ...}
        """
        import calendar as cal_mod
        from datetime import date, timedelta

        year_start = fields.Date.to_date(year_start)
        year_end = fields.Date.to_date(year_end)

        Color = self._DATE_TYPE_COLOR
        HEX = {
            0: '#FFFFFF',   # grey/normal -> white for print
            2: '#FFB74D',   # orange
            3: '#FFF176',   # yellow
            6: '#FF8A80',   # salmon
            7: '#90CAF9',   # blue
            10: '#A5D6A7',  # green
        }

        def default_hex(date_type):
            return HEX.get(Color.get(date_type, 0), '#FFFFFF')

        # Fetch all calendar entries in range.
        # by_date: one entry per date (first found) — used for grid colouring.
        # all_events: every described/typed entry — used for the event list.
        records = self.search([
            ('date', '>=', year_start),
            ('date', '<=', year_end),
        ])
        by_date = {}
        all_events = []
        for rec in records:
            # Skip pure weekend noise from the printed grid
            if rec.date_type == 'weekend':
                continue
            if rec.date not in by_date:
                by_date[rec.date] = {
                    'date_type': rec.date_type,
                    'description': rec.description or '',
                }
            all_events.append({
                'date': rec.date,
                'date_type': rec.date_type,
                'description': rec.description or '',
            })

        months = []
        d = year_start
        while (d.year, d.month) <= (year_end.year, year_end.month):
            label = d.strftime('%b-%y')
            cal = cal_mod.Calendar(firstweekday=0)  # Monday first
            weeks = []
            events_by_key = {}

            for week in cal.monthdatescalendar(d.year, d.month):
                row = [None] * 5
                saturday_cell = None
                for day in week:
                    in_month = day.month == d.month
                    info = by_date.get(day)
                    if day.weekday() < 5:
                        cell = {
                            'day': day.day if in_month else None,
                            'color': default_hex(info['date_type']) if info and in_month else '#FFFFFF',
                        }
                        row[day.weekday()] = cell
                    elif day.weekday() == 5:
                        # Saturday: only shown when a school day is forced onto it
                        if info and info['date_type'] == 'school_day':
                            saturday_cell = {
                                'day': day.day,
                                'color': default_hex(info['date_type']),
                            }
                    # Sunday never rendered

                # Row may be entirely blank leading/trailing cells — keep for grid shape
                weeks.append({'days': row, 'saturday': saturday_cell})

            # Drop fully blank rows (e.g. month starting on Sunday, or trailing
            # week whose only in-month days fall on the hidden weekend)
            weeks = [
                w for w in weeks
                if any(c and c['day'] for c in w['days']) or w['saturday']
            ]

            # Group events for this month (ALL events, not just the grid winner)
            TYPE_LABELS = dict(self.DATE_TYPE)
            month_events = [e for e in all_events
                            if e['date'].year == d.year and e['date'].month == d.month
                            and (e['description'] or e['date_type'] != 'school_day')]
            for e in sorted(month_events, key=lambda x: x['date']):
                # Use description; fall back to the type label (e.g. 'Public Holiday')
                desc = e['description'] or TYPE_LABELS.get(e['date_type'], '')
                key = (desc, e['date_type'])
                events_by_key.setdefault(key, []).append(e['date'])

            events = []
            for (desc, date_type), dates in sorted(
                    events_by_key.items(), key=lambda kv: kv[1][0]):
                # Merge consecutive runs into ranges, comma-separate the rest
                parts = []
                run_start = prev = dates[0]
                for cur in dates[1:] + [None]:
                    if cur is not None and (cur - prev).days == 1:
                        prev = cur
                        continue
                    if run_start == prev:
                        parts.append(str(run_start.day))
                    elif (prev - run_start).days <= 2 and run_start.weekday() > 3:
                        # short runs over a weekend: list days
                        parts.append(','.join(str(x.day) for x in
                                              [run_start + timedelta(days=i)
                                               for i in range((prev - run_start).days + 1)]))
                    else:
                        parts.append(f'{run_start.day}\u2013{prev.day}')
                    if cur is not None:
                        run_start = prev = cur
                events.append({
                    'dates': ','.join(parts),
                    'title': desc,
                    'color': default_hex(date_type),
                })

            months.append({
                'label': label,
                'weeks': weeks,
                'events': events,
            })
            # advance to first of next month
            d = date(d.year + (d.month // 12), (d.month % 12) + 1, 1)

        return months

