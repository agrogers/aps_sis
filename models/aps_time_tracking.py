from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime, time, timedelta


SCHOOL_START_HOUR = 8      # 08:00
SCHOOL_END_HOUR = 15       # 15:00
SCHOOL_END_MINUTE = 30     # 15:30


class APSTimeTracking(models.Model):
    _name = 'aps.time.tracking'
    _description = 'Time Tracking Entry'
    _order = 'start_time desc'

    display_name = fields.Char(compute='_compute_display_name')

    @api.depends('partner_id', 'subject_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.partner_id:
                parts.append(rec.partner_id.display_name)
            if rec.subject_id:
                parts.append(rec.subject_id.name)
            if rec.date:
                parts.append(str(rec.date))
            rec.display_name = ' - '.join(parts) if parts else f'Time Entry #{rec.id}'

    def _compute_is_current_user_teacher(self):
        teacher_group = self.env.ref('aps_sis.group_aps_teacher', raise_if_not_found=False)
        is_teacher = teacher_group and teacher_group in self.env.user.groups_id
        for rec in self:
            rec.is_current_user_teacher = is_teacher

    partner_id = fields.Many2one(
        'res.partner',
        string='Person',
        domain=[('is_student', '=', True)],
        default=lambda self: self.env.user.partner_id.id,
        index=True,
    )
    is_current_user_teacher = fields.Boolean(
        compute='_compute_is_current_user_teacher',
    )
    subject_id = fields.Many2one(
        'op.subject',
        string='Subject',
        index=True,
        required=True,
    )

    date = fields.Date(
        string='Date',
        compute='_compute_date',
        store=True,
        readonly=False,
        default=fields.Date.context_today,
        index=True,
    )
    start_time = fields.Datetime(string='Start Time')
    stop_time = fields.Datetime(string='Stop Time')
    pause_minutes = fields.Float(string='Pause (minutes)', default=0.0)

    total_minutes = fields.Float(
        string='Total Minutes',
        compute='_compute_total_minutes',
        store=True,
        readonly=False,
    )

    # ── Meta ──────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')
    is_outside_school_hours = fields.Boolean(
        string='Outside School Hours',
        compute='_compute_is_outside_school_hours',
        store=True,
        readonly=False,
        help=(
            'Automatically set when the entry starts before 08:00, '
            'after 15:30, or on a weekend.  You can override this manually. '
            'If a weekday entry is manually set to outside school hours it '
            'is treated as a holiday and subsequent entries on that day will '
            'also default to outside school hours.'
        ),
    )

    # ── Computed fields ───────────────────────────────────────────────────────
    subject_icon = fields.Image(
        related='subject_id.icon',
        string='Subject Icon',
        readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Compute helpers
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('start_time')
    def _compute_date(self):
        for rec in self:
            if rec.start_time:
                # start_time is stored as UTC in Odoo; convert to local date using
                # the company's timezone if available, otherwise use UTC date.
                rec.date = fields.Date.context_today(rec, rec.start_time)
            else:
                rec.date = False

    @api.depends('start_time', 'stop_time', 'pause_minutes')
    def _compute_total_minutes(self):
        for rec in self:
            if rec.start_time and rec.stop_time and rec.stop_time > rec.start_time:
                delta = rec.stop_time - rec.start_time
                rec.total_minutes = max(0.0, (delta.total_seconds() / 60.0) - (rec.pause_minutes or 0.0))
            else:
                rec.total_minutes = 0.0

    @api.onchange('total_minutes', 'pause_minutes')
    def _onchange_total_minutes(self):
        """When total_minutes or pause changes, fill the missing time field."""
        if self.total_minutes > 0:
            offset = timedelta(minutes=self.total_minutes + (self.pause_minutes or 0.0))
            if self.stop_time and not self.start_time:
                self.start_time = self.stop_time - offset
            elif self.start_time and not self.stop_time:
                self.stop_time = self.start_time + offset
            elif self.stop_time:
                # Both exist — anchor on stop_time
                self.start_time = self.stop_time - offset

    @api.onchange('start_time')
    def _onchange_start_time(self):
        """When start_time is set/changed, fill stop_time if total_minutes exists but stop doesn't."""
        if self.start_time and self.total_minutes > 0 and not self.stop_time:
            offset = timedelta(minutes=self.total_minutes + (self.pause_minutes or 0.0))
            self.stop_time = self.start_time + offset

    @api.onchange('stop_time')
    def _onchange_stop_time(self):
        """When stop_time is set/changed, fill start_time if total_minutes exists but start doesn't."""
        if self.stop_time and self.total_minutes > 0 and not self.start_time:
            offset = timedelta(minutes=self.total_minutes + (self.pause_minutes or 0.0))
            self.start_time = self.stop_time - offset

    @api.constrains('start_time', 'stop_time')
    def _check_duration_limit(self):
        for rec in self:
            if rec.start_time and rec.stop_time:
                if rec.stop_time < rec.start_time:
                    raise ValidationError("Stop time cannot be before start time.")
                if (rec.stop_time - rec.start_time) > timedelta(hours=24):
                    raise ValidationError("Start and stop time cannot be more than 24 hours apart.")

    @api.depends('start_time', 'is_outside_school_hours')
    def _compute_is_outside_school_hours(self):
        """
        Auto-detect outside-school-hours based on start_time (converted to the
        user's local timezone).
        Weekends are always outside school hours.
        Before SCHOOL_START_HOUR or after SCHOOL_END_HOUR:SCHOOL_END_MINUTE
        on weekdays is outside school hours.
        If a weekday entry already exists for the same date that was manually
        marked as outside_school_hours, treat the whole day as a holiday.
        """
        import pytz

        for rec in self:
            if not rec.start_time:
                rec.is_outside_school_hours = False
                continue

            # Convert UTC start_time to user's local time
            user_tz = pytz.timezone(rec.env.user.tz or 'UTC')
            local_dt = rec.start_time.replace(tzinfo=pytz.utc).astimezone(user_tz)
            local_date = local_dt.date()
            weekday = local_date.weekday()  # 0=Mon … 6=Sun

            # Weekends → always outside
            if weekday >= 5:
                rec.is_outside_school_hours = True
                continue

            # Check if another entry for the same date is marked as holiday
            # (weekday + outside school hours = treat as holiday)
            domain = [
                ('date', '=', local_date),
                ('is_outside_school_hours', '=', True),
            ]
            if rec.id:
                domain.append(('id', '!=', rec.id))
            if self.search_count(domain):
                rec.is_outside_school_hours = True
                continue

            # Check local start hour/minute (already converted to user tz)
            local_hour = local_dt.hour
            local_minute = local_dt.minute
            before_school = (local_hour < SCHOOL_START_HOUR)
            after_school = (
                local_hour > SCHOOL_END_HOUR or
                (local_hour == SCHOOL_END_HOUR and local_minute >= SCHOOL_END_MINUTE)
            )
            rec.is_outside_school_hours = before_school or after_school

    # ─────────────────────────────────────────────────────────────────────────
    # API methods for the frontend timer
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def get_timer_dialog_defaults(self):
        """Return current user's partner and their available subjects."""
        partner = self.env.user.partner_id
        student = self.env['op.student'].search([('user_id', '=', self.env.uid)], limit=1)
        subjects = []
        if student:
            course_details = self.env['op.student.course'].search([
                ('student_id', '=', student.id),
                ('state', '=', 'running'),
            ])
            subject_records = course_details.mapped('subject_ids')
            subjects = [{'id': s.id, 'name': s.name} for s in subject_records.sorted('name')]
        if not subjects:
            all_subjects = self.env['op.subject'].search([], order='name asc')
            subjects = [{'id': s.id, 'name': s.name} for s in all_subjects]
        return {
            'partner_id': partner.id,
            'partner_name': partner.display_name,
            'subjects': subjects,
        }

    @api.model
    def start_timer(self, partner_id=None, subject_id=None):
        """Create a new in-progress timer entry and return its id."""
        vals = {
            'start_time': fields.Datetime.now(),
            'partner_id': partner_id,
            'subject_id': subject_id,
        }
        record = self.create(vals)
        return record.id

    @api.model
    def stop_timer(self, entry_id):
        """Set the stop_time on an existing timer entry and return summary data."""
        entry = self.browse(entry_id)
        if entry.exists() and not entry.stop_time:
            entry.write({'stop_time': fields.Datetime.now()})
        return self._entry_summary(entry)

    def _entry_summary(self, entry):
        """Return a dict describing a timer entry for the frontend dialog."""
        import pytz
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        def to_local_str(dt):
            if not dt:
                return False
            return dt.replace(tzinfo=pytz.utc).astimezone(user_tz).strftime('%Y-%m-%d %H:%M:%S')

        return {
            'id': entry.id,
            'partner_id': [entry.partner_id.id, entry.partner_id.display_name] if entry.partner_id else False,
            'subject_id': [entry.subject_id.id, entry.subject_id.name] if entry.subject_id else False,
            'date': str(entry.date) if entry.date else False,
            'start_time': to_local_str(entry.start_time),
            'stop_time': to_local_str(entry.stop_time),
            'pause_minutes': entry.pause_minutes,
            'total_minutes': entry.total_minutes,
            'notes': entry.notes or '',
            'is_outside_school_hours': entry.is_outside_school_hours,
            'tz': self.env.user.tz or 'UTC',
        }

    @api.model
    def get_dashboard_data(self, days=14):
        """
        Return aggregated data for the time-tracking dashboard.

        Returns:
            dict with keys:
                weekly_comparison  – list [{label, this_week, last_week}] per subject
                subject_doughnut   – {labels, data}
                history_bar        – {labels, datasets}  (stacked bar by subject)
        """
        import pytz
        from datetime import timedelta

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        now_local = datetime.now(tz)
        today = now_local.date()

        # Week boundaries (Monday = 0)
        this_week_start = today - timedelta(days=today.weekday())
        this_week_end = today
        last_week_start = this_week_start - timedelta(weeks=1)
        last_week_end = this_week_start - timedelta(days=1)

        # ── Weekly comparison by subject ──────────────────────────────────────
        def _sum_by_subject(date_from, date_to):
            recs = self.search([
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ])
            totals = {}
            for r in recs:
                subj = r.subject_id.name if r.subject_id else 'Unknown'
                totals[subj] = totals.get(subj, 0.0) + (r.total_minutes or 0.0)
            return totals

        this_week_totals = _sum_by_subject(this_week_start, this_week_end)
        last_week_totals = _sum_by_subject(last_week_start, last_week_end)
        all_subjects = sorted(set(list(this_week_totals.keys()) + list(last_week_totals.keys())))

        weekly_comparison = [
            {
                'label': s,
                'this_week': round(this_week_totals.get(s, 0.0), 1),
                'last_week': round(last_week_totals.get(s, 0.0), 1),
            }
            for s in all_subjects
        ]

        # ── Doughnut – total minutes by subject (over requested days) ─────────
        history_start = today - timedelta(days=days - 1)
        recs_all = self.search([('date', '>=', history_start)])
        doughnut_totals = {}  # {subject_name: minutes}
        doughnut_subject_ids = {}  # {subject_name: subject_id}
        for r in recs_all:
            subj = r.subject_id.name if r.subject_id else 'Unknown'
            doughnut_totals[subj] = doughnut_totals.get(subj, 0.0) + (r.total_minutes or 0.0)
            if r.subject_id and subj not in doughnut_subject_ids:
                doughnut_subject_ids[subj] = r.subject_id.id

        # Get subject colors for doughnut
        subject_color_map = self.env['op.subject'].get_subject_colors_map()
        all_op_subjects = self.env['op.subject'].search([])
        name_to_color = {}
        for s in all_op_subjects:
            color = subject_color_map.get(s.id)
            if color:
                name_to_color[s.name] = color

        doughnut_default_colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#C9CBCF', '#E7E9ED',
        ]
        doughnut_labels = list(doughnut_totals.keys())
        doughnut_colors = [
            name_to_color.get(lbl, doughnut_default_colors[i % len(doughnut_default_colors)])
            for i, lbl in enumerate(doughnut_labels)
        ]

        subject_doughnut = {
            'labels': doughnut_labels,
            'data': [round(doughnut_totals[lbl], 1) for lbl in doughnut_labels],
            'colors': doughnut_colors,
        }

        # ── Historical stacked bar ─────────────────────────────────────────────
        # Group by date (daily for ≤90 days, by week for >90 days)
        use_weekly = days > 90
        history_recs = self.search([('date', '>=', history_start)])

        bar_data = {}  # {label: {subject: minutes}}
        for r in history_recs:
            if not r.date:
                continue
            if use_weekly:
                # ISO week label e.g. "2024-W02"
                label = f"{r.date.isocalendar()[0]}-W{r.date.isocalendar()[1]:02d}"
            else:
                label = str(r.date)
            subj = r.subject_id.name if r.subject_id else 'Unknown'
            if label not in bar_data:
                bar_data[label] = {}
            bar_data[label][subj] = bar_data[label].get(subj, 0.0) + (r.total_minutes or 0.0)

        bar_labels = sorted(bar_data.keys())
        bar_subjects = sorted(set(s for day in bar_data.values() for s in day.keys()))

        default_colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#C9CBCF', '#E7E9ED',
        ]
        # Try to use subject category colors (reuse name_to_color from doughnut above)

        history_datasets = []
        for idx, subj in enumerate(bar_subjects):
            color = name_to_color.get(subj, default_colors[idx % len(default_colors)])
            history_datasets.append({
                'label': subj,
                'data': [round(bar_data.get(lbl, {}).get(subj, 0.0), 1) for lbl in bar_labels],
                'backgroundColor': color + '80',
                'borderColor': color,
                'borderWidth': 2,
            })

        history_bar = {
            'labels': bar_labels,
            'datasets': history_datasets,
        }

        return {
            'weekly_comparison': weekly_comparison,
            'subject_doughnut': subject_doughnut,
            'history_bar': history_bar,
        }
