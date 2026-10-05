from datetime import timedelta
import re
from odoo import models, fields, api


class APSResource(models.Model):
    _inherit = 'aps.resources'

    @api.model
    def get_teacher_dashboard_classes(self, category_id=False, days=30):
        """Return classes with submissions in the filtered period."""
        today = fields.Date.today()
        start_date = (today - timedelta(days=days)) if days != -1 else False
        submission_domain = []
        if start_date:
            submission_domain.append(('date_assigned', '>=', str(start_date)))
        if category_id:
            subjects = self.env['aps.subject'].search(
                [('category_id', '=', category_id)]
            )
            submission_domain.append(
                ('resource_id.subjects', 'in', subjects.ids)
                if subjects else ('id', '=', False)
            )
        partner_ids = self.env['aps.resource.submission'].search(
            submission_domain
        ).mapped('student_id').ids
        if not partner_ids:
            return []

        enrollment_domain = [
            ('student_id.partner_id', 'in', partner_ids),
            ('state', '=', 'enrolled'),
        ]
        current_year = self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        )
        if current_year:
            enrollment_domain.append(
                ('class_id.academic_year_id', '=', current_year.id)
            )
        if category_id:
            enrollment_domain.append(
                ('class_id.subject_id.category_id', '=', category_id)
            )
        classes = self.env['aps.student.class'].search(
            enrollment_domain
        ).mapped('class_id')
        return classes.sorted(lambda record: (record.name or '').lower()).read(
            ['id', 'name']
        )

    @api.model
    def get_teacher_dashboard_students(self, category_id=False, days=30, class_id=False):
        """Return enrolled students with submissions in the filtered period."""
        today = fields.Date.today()
        start_date = (today - timedelta(days=days)) if days != -1 else False
        submission_domain = []
        if start_date:
            submission_domain.append(('date_assigned', '>=', str(start_date)))
        submissions = self.env['aps.resource.submission'].search(submission_domain)
        partner_ids = submissions.mapped('student_id').ids
        if not partner_ids:
            return []

        current_year = self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        )
        enrollment_domain = [
            ('student_id.partner_id', 'in', partner_ids),
            ('state', '=', 'enrolled'),
        ]
        if current_year:
            enrollment_domain.append(
                ('class_id.academic_year_id', '=', current_year.id)
            )
        if category_id:
            enrollment_domain.append(
                ('class_id.subject_id.category_id', '=', category_id)
            )
        if class_id:
            enrollment_domain.append(('class_id', '=', class_id))
        enrollments = self.env['aps.student.class'].search(enrollment_domain)
        students = enrollments.mapped('student_id.partner_id')
        unique_students = self.env['res.partner'].browse(
            list(set(students.ids))
        ).sorted(lambda student: (student.name or '').lower())
        return unique_students.read(['id', 'name'])

    @api.model
    def get_teacher_dashboard_data(
        self, category_id=False, days=30, student_id=False, class_id=False
    ):
        """Return data for the teacher dashboard.

        Args:
            category_id: ID of the subject category to filter by, or False for all
            days: Number of days for the date range (default: 30), or -1 for All Time
        Returns a dict with:
            categories       – list of {id, name} for the category dropdown
            subject_resources – resources edited in period OR linked to subjects
            task_resources   – per-resource task aggregates ordered by most-recent assignment
        """
        today = fields.Date.today()
        start_date = (today - timedelta(days=days)) if days != -1 else False
        classes = self.get_teacher_dashboard_classes(category_id, days)
        class_id = int(class_id) if class_id else False
        if class_id not in {record['id'] for record in classes}:
            class_id = False
        students = self.get_teacher_dashboard_students(
            category_id, days, class_id
        )
        student_ids = {student['id'] for student in students}
        student_id = int(student_id) if student_id else False
        if student_id not in student_ids:
            student_id = False

        metric_base_domain = []
        if start_date:
            metric_base_domain.append(('date_assigned', '>=', str(start_date)))
        if category_id:
            metric_subjects = self.env['aps.subject'].search(
                [('category_id', '=', category_id)]
            )
            metric_base_domain.append(
                ('resource_id.subjects', 'in', metric_subjects.ids)
                if metric_subjects else ('id', '=', False)
            )
        if student_id:
            metric_base_domain.append(('task_id.student_id', '=', student_id))
        if class_id:
            class_partner_ids = self.env['aps.student.class'].search([
                ('class_id', '=', class_id),
                ('state', '=', 'enrolled'),
            ]).mapped('student_id.partner_id').ids
            metric_base_domain.append(
                ('task_id.student_id', 'in', class_partner_ids)
            )

        submission_model = self.env['aps.resource.submission']
        current_faculty = submission_model._get_current_faculty()
        review_domain = metric_base_domain + (
            [('review_requested_by', 'in', current_faculty.id)]
            if current_faculty else [('id', '=', False)]
        )
        labelled_domain = metric_base_domain + [
            ('submission_label', '!=', False),
        ]
        overdue_domain = metric_base_domain + [
            ('state', '=', 'assigned'),
            ('due_status', '=', 'late'),
        ]
        due_today_domain = metric_base_domain + [
            ('state', '=', 'assigned'),
            ('date_due', '=', str(today)),
        ]
        labelled_submissions = submission_model.search(labelled_domain)
        dashboard_metrics = {
            'review_requested': {
                'count': submission_model.search_count(review_domain),
                'domain': review_domain,
            },
            'unique_labels': {
                'count': len(set(labelled_submissions.mapped('submission_label'))),
                'domain': labelled_domain,
            },
            'overdue': {
                'count': submission_model.search_count(overdue_domain),
                'domain': overdue_domain,
            },
            'due_today': {
                'count': submission_model.search_count(due_today_domain),
                'domain': due_today_domain,
            },
        }

        # ------------------------------------------------------------------ #
        # Subject Categories
        # ------------------------------------------------------------------ #
        categories = self.env['aps.subject.category'].search_read(
            [], ['id', 'name'], order='name'
        )

        # ------------------------------------------------------------------ #
        # Section 3 – Subject/Edit Resources
        # ------------------------------------------------------------------ #
        subject_domain = [('subjects', '!=', False)]
        if category_id:
            subjects_in_cat = self.env['aps.subject'].search(
                [('category_id', '=', category_id)]
            )
            subject_domain = (
                [('subjects', 'in', subjects_in_cat.ids)]
                if subjects_in_cat
                else [('id', '=', False)]
            )

        if start_date:
            start_dt_str = fields.Datetime.to_string(
                fields.Datetime.from_string(str(start_date))
            )
            edit_domain = [('write_date', '>=', start_dt_str)]
            combined_domain = edit_domain + subject_domain
        else:
            combined_domain = subject_domain

        combined_domain = ['|', ('type_id.name', '=', 'Subject')] + combined_domain
        subject_resources = self.env['aps.resources'].search_read(
            combined_domain,
            ['id', 'name', 'display_name', 'type_id', 'subjects', 'write_date'],
            order='write_date desc',
            limit=200,
        )
        # Stringify dates for JSON serialisation
        for rec in subject_resources:
            if rec.get('write_date'):
                rec['write_date'] = str(rec['write_date'])[:10]

        # Keep newest first within groups, then force Subject resources to top.
        subject_resources.sort(key=lambda rec: rec.get('write_date') or '', reverse=True)
        subject_resources.sort(
            key=lambda rec: not (
                rec.get('type_id')
                and len(rec['type_id']) > 1
                and rec['type_id'][1] == 'Subject'
            )
        )

        favourite_domain = [
            ('favourite_user_ids', 'in', [self.env.uid]),
        ]
        if category_id:
            favourite_domain.append(
                ('subjects.category_id', '=', category_id)
            )
        favourite_resources = self.env['aps.resources'].search_read(
            favourite_domain,
            ['id', 'display_name', 'subject_icons'],
            order='display_name',
        )

        # ------------------------------------------------------------------ #
        # Section 4 – Assigned Resources
        # ------------------------------------------------------------------ #
        task_domain = []
        if start_date:
            task_domain.append(('date_assigned', '>=', str(start_date)))
        if category_id:
            subjects_in_cat = self.env['aps.subject'].search(
                [('category_id', '=', category_id)]
            )
            if subjects_in_cat:
                task_domain.append(
                    ('resource_id.subjects', 'in', subjects_in_cat.ids)
                )
            else:
                task_domain.append(('id', '=', False))
        if student_id:
            task_domain.append(('student_id', '=', student_id))
        if class_id:
            task_domain.append(('student_id', 'in', class_partner_ids))

        tasks = self.env['aps.resource.task'].search(
            task_domain, order='date_assigned desc'
        )

        # ------------------------------------------------------------------ #
        # Submission groups
        # ------------------------------------------------------------------ #
        submission_domain = [('submission_label', '!=', False)]
        if start_date:
            submission_domain.append(('date_assigned', '>=', str(start_date)))
        if category_id:
            subjects_in_cat = self.env['aps.subject'].search(
                [('category_id', '=', category_id)]
            )
            submission_domain.append(
                ('resource_id.subjects', 'in', subjects_in_cat.ids)
                if subjects_in_cat else ('id', '=', False)
            )
        if student_id:
            submission_domain.append(('task_id.student_id', '=', student_id))
        if class_id:
            submission_domain.append(
                ('task_id.student_id', 'in', class_partner_ids)
            )
        submissions = self.env['aps.resource.submission'].search(
            submission_domain, order='date_assigned desc, id'
        )
        groups_by_key = {}
        resource_groups = {}
        for submission in submissions:
            resource = submission.resource_id
            label = submission.submission_label or ''
            key = (label, resource.id)
            if key not in groups_by_key:
                groups_by_key[key] = {
                    'key': f'{resource.id}:{label}',
                    'label': label,
                    'resource_id': resource.id,
                    'resource_sequence': resource.sequence or 0,
                    'parent_resource_id': resource.primary_parent_id.id or False,
                    'parent_resource_ids': resource.parent_ids.ids,
                    'title': (
                        re.sub(
                            r'\s+\(\d{4}-\d{2}-\d{2}\)$',
                            '',
                            submission.display_name or label,
                        )
                    ),
                    'resource_name': resource.display_name or resource.name or '',
                    'description': resource.description or '',
                    'type_id': (
                        [resource.type_id.id, resource.type_id.display_name]
                        if resource.type_id else [0, 'Uncategorised']
                    ),
                    'type_icon': (
                        submission.type_icon
                        or (resource.type_icon if resource else False)
                    ),
                    'date_assigned': str(submission.date_assigned or ''),
                    'date_due': False,
                    'days_till_due': False,
                    'total': 0,
                    'assigned': 0,
                    'submitted': 0,
                    'finalised': 0,
                    'overdue': 0,
                    'out_of': 0,
                    'scores': [],
                    'submission_ids': [],
                    'assigned_ids': [],
                    'submitted_ids': [],
                    'finalised_ids': [],
                    'overdue_ids': [],
                    'scored_ids': [],
                }
                resource_groups.setdefault(resource.id, []).append(key)
            group = groups_by_key[key]
            group['total'] += 1
            group['out_of'] = max(group['out_of'], submission.out_of or 0)
            group['submission_ids'].append(submission.id)
            group['date_assigned'] = min(
                filter(None, [group['date_assigned'], str(submission.date_assigned or '')]),
                default='',
            )
            if submission.date_due and submission.date_due >= today:
                current_due_date = group['date_due']
                if not current_due_date or submission.date_due < fields.Date.from_string(
                    current_due_date
                ):
                    group['date_due'] = str(submission.date_due)
                    group['days_till_due'] = (submission.date_due - today).days
            if submission.state == 'assigned':
                if submission.due_status == 'late':
                    group['overdue'] += 1
                    group['overdue_ids'].append(submission.id)
                else:
                    group['assigned'] += 1
                    group['assigned_ids'].append(submission.id)
            elif submission.state == 'submitted':
                group['submitted'] += 1
                group['submitted_ids'].append(submission.id)
            elif submission.state == 'complete':
                group['finalised'] += 1
                group['finalised_ids'].append(submission.id)
            if submission.score != -0.01 and submission.result_percent is not False:
                group['scores'].append(submission.result_percent)
                group['scored_ids'].append(submission.id)

        submission_groups = []
        for key, group in groups_by_key.items():
            child_groups = [
                groups_by_key[child_key]
                for child in self.env['aps.resources'].browse(group['resource_id']).child_ids
                for child_key in resource_groups.get(child.id, [])
            ]
            descendant_groups = [
                groups_by_key[child_key]
                for descendant in self.browse(group['resource_id'])._get_all_descendants()
                for child_key in resource_groups.get(descendant.id, [])
            ]
            child_count = sum(child['total'] for child in descendant_groups)
            parent_ids = list(dict.fromkeys(
                ([group['parent_resource_id']] if group['parent_resource_id'] else [])
                + group['parent_resource_ids']
            ))
            parent_candidates = [
                groups_by_key[parent_key]
                for parent_id in parent_ids
                for parent_key in resource_groups.get(parent_id, [])
            ]
            same_label_candidates = [
                parent for parent in parent_candidates
                if parent['label'] == group['label']
            ]
            primary_parent_candidates = resource_groups.get(
                group['parent_resource_id'], []
            )
            parent_group = False
            if same_label_candidates:
                parent_group = same_label_candidates[0]
            elif len(primary_parent_candidates) == 1:
                parent_group = groups_by_key[primary_parent_candidates[0]]
            elif len(parent_candidates) == 1:
                parent_group = parent_candidates[0]
            group['parent_key'] = parent_group and parent_group['key']
            group['child_count'] = child_count
            group['child_resource_count'] = len(child_groups)
            group['child_submission_ids'] = [
                submission_id
                for child in descendant_groups
                for submission_id in child['submission_ids']
            ]
            for state_name, state_key in [
                ('assigned', 'assigned'),
                ('submitted', 'submitted'),
                ('finalised', 'finalised'),
                ('overdue', 'overdue'),
            ]:
                group[f'child_{state_name}_count'] = sum(
                    child[state_key] for child in descendant_groups
                )
                group[f'child_{state_name}_ids'] = [
                    submission_id
                    for child in descendant_groups
                    for submission_id in child[f'{state_key}_ids']
                ]
            group['avg_score'] = (
                round(sum(group['scores']) / len(group['scores']))
                if group['scores'] else False
            )
            del group['scores']
            submission_groups.append(group)

        group_titles = {group['key']: group['title'] for group in submission_groups}
        for group in submission_groups:
            parent_title = group_titles.get(group['parent_key'])
            if parent_title and group['title'].startswith(parent_title):
                group['title'] = group['title'][len(parent_title):].lstrip(
                    ' \t🢒/:-'
                ) or group['title']

        resource_stats = {}
        for task in tasks:
            rid = task.resource_id.id
            if rid not in resource_stats:
                resource_stats[rid] = {
                    'id': rid,
                    'name': task.resource_id.name or '',
                    'type_id': (
                        [
                            task.resource_id.type_id.id,
                            task.resource_id.type_id.display_name,
                        ]
                        if task.resource_id.type_id else [0, 'Uncategorised']
                    ),
                    'type_icon': task.type_icon or task.resource_id.type_icon,
                    'oldest_date_assigned': task.date_assigned,
                    'most_recent_date_assigned': task.date_assigned,
                    'total_submissions': 0,
                    'overdue_count': 0,
                    'scores': [],
                }
            stats = resource_stats[rid]
            if task.date_assigned:
                if (
                    not stats['oldest_date_assigned']
                    or task.date_assigned < stats['oldest_date_assigned']
                ):
                    stats['oldest_date_assigned'] = task.date_assigned
                if (
                    not stats['most_recent_date_assigned']
                    or task.date_assigned > stats['most_recent_date_assigned']
                ):
                    stats['most_recent_date_assigned'] = task.date_assigned
            stats['total_submissions'] += task.submission_count
            if task.state == 'overdue':
                stats['overdue_count'] += 1
            if task.avg_result is not None and task.avg_result >= 0:
                stats['scores'].append(task.avg_result)

        task_resources = []
        for stats in resource_stats.values():
            avg_score = (
                round(sum(stats['scores']) / len(stats['scores']))
                if stats['scores']
                else 0
            )
            task_resources.append({
                'id': stats['id'],
                'name': stats['name'],
                'type_id': stats['type_id'],
                'type_icon': stats['type_icon'],
                'oldest_date_assigned': (
                    str(stats['oldest_date_assigned'])
                    if stats['oldest_date_assigned']
                    else ''
                ),
                'most_recent_date_assigned': (
                    str(stats['most_recent_date_assigned'])
                    if stats['most_recent_date_assigned']
                    else ''
                ),
                'total_submissions': stats['total_submissions'],
                'overdue_count': stats['overdue_count'],
                'avg_score': avg_score,
            })

        task_resources.sort(
            key=lambda x: x['most_recent_date_assigned'] or '', reverse=True
        )

        return {
            'categories': categories,
            'students': students,
            'classes': classes,
            'selected_class_id': class_id,
            'selected_student_id': student_id,
            'dashboard_metrics': dashboard_metrics,
            'subject_resources': subject_resources,
            'favourite_resources': favourite_resources,
            'task_resources': task_resources,
            'submission_groups': submission_groups,
        }

    @api.model
    def get_dashboard_submissions_for_resource(
        self, resource_id, days=30, student_id=False, class_id=False
    ):
        """Return individual submissions for the given resource within the period.

        Args:
            resource_id: ID of the aps.resources record to query
            days: Number of days for the date range (default: 30), or -1 for All Time
        """
        today = fields.Date.today()
        start_date = (today - timedelta(days=days)) if days != -1 else False

        domain = [('resource_id', '=', resource_id)]
        if student_id:
            domain.append(('task_id.student_id', '=', student_id))
        if class_id:
            partner_ids = self.env['aps.student.class'].search([
                ('class_id', '=', class_id),
                ('state', '=', 'enrolled'),
            ]).mapped('student_id.partner_id').ids
            domain.append(('task_id.student_id', 'in', partner_ids))
        if start_date:
            domain.append(('date_assigned', '>=', str(start_date)))

        submissions = self.env['aps.resource.submission'].search_read(
            domain,
            [
                'id',
                'display_name',
                'type_icon',
                'student_id',
                'state',
                'date_assigned',
                'date_due',
                'result_percent',
                'out_of',
                'date_submitted',
                'due_status',
            ],
            order='date_assigned desc',
        )

        for sub in submissions:
            for key in ['date_assigned', 'date_due', 'date_submitted']:
                if sub[key]:
                    sub[key] = str(sub[key])

        # Sort for dashboard display: Date Assigned (DESC), Student (ASC)
        submissions.sort(
            key=lambda sub: (sub.get('student_id') and sub['student_id'][1] or '').lower()
        )
        submissions.sort(key=lambda sub: sub.get('date_assigned') or '', reverse=True)

        return submissions
