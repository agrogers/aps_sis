import re
import html as html_lib
import logging
from datetime import datetime, timedelta

from markupsafe import Markup
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class APSResourceSubmission(models.Model):
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
    def read_submission_data(self, domain, fields, orderby=False, limit=False):
        return self.env['aps.resource.submission'].sudo().search_read(
                domain=domain,
                fields=fields,
                order=orderby,
                limit=limit,
            )

    @api.model
    def get_progress_data_for_dashboard(self, student_id, period_start_date):
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
        """
        # Find all resources with ' Progress' in the name
        progress_resources = self.env['aps.resources'].search([
            ('name', 'ilike', ' Progress')
        ])

        if not progress_resources:
            return {
                'line_data': [],
                'bar_data': [],
                'pace_data': {},
                'subject_colors': {},
                'exclude_from_average': [],
                'exclude': [],
            }

        # Parse exclude_from_average and exclude from resource notes
        exclude_from_average = []
        exclude = []
        for resource in progress_resources:
            if resource.notes:
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
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude_from_average:
                            exclude_from_average.append(cleaned_name)

                match = re.search(r'\bexclude:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude:
                            exclude.append(cleaned_name)

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

        # Filter out excluded subjects
        if exclude:
            all_subjects = all_subjects.filtered(lambda s: s.name not in exclude)

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
                    if subject.id not in current_progress:
                        current_progress[subject.id] = {
                            'result_percent': submission.result_percent,
                            'date': date_to_use
                        }
                    else:
                        # Update if this is a more recent submission
                        if date_to_use > current_progress[subject.id]['date']:
                            current_progress[subject.id] = {
                                'result_percent': submission.result_percent,
                                'date': date_to_use
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
            # Sort by date and remove duplicates
            sorted_points = sorted(data_points, key=lambda x: x['date'])
            all_subject_data[subject_id] = sorted_points

        # Build bar data (current progress)
        bar_data = []
        for subject_id, progress_data in current_progress.items():
            subject = all_subjects.filtered(lambda s: s.id == subject_id)
            if subject:
                bar_data.append({
                    'subject_id': subject_id,
                    'subject_name': subject.name,
                    'progress': progress_data['result_percent'],  # Extract result_percent from dict
                    'color': subject_colors.get(subject_id, '#6c757d')  # Fallback to gray
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
    def get_student_comparison_data(self):
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
        # Find all resources with ' Progress' in the name
        progress_resources = self.env['aps.resources'].search([
            ('name', 'ilike', ' Progress')
        ])

        if not progress_resources:
            return {
                'student_data': [],
                'subject_list': [],
                'subject_colors': {},
                'pace_average': 0,
                'exclude_from_average': []
            }

        # Parse exclude_from_average and exclude from resource notes
        exclude_from_average = []
        exclude = []
        for resource in progress_resources:
            if resource.notes:
                # Strip HTML tags if present
                notes_text = resource.notes
                if isinstance(notes_text, Markup) or '<' in str(notes_text):
                    notes_text = str(notes_text)
                    notes_text = re.sub(r'<br\s*/?>', '\n', notes_text, flags=re.IGNORECASE)
                    notes_text = re.sub(r'</(?:p|div|li)>', '\n', notes_text, flags=re.IGNORECASE)
                    notes_text = re.sub(r'<[^>]+>', '', notes_text)
                # Decode HTML entities (e.g., &nbsp; -> space)
                notes_text = html_lib.unescape(str(notes_text))
                notes_text = notes_text.replace('\xa0', ' ')

                match = re.search(r'\bexclude_from_average:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude_from_average:
                            exclude_from_average.append(cleaned_name)

                match = re.search(r'\bexclude:\s*(.+?)(?=\b\w+:|\n|$)', notes_text, re.IGNORECASE)
                if match:
                    for subject_name in match.group(1).split(','):
                        cleaned_name = subject_name.strip()
                        if cleaned_name and cleaned_name not in exclude:
                            exclude.append(cleaned_name)

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

        # Get subject colors
        subject_colors = self.env['op.subject'].get_subject_colors_map(all_subjects.ids)

        # Build student progress data: {student_id: {subject_id: {'result': x, 'date': y}}}
        student_progress = {}
        pace_values = []
        redline_values = []
        processed_resources_for_pace = set()

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
                if subject.name in exclude:
                    continue
                date_to_use = submission.date_submitted or submission.date_completed
                if not date_to_use:
                    continue

                # Track latest result for each subject (most recent submission)
                if subject.id not in student_progress[student_id]['subjects']:
                    student_progress[student_id]['subjects'][subject.id] = {
                        'result_percent': submission.result_percent,
                        'date': date_to_use
                    }
                else:
                    # Update if this is a more recent submission
                    if date_to_use > student_progress[student_id]['subjects'][subject.id]['date']:
                        student_progress[student_id]['subjects'][subject.id] = {
                            'result_percent': submission.result_percent,
                            'date': date_to_use
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

    # endregion - Get Data
