from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class APSResourceSubmissionDashboardData(models.Model):
    _inherit = 'aps.resource.submission'

# region - Get Data    
    @api.model
    def read_group_points_by_student(self, domain, orderby=False):
        return self.sudo().read_group(
            domain=domain,
            fields=["points:sum"],
            groupby=["student_id"],
            orderby=orderby,
            lazy=True,  # or False, depending on your needs
        )
    
    @api.model
    def _get_progress_resources(self):
        """Return all resources whose type name contains 'Progress'."""
        return self.env['aps.resources'].search([
            ('type_id.name', 'ilike', 'Progress')
        ])

    @staticmethod
    def _parse_resource_notes_excludes(resources):
        """Parse 'exclude:' and 'exclude_from_average:' lists from resource notes.

        Returns (exclude, exclude_from_average) — two lists of subject name strings.
        """
        import re
        import html as html_lib
        from markupsafe import Markup

        exclude = []
        exclude_from_average = []
        for resource in resources:
            if not resource.notes:
                continue
            notes_text = resource.notes
            if isinstance(notes_text, Markup) or '<' in str(notes_text):
                notes_text = str(notes_text)
                notes_text = re.sub(r'<br\s*/?>', '\n', notes_text, flags=re.IGNORECASE)
                notes_text = re.sub(r'</(?:p|div|li)>', '\n', notes_text, flags=re.IGNORECASE)
                notes_text = re.sub(r'<[^>]+>', '', notes_text)
            notes_text = html_lib.unescape(str(notes_text))
            notes_text = notes_text.replace('\xa0', ' ')

            match = re.search(r'\bexclude_from_average:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
            if match:
                for name in match.group(1).split(','):
                    cleaned = name.strip()
                    if cleaned and cleaned not in exclude_from_average:
                        exclude_from_average.append(cleaned)

            match = re.search(r'\bexclude:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
            if match:
                for name in match.group(1).split(','):
                    cleaned = name.strip()
                    if cleaned and cleaned not in exclude:
                        exclude.append(cleaned)

        return exclude, exclude_from_average

    @api.model
    def _progress_result_sort_key(self, date_value, result_percent):
        """Sort progress snapshots by date, then result percent.

        This keeps "current progress" selection consistent across the dashboard,
        progress leaderboard, completion leaderboard, and student comparison chart.
        """
        normalized_date = fields.Date.to_date(date_value) if date_value else False
        normalized_result = result_percent if result_percent is not None else float('-inf')
        return (
            normalized_date.toordinal() if normalized_date else -1,
            normalized_result,
        )

    @api.model
    def _should_replace_progress_result(self, existing, date_value, result_percent):
        """Return True when a candidate progress snapshot should replace the current one."""
        if not date_value:
            return False

        existing_date = existing.get('date') if existing else False
        existing_result = existing.get('result_percent') if existing else False
        return self._progress_result_sort_key(date_value, result_percent) > self._progress_result_sort_key(
            existing_date,
            existing_result,
        )

    @api.model
    def _collapse_progress_points_by_date(self, data_points):
        """Return one point per date, keeping the highest score for that day."""
        points_by_date = {}

        for point in data_points or []:
            date_value = point.get('date')
            if not date_value:
                continue

            normalized_date = fields.Date.to_date(date_value)
            if not normalized_date:
                continue

            date_key = normalized_date.isoformat()
            candidate = dict(point)
            candidate['date'] = date_key

            existing = points_by_date.get(date_key)
            if not existing or self._should_replace_progress_result(
                existing,
                date_key,
                candidate.get('result_percent'),
            ):
                points_by_date[date_key] = candidate

        return sorted(
            points_by_date.values(),
            key=lambda p: self._progress_result_sort_key(p.get('date'), p.get('result_percent')),
        )

    @api.model
    def _get_avatar_and_image_maps(self, partner_ids):
        """Return avatar and image maps without forcing filestore binary reads."""
        if not partner_ids:
            return {}, {}

        user_data = self.env['res.users'].sudo().search_read(
            [('partner_id', 'in', partner_ids)],
            ['partner_id', 'avatar_id'],
        )
        avatar_map = {d['partner_id'][0]: d['avatar_id'][0] for d in user_data if d.get('avatar_id')}

        # bin_size=True returns metadata/size marker for binaries instead of reading file contents.
        partners = self.env['res.partner'].sudo().browse(partner_ids).with_context(bin_size=True)
        image_map = {p.id: bool(p.image_128) for p in partners}
        return avatar_map, image_map
    
    @api.model
    def get_progress_leaderboard_data(self, limit=30, category_id=None):
        """Return top N students by average progress across enrolled, non-excluded subjects.

        Uses the same subject inclusion/exclusion logic as the Progress charts:
        - Resources with ' Progress' in the name are used
        - Subjects in the resource notes 'exclude:' list are completely excluded
        - Only subjects the student is currently enrolled in are counted
        - Each student's most-recent result_percent per subject is averaged
        - Returns up to `limit` students ranked by average progress (descending)

        Each entry contains: rank, student_id, student_name, total_points (= rounded avg %)
        """
        progress_resources = self._get_progress_resources()
        if not progress_resources:
            return []

        exclude, _exclude_from_avg = self._parse_resource_notes_excludes(progress_resources)

        # Fetch all active submitted/complete submissions for progress resources
        submissions = self.sudo().search([
            ('resource_id', 'in', progress_resources.ids),
            ('submission_active', '=', True),
            ('state', 'in', ['submitted', 'complete']),
        ], order='date_submitted asc')
        if not submissions:
            return []

        # Collect all subjects referenced in these submissions, then filter out excluded ones
        all_subjects = self.env['op.subject']
        for sub in submissions:
            all_subjects |= sub.subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)
        if category_id:
            all_subjects = all_subjects.filtered(lambda s: s.category_id.id == category_id)

        # Restrict to subjects students are currently enrolled in
        student_enrolled_subjects = {}
        all_enrolled_subject_ids = set()
        partner_ids = list({sub.student_id.id for sub in submissions if sub.student_id})
        student_records = self.env['op.student'].sudo().search([('partner_id', 'in', partner_ids)])
        for student_record in student_records:
            running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
            enrolled_ids = set(running_courses.mapped('subject_ids').ids)
            student_enrolled_subjects[student_record.partner_id.id] = enrolled_ids
            all_enrolled_subject_ids.update(enrolled_ids)
        if all_enrolled_subject_ids:
            all_subjects = all_subjects.filtered(lambda s: s.id in all_enrolled_subject_ids)

        all_subject_ids_set = set(all_subjects.ids)

        # Build per-student, per-subject latest progress (result_percent)
        student_progress = {}
        for submission in submissions:
            student_id = submission.student_id.id
            if not student_id:
                continue
            if student_id not in student_progress:
                student_progress[student_id] = {
                    'name': submission.student_id.name,
                    'subjects': {},
                }
            for subject in submission.subjects:
                if subject.id not in all_subject_ids_set:
                    continue
                student_enrolled = student_enrolled_subjects.get(student_id)
                if student_enrolled is not None and subject.id not in student_enrolled:
                    continue
                date_to_use = submission.date_submitted or submission.date_completed
                if not date_to_use:
                    continue
                existing = student_progress[student_id]['subjects'].get(subject.id)
                if self._should_replace_progress_result(existing, date_to_use, submission.result_percent):
                    student_progress[student_id]['subjects'][subject.id] = {
                        'result_percent': submission.result_percent,
                        'date': fields.Date.to_date(date_to_use),
                    }

        # Calculate average progress per student and build sorted leaderboard
        leaderboard = []
        for student_id, student_info in student_progress.items():
            progresses = [
                info['result_percent']
                for info in student_info['subjects'].values()
                if info['result_percent'] is not None
            ]
            if not progresses:
                continue
            avg_progress = sum(progresses) / len(progresses)
            leaderboard.append({
                'student_id': student_id,
                'student_name': student_info['name'],
                'avg_progress': avg_progress,
            })

        leaderboard.sort(key=lambda x: x['avg_progress'], reverse=True)
        leaderboard = leaderboard[:limit]

        result = [
            {
                'rank': i + 1,
                'student_id': entry['student_id'],
                'student_name': entry['student_name'],
                'total_points': round(entry['avg_progress']),
            }
            for i, entry in enumerate(leaderboard)
        ]

        # Enrich with avatar and partner image info
        partner_ids = [r['student_id'] for r in result]
        avatar_map, image_map = self._get_avatar_and_image_maps(partner_ids)
        for entry in result:
            entry['avatar_id'] = avatar_map.get(entry['student_id'], False)
            entry['has_image'] = image_map.get(entry['student_id'], False)

        return result

    @api.model
    def get_completion_leaderboard_data(self, limit=30, category_id=None):
        """Return top N students ranked by predicted total progress at the course deadline.

        Uses the same subject inclusion/exclusion and enrolment logic as
        get_progress_leaderboard_data and mirrors the _calculatePredictionData
        logic from the frontend (progress_charts.js).

        For each student / subject:
        - Calculate daily progress rate from the student's historical line data
          (first to last submitted data-point for that subject).
        - Determine the deadline: the latest end_date across all progress resources.
        - Project: predicted_total = min(current + daily_rate * days_remaining, 100)
        - Average the predicted totals across all enrolled, non-excluded subjects.

        Returns up to `limit` students ranked by predicted average (descending).
        Each entry: rank, student_id, student_name, total_points (= rounded predicted %)
        """
        from datetime import date as date_type, timedelta

        progress_resources = self._get_progress_resources()
        if not progress_resources:
            return {'entries': [], 'deadline': False}

        exclude, _exclude_from_avg = self._parse_resource_notes_excludes(progress_resources)

        # --- Determine global deadline (latest end_date across all progress resources) ---
        deadline = None
        for resource in progress_resources:
            pace_dates = resource.get_pace_dates()
            if pace_dates.get('end_date'):
                if deadline is None or pace_dates['end_date'] > deadline:
                    deadline = pace_dates['end_date']

        today = date_type.today()
        if deadline and deadline > today:
            days_remaining = (deadline - today).days
        else:
            days_remaining = 0  # No future deadline → no projection, use current progress

        # --- Fetch submissions ---
        submissions = self.sudo().search([
            ('resource_id', 'in', progress_resources.ids),
            ('submission_active', '=', True),
            ('state', 'in', ['submitted', 'complete']),
        ], order='date_submitted asc')
        if not submissions:
            return {'entries': [], 'deadline': deadline.isoformat() if deadline else False}

        # --- Collect subjects, apply exclude filter ---
        all_subjects = self.env['op.subject']
        for sub in submissions:
            all_subjects |= sub.subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)
        if category_id:
            all_subjects = all_subjects.filtered(lambda s: s.category_id.id == category_id)

        # --- Restrict to enrolled subjects ---
        student_enrolled_subjects = {}
        all_enrolled_subject_ids = set()
        partner_ids = list({sub.student_id.id for sub in submissions if sub.student_id})
        student_records = self.env['op.student'].sudo().search([('partner_id', 'in', partner_ids)])
        for student_record in student_records:
            running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
            enrolled_ids = set(running_courses.mapped('subject_ids').ids)
            student_enrolled_subjects[student_record.partner_id.id] = enrolled_ids
            all_enrolled_subject_ids.update(enrolled_ids)
        if all_enrolled_subject_ids:
            all_subjects = all_subjects.filtered(lambda s: s.id in all_enrolled_subject_ids)

        all_subject_ids_set = set(all_subjects.ids)

        # --- Build per-student, per-subject historical data ---
        # Dates are normalised to date objects at extraction to avoid mixed-type arithmetic.
        # student_history: {student_id: {subject_id: [(date, result_percent), ...]}}
        student_history = {}
        student_names = {}
        for submission in submissions:
            student_id = submission.student_id.id
            if not student_id:
                continue
            student_names[student_id] = submission.student_id.name
            if student_id not in student_history:
                student_history[student_id] = {}
            student_enrolled = student_enrolled_subjects.get(student_id)
            for subject in submission.subjects:
                if subject.id not in all_subject_ids_set:
                    continue
                if student_enrolled is not None and subject.id not in student_enrolled:
                    continue
                date_to_use = submission.date_submitted or submission.date_completed
                if not date_to_use:
                    continue
                # Normalise to a date object (Odoo datetime fields return datetime instances)
                if hasattr(date_to_use, 'date'):
                    date_to_use = date_to_use.date()
                if subject.id not in student_history[student_id]:
                    student_history[student_id][subject.id] = []
                student_history[student_id][subject.id].append(
                    (date_to_use, submission.result_percent or 0)
                )

        # --- Calculate predicted total progress per student ---
        leaderboard = []
        for student_id, subjects in student_history.items():
            predicted_totals = []
            for subject_id, data_points in subjects.items():
                if not data_points:
                    continue
                # Sort ascending by date
                sorted_points = sorted(
                    data_points,
                    key=lambda x: self._progress_result_sort_key(x[0], x[1]),
                )
                current_progress = sorted_points[-1][1]  # Latest result_percent

                if current_progress >= 100:
                    predicted_totals.append(100.0)
                    continue

                # Calculate daily rate using only the last 4 months of data
                last_date, last_progress = sorted_points[-1]
                four_months_ago = today - timedelta(days=120)
                recent_points = [(d, p) for d, p in sorted_points if d >= four_months_ago]
                first_date, first_progress = recent_points[0] if len(recent_points) >= 2 else sorted_points[0]
                days_between = (last_date - first_date).days

                if days_between > 0:
                    daily_rate = (last_progress - first_progress) / days_between
                else:
                    daily_rate = 0

                if daily_rate > 0 and days_remaining > 0:
                    predicted_total = min(current_progress + daily_rate * days_remaining, 100.0)
                else:
                    predicted_total = current_progress

                predicted_totals.append(predicted_total)

            if not predicted_totals:
                continue
            avg_predicted = sum(predicted_totals) / len(predicted_totals)
            leaderboard.append({
                'student_id': student_id,
                'student_name': student_names.get(student_id, ''),
                'avg_predicted': avg_predicted,
            })

        leaderboard.sort(key=lambda x: x['avg_predicted'], reverse=True)
        leaderboard = leaderboard[:limit]

        result = [
            {
                'rank': i + 1,
                'student_id': entry['student_id'],
                'student_name': entry['student_name'],
                'total_points': round(entry['avg_predicted']),
            }
            for i, entry in enumerate(leaderboard)
        ]

        # --- Enrich with avatar / image info ---
        partner_ids = [r['student_id'] for r in result]
        avatar_map, image_map = self._get_avatar_and_image_maps(partner_ids)
        for entry in result:
            entry['avatar_id'] = avatar_map.get(entry['student_id'], False)
            entry['has_image'] = image_map.get(entry['student_id'], False)

        return {
            'entries': result,
            'deadline': deadline.isoformat() if deadline else False,
        }

    @api.model
    def get_leaderboard_data(self, domain, limit=5):
        """Return top N students by points for the leaderboard.

        Each entry contains:
          rank, student_id, student_name, total_points, image_url
        """
        groups = self.sudo().read_group(
            domain=domain,
            fields=["points:sum"],
            groupby=["student_id"],
            orderby="points:sum desc",
            lazy=True,
        )[:limit]

        result = []
        for i, group in enumerate(groups):
            student_id = group['student_id'][0]
            student_name = group['student_id'][1]
            total_points = group['points'] or 0
            result.append({
                'rank': i + 1,
                'student_id': student_id,
                'student_name': student_name,
                'total_points': total_points,
            })

        # Enrich with avatar and partner image info
        partner_ids = [r['student_id'] for r in result]
        avatar_map, image_map = self._get_avatar_and_image_maps(partner_ids)
        for entry in result:
            entry['avatar_id'] = avatar_map.get(entry['student_id'], False)
            entry['has_image'] = image_map.get(entry['student_id'], False)

        return result

    @api.model
    def read_submission_data(self, domain, fields, orderby=False, limit=False):
        return self.env['aps.resource.submission'].sudo().search_read(
                domain=domain,
                fields=fields,
                order=orderby,
                limit=limit,
            )
    
    @api.model
    def get_progress_data_for_dashboard(self, student_id, period_start_date, category_id=False):
        """
        Get student progress data for dashboard charts.
        Fetches submissions for resources with ' Progress' in the name.
        Returns:
        - line_data: List of progress data points over time by subject
        - bar_data: Current progress percentage by subject
        - pace_data: PACE information from resource notes (including redline dates)
        - subject_colors: Color mapping for subjects
        - exclude_from_average: Subject names to exclude from redline highlight
        - exclude: Subjects to completely exclude from the chart

        Only subjects currently enrolled by the student (running course subject_ids)
        are included in chart data.
        """
        from datetime import datetime, timedelta
        
        progress_resources = self._get_progress_resources()
        
        if not progress_resources:
            return {
                'line_data': [],
                'bar_data': [],
                'pace_data': {},
                'subject_colors': {},
                'exclude_from_average': [],
                'exclude': [],
            }
        
        exclude, exclude_from_average = self._parse_resource_notes_excludes(progress_resources)
        
        # Build domain for submissions
        domain = [
            ('resource_id', 'in', progress_resources.ids),
            ('student_id', '=', student_id),
            ('submission_active', '=', True),
            ('state', 'in', ['submitted', 'complete'])
        ]
        
        # Fetch submissions
        submissions = self.search(domain, order='date_submitted asc')
        
        if not submissions:
            return {
                'line_data': [],
                'bar_data': [],
                'pace_data': {},
                'subject_colors': {},
                'exclude_from_average': exclude_from_average,
                'exclude': exclude,
            }
        
        # Get all subjects from submissions
        all_subjects = self.env['op.subject']
        for sub in submissions:
            all_subjects |= sub.subjects

        # Restrict to the student's currently enrolled subjects (running courses only)
        student_record = self.env['op.student'].sudo().search([
            ('partner_id', '=', student_id)
        ], limit=1)
        enrolled_subject_ids = set()
        if student_record:
            running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
            enrolled_subject_ids = set(running_courses.mapped('subject_ids').ids)
        if enrolled_subject_ids:
            all_subjects = all_subjects.filtered(lambda s: s.id in enrolled_subject_ids)
        else:
            all_subjects = self.env['op.subject']
        
        # Filter out excluded subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)

        # Apply optional subject category filter
        if category_id:
            all_subjects = all_subjects.filtered(lambda s: s.category_id.id == category_id)

        # Nothing left after enrollment/exclude filtering
        if not all_subjects:
            return {
                'line_data': [],
                'bar_data': [],
                'pace_data': {},
                'subject_colors': {},
                'exclude_from_average': exclude_from_average,
                'exclude': exclude,
                'period_start': period_start_date,
                'period_end': datetime.now().date().isoformat(),
            }

        allowed_subject_ids = set(all_subjects.ids)
        
        # Get subject colors (with automatic color generation for subjects without categories)
        subject_colors = self.env['op.subject'].get_subject_colors_map(all_subjects.ids)
        
        # Group submissions by subject and build historical data
        subject_data = {}  # {subject_id: [(date, result_percent), ...]}
        current_progress = {}  # {subject_id: {'result_percent': x, 'date': y}}
        pace_info = {}  # {resource_id: {start_date, end_date, redline_start_date, redline_end_date, resource_name}}
        
        for submission in submissions:
            for subject in submission.subjects:
                if subject.name in exclude:
                    continue
                if subject.id not in allowed_subject_ids:
                    continue
                if subject.id not in subject_data:
                    subject_data[subject.id] = []
                
                # Only use submitted or completed dates since we're filtering for those states
                date_to_use = submission.date_submitted or submission.date_completed
                if date_to_use:
                    subject_data[subject.id].append({
                        'date': date_to_use.isoformat(),
                        'result_percent': submission.result_percent,
                        'subject_id': subject.id,
                        'subject_name': subject.name,
                    })
                    
                    # Track latest result for bar chart (most recent submission by date)
                    existing = current_progress.get(subject.id)
                    if self._should_replace_progress_result(existing, date_to_use, submission.result_percent):
                        current_progress[subject.id] = {
                            'result_percent': submission.result_percent,
                            'date': fields.Date.to_date(date_to_use)
                        }
                
                # Get PACE/redline dates from resource notes
                # Note: resource.subjects is a Many2many field - one resource can have multiple subjects
                # The PACE dates from the resource's notes field apply to ALL subjects linked to that resource
                # Store PACE info once per resource (not per subject) to avoid duplicate PACE lines
                if submission.resource_id and submission.resource_id.id not in pace_info:
                    pace_dates = submission.resource_id.get_pace_dates()
                    if any([
                        pace_dates['start_date'],
                        pace_dates['end_date'],
                        pace_dates['redline_start_date'],
                        pace_dates['redline_end_date'],
                    ]):
                        pace_info[submission.resource_id.id] = {
                            'start_date': pace_dates['start_date'].isoformat() if pace_dates['start_date'] else False,
                            'end_date': pace_dates['end_date'].isoformat() if pace_dates['end_date'] else False,
                            'redline_start_date': pace_dates['redline_start_date'].isoformat() if pace_dates['redline_start_date'] else False,
                            'redline_end_date': pace_dates['redline_end_date'].isoformat() if pace_dates['redline_end_date'] else False,
                            'resource_name': submission.resource_id.name,
                        }
        
        # Return all data points (sorted by date) - no filtering by period
        # Frontend will handle zooming to the selected period
        all_subject_data = {}
        
        for subject_id, data_points in subject_data.items():
            all_subject_data[subject_id] = self._collapse_progress_points_by_date(data_points)
        
        # Build bar data (current progress, split into >120 days old and last 120 days)
        cutoff_date = (datetime.now().date() - timedelta(days=120))
        cutoff_str = cutoff_date.isoformat()
        bar_data = []
        for subject_id, progress_data in current_progress.items():
            subject = all_subjects.filtered(lambda s: s.id == subject_id)
            if subject:
                current_pct = progress_data['result_percent']
                # Find the last data point on or before the 120-day cutoff
                sorted_pts = all_subject_data.get(subject_id, [])
                pts_at_cutoff = [p for p in sorted_pts if p['date'][:10] <= cutoff_str]
                progress_old = pts_at_cutoff[-1]['result_percent'] if pts_at_cutoff else 0
                progress_recent = max(0, current_pct - progress_old)
                bar_data.append({
                    'subject_id': subject_id,
                    'subject_name': subject.name,
                    'progress': current_pct,
                    'progress_old': progress_old,
                    'progress_recent': progress_recent,
                    'color': subject_colors.get(subject_id, '#6c757d'),
                })
        
        return {
            'line_data': all_subject_data,
            'bar_data': bar_data,
            'pace_data': pace_info,
            'subject_colors': subject_colors,
            'exclude_from_average': exclude_from_average,
            'exclude': exclude,
            'period_start': period_start_date,  # For zoom reference
            'period_end': datetime.now().date().isoformat()  # Today as period end
        }

    @api.model
    def get_student_comparison_data(self, category_id=False):
        """
        Get progress comparison data for all students.
        Returns the most recent progress score for each student in each subject.
        Returns:
        - student_data: List of students with their progress by subject
        - subject_list: List of all subjects
        - subject_colors: Color mapping for subjects
        - pace_average: Average PACE percentage across resources
        - exclude_from_average: List of subject names to exclude from average calculation
        """
        from datetime import datetime
        
        progress_resources = self._get_progress_resources()
        
        if not progress_resources:
            return {
                'student_data': [],
                'subject_list': [],
                'subject_colors': {},
                'pace_average': 0,
                'exclude_from_average': []
            }
        
        exclude, exclude_from_average = self._parse_resource_notes_excludes(progress_resources)
        
        # Build domain for submissions
        domain = [
            ('resource_id', 'in', progress_resources.ids),
            ('submission_active', '=', True),
            ('state', 'in', ['submitted', 'complete'])
        ]
        
        # Fetch submissions
        submissions = self.search(domain, order='date_submitted asc')
        
        if not submissions:
            return {
                'student_data': [],
                'subject_list': [],
                'subject_colors': {},
                'pace_average': 0
            }
        
        # Get all subjects from submissions
        all_subjects = self.env['op.subject']
        for sub in submissions:
            all_subjects |= sub.subjects
        
        # Filter out excluded subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)

        # Restrict to subjects students are currently enrolled in
        student_enrolled_subjects = {}  # {partner_id: set(enrolled_subject_ids)}
        all_enrolled_subject_ids = set()
        partner_ids = list({sub.student_id.id for sub in submissions if sub.student_id})
        student_records = self.env['op.student'].sudo().search([('partner_id', 'in', partner_ids)])
        for student_record in student_records:
            running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
            enrolled_ids = set(running_courses.mapped('subject_ids').ids)
            student_enrolled_subjects[student_record.partner_id.id] = enrolled_ids
            all_enrolled_subject_ids.update(enrolled_ids)
        if all_enrolled_subject_ids:
            all_subjects = all_subjects.filtered(lambda s: s.id in all_enrolled_subject_ids)

        # Apply optional subject category filter
        if category_id:
            all_subjects = all_subjects.filtered(lambda s: s.category_id.id == category_id)

        # Get subject colors
        subject_colors = self.env['op.subject'].get_subject_colors_map(all_subjects.ids)
        
        # Build student progress data: {student_id: {subject_id: {'result': x, 'date': y}}}
        student_progress = {}
        pace_values = []
        redline_values = []
        processed_resources_for_pace = set()
        all_subject_ids_set = set(all_subjects.ids)  # enrolled + not excluded

        for submission in submissions:
            student_id = submission.student_id.id
            if not student_id:
                continue
                
            if student_id not in student_progress:
                student_progress[student_id] = {
                    'name': submission.student_id.name,
                    'subjects': {}
                }
            
            for subject in submission.subjects:
                if subject.id not in all_subject_ids_set:
                    continue
                student_enrolled = student_enrolled_subjects.get(student_id)
                if student_enrolled is not None and subject.id not in student_enrolled:
                    continue
                date_to_use = submission.date_submitted or submission.date_completed
                if not date_to_use:
                    continue
                
                # Track latest result for each subject (most recent submission)
                existing = student_progress[student_id]['subjects'].get(subject.id)
                if self._should_replace_progress_result(existing, date_to_use, submission.result_percent):
                    student_progress[student_id]['subjects'][subject.id] = {
                        'result_percent': submission.result_percent,
                        'date': fields.Date.to_date(date_to_use)
                    }
            
            # Calculate PACE and redline for averaging (process each resource only once)
            if submission.resource_id and submission.resource_id.id not in processed_resources_for_pace:
                processed_resources_for_pace.add(submission.resource_id.id)
                pace_dates = submission.resource_id.get_pace_dates()
                today = datetime.now().date()
                
                if pace_dates['start_date'] and pace_dates['end_date']:
                    start_date = pace_dates['start_date']
                    end_date = pace_dates['end_date']
                    if start_date <= today <= end_date:
                        total_days = (end_date - start_date).days
                        if total_days > 0:
                            days_from_start = (today - start_date).days
                            pace_percent = (days_from_start / total_days) * 100
                            pace_values.append(min(100, max(0, pace_percent)))
                
                if pace_dates['redline_start_date'] and pace_dates['redline_end_date']:
                    rl_start = pace_dates['redline_start_date']
                    rl_end = pace_dates['redline_end_date']
                    if rl_start <= today <= rl_end:
                        total_days = (rl_end - rl_start).days
                        if total_days > 0:
                            days_from_start = (today - rl_start).days
                            redline_percent = (days_from_start / total_days) * 100
                            redline_values.append(min(100, max(0, redline_percent)))
        
        # Format for frontend
        student_list = []
        for student_id, student_info in student_progress.items():
            student_data = {
                'student_id': student_id,
                'student_name': student_info['name'],
                'progress_by_subject': {}
            }
            for subject_id, progress_info in student_info['subjects'].items():
                student_data['progress_by_subject'][subject_id] = progress_info['result_percent']
            student_list.append(student_data)
        
        # Calculate average PACE and redline
        pace_average = sum(pace_values) / len(pace_values) if pace_values else 0
        redline_average = sum(redline_values) / len(redline_values) if redline_values else 0
        
        # Build subject list
        subject_list = []
        for subject in all_subjects:
            subject_list.append({
                'id': subject.id,
                'name': subject.name,
                'color': subject_colors.get(subject.id, '#6c757d')
            })
        
        return {
            'student_data': student_list,
            'subject_list': subject_list,
            'subject_colors': subject_colors,
            'pace_average': pace_average,
            'redline_average': redline_average,
            'exclude_from_average': exclude_from_average,
            'exclude': exclude,
        }

    @api.model
    def get_current_user_is_teacher(self):
        """
        Check if the current user is a teacher.
        Returns True if the user is in the group_aps_teacher group.
        """
        teacher_group = self.env.ref('aps_sis.group_aps_teacher', raise_if_not_found=False)
        if not teacher_group:
            return False
        
        current_user = self.env.user
        return teacher_group in current_user.groups_id

    @api.model
    def get_subject_categories_for_dashboard(self, student_id=False):
        """Return subject categories available for a student's active submissions.

        Uses a single SQL query to walk submissions → subjects → categories
        instead of fetching every submission record to the client.
        Returns a list of dicts: [{'id': int, 'name': str}, ...]
        """
        lang = self.env.lang or 'en_US'
        query = """
            SELECT DISTINCT sc.id,
                   COALESCE(sc.name->>%s, sc.name->>'en_US',
                            (SELECT value FROM jsonb_each_text(sc.name) LIMIT 1))
              FROM aps_resource_submission_op_subject_rel rel
              JOIN aps_resource_submission s ON s.id = rel.aps_resource_submission_id
              JOIN aps_resource_task t       ON t.id = s.task_id
              JOIN op_subject sub            ON sub.id = rel.op_subject_id
              JOIN aps_subject_category sc   ON sc.id = sub.category_id
             WHERE s.submission_active = true
        """
        params = [lang]
        if student_id:
            query += " AND t.student_id = %s"
            params.append(int(student_id))
        query += " ORDER BY 2"
        self.env.cr.execute(query, params)
        return [{'id': row[0], 'name': row[1]} for row in self.env.cr.fetchall()]
# endregion - Get Data
