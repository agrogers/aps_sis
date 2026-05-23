from datetime import timedelta
from odoo import models, fields, api


class APSResource(models.Model):
    _inherit = 'aps.resources'

    @api.model
    def get_teacher_dashboard_data(self, category_id=False, days=30):
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
            subjects_in_cat = self.env['op.subject'].search(
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

        # ------------------------------------------------------------------ #
        # Section 4 – Assigned Resources
        # ------------------------------------------------------------------ #
        task_domain = []
        if start_date:
            task_domain.append(('date_assigned', '>=', str(start_date)))
        if category_id:
            subjects_in_cat = self.env['op.subject'].search(
                [('category_id', '=', category_id)]
            )
            if subjects_in_cat:
                task_domain.append(
                    ('resource_id.subjects', 'in', subjects_in_cat.ids)
                )
            else:
                task_domain.append(('id', '=', False))

        tasks = self.env['aps.resource.task'].search(
            task_domain, order='date_assigned desc'
        )

        resource_stats = {}
        for task in tasks:
            rid = task.resource_id.id
            if rid not in resource_stats:
                resource_stats[rid] = {
                    'id': rid,
                    'name': task.resource_id.name or '',
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
            'subject_resources': subject_resources,
            'task_resources': task_resources,
        }

    @api.model
    def get_dashboard_submissions_for_resource(self, resource_id, days=30):
        """Return individual submissions for the given resource within the period.

        Args:
            resource_id: ID of the aps.resources record to query
            days: Number of days for the date range (default: 30), or -1 for All Time
        """
        today = fields.Date.today()
        start_date = (today - timedelta(days=days)) if days != -1 else False

        domain = [('resource_id', '=', resource_id)]
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
