import re
import logging
from datetime import datetime, timedelta
from odoo import models, api, fields

_logger = logging.getLogger(__name__)


class APSResource(models.Model):
    _inherit = 'aps.resources'

    def action_force_update_display_names(self):
        """Force recompute display names for all resources in hierarchical order."""
        all_resources = self.search([])
        updated = self.env['aps.resources']

        # Start with resources that have no parents (root level)
        to_process = all_resources.filtered(lambda r: not r.parent_ids)

        # Process in layers: update current layer, then find children of updated resources
        iteration = 0
        max_iterations = 100  # Safety limit to prevent infinite loops

        while to_process and iteration < max_iterations:
            # Update display names for current layer
            to_process._compute_display_name()
            updated |= to_process

            # Find next layer: resources whose parents are all in the updated set
            remaining = all_resources - updated
            next_layer = self.env['aps.resources']

            for resource in remaining:
                # Check if all parents of this resource have been updated
                if all(parent in updated for parent in resource.parent_ids):
                    next_layer |= resource

            to_process = next_layer
            iteration += 1

        # Handle any remaining resources (shouldn't happen unless there are cycles)
        remaining = all_resources - updated
        if remaining:
            remaining._compute_display_name()
            updated |= remaining

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Updated display names for {len(updated)} resources in {iteration} layers.',
                'sticky': False,
            }
        }

    def get_pace_dates(self):
        """
        Parse PACE start_date, end_date, redline_start_date, and redline_end_date
        from the notes field.

        Note: Since resource.subjects is a Many2many field, one resource can be associated
        with multiple subjects. The PACE dates parsed from this resource's notes field
        apply to ALL subjects linked to this resource.

        Expected format in notes:
            start_date: 1/Aug/2025
            end_date: 31/Dec/2027
            redline_start_date: 1/Nov/2025
            redline_end_date: 30/Jan/2027

        Returns dict with date objects or False for each key if not found.
        """
        self.ensure_one()

        result = {
            'start_date': False,
            'end_date': False,
            'redline_start_date': False,
            'redline_end_date': False,
        }

        if not self.notes:
            return result

        # Remove HTML tags to get plain text
        plain_text = re.sub(r'<[^>]+>', '', self.notes)

        # Pattern to match dates in format: day/month/year where month can be short name or full name
        # Examples: 1/Aug/2025, 31/December/2027, 15/Jan/2026
        date_pattern = r'(\d{1,2})/([A-Za-z]+)/(\d{4})'

        def _parse_date_match(match):
            """Parse a regex match containing (day, month_str, year) groups into a date."""
            try:
                day, month_str, year = match.groups()
                date_str = f"{day} {month_str} {year}"
                for fmt in ['%d %B %Y', '%d %b %Y']:
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except ValueError:
                        continue
            except (ValueError, AttributeError):
                pass
            return False

        # Search for start_date (negative lookbehind prevents matching 'redline_start_date:')
        start_match = re.search(rf'(?<!redline_)start_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if start_match:
            result['start_date'] = _parse_date_match(start_match) or False

        # Search for end_date (negative lookbehind prevents matching 'redline_end_date:')
        end_match = re.search(rf'(?<!redline_)end_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if end_match:
            result['end_date'] = _parse_date_match(end_match) or False

        # Search for redline_start_date
        redline_start_match = re.search(rf'redline_start_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if redline_start_match:
            result['redline_start_date'] = _parse_date_match(redline_start_match) or False

        # Search for redline_end_date
        redline_end_match = re.search(rf'redline_end_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if redline_end_match:
            result['redline_end_date'] = _parse_date_match(redline_end_match) or False

        return result

    def action_assign_students(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assign Students to Resource',
            'res_model': 'aps.assign.students.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_resource_id': self.id},
        }

    def action_open_all_submissions(self):
        """Open all submissions associated with this resource regardless of state."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aps_sis.action_aps_resource_submissions')
        action['name'] = f'Submissions: {self.name}'
        action['domain'] = [('resource_id', '=', self.id)]
        action['context'] = {}
        return action

    def action_open_recent_submissions(self):
        """Open submissions for this resource that are in 'submitted' state and submitted in the last 7 days."""
        self.ensure_one()
        seven_days_ago = fields.Date.today() - timedelta(days=7)
        action = self.env['ir.actions.act_window']._for_xml_id('aps_sis.action_aps_resource_submissions')
        action['name'] = f'Recent Submissions: {self.name}'
        action['domain'] = [
            ('resource_id', '=', self.id),
            ('state', '=', 'submitted'),
            ('date_submitted', '>=', str(seven_days_ago)),
        ]
        action['context'] = {}
        return action

    def action_open_child_resources_list(self):
        """Open child resources in a standard list/form view with navigation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Linked Resources: {self.name}',
            'res_model': 'aps.resources',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.child_ids.ids)],
            'context': {'default_parent_ids': [(6, 0, [self.id])], 'default_primary_parent_id': self.id, 'default_subjects': self.subjects.ids},
            'target': 'current',
        }

    def action_open_supporting_resources_list(self):
        """Open supporting resources in a standard list/form view with navigation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Supporting Resources: {self.name}',
            'res_model': 'aps.resources',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.supporting_resource_ids.ids)],
            'context': {'default_subjects': self.subjects.ids},
            'target': 'current',
        }

    def action_delete(self):
        """Called by the form button to delete the record and close the form."""
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

    def get_resource_tree(self):
        """Return the full resource hierarchy for the Tree View tab.

        Returns a dict with:
          - ancestors: list of dicts from root down to (but not including) this resource
          - current:   dict for this resource
          - children:  recursive list of child dicts

        Each node dict has: id, name, type_id, type_name, connection_type.
        ``connection_type`` is ``'linked'`` for mark-contributing children or
        ``'supporting'`` for supplementary children (rendered in italics in the
        UI).  Linked children are always listed before supporting children.
        """
        self.ensure_one()

        def _node(resource, connection_type='linked'):
            return {
                'id': resource.id,
                'name': resource.name or '',
                'type_id': resource.type_id.id if resource.type_id else False,
                'type_name': resource.type_id.name if resource.type_id else '',
                'connection_type': connection_type,
            }

        # Build the ancestor chain (single path upward, no cycles)
        ancestors = []
        current = self
        visited_up = {self.id}
        while True:
            parent = current.primary_parent_id
            if not parent:
                remaining = current.parent_ids.filtered(lambda p: p.id not in visited_up)
                parent = remaining.sorted(key=lambda p: (p.sequence or 0, p.id))[:1] if remaining else None
            if not parent or parent.id in visited_up:
                break
            visited_up.add(parent.id)
            ancestors.insert(0, _node(parent))
            current = parent

        # Build the descendant tree (depth-first, cycle-safe)
        def _build_children(resource, visited):
            result = []
            # Linked resources first (mark-contributing)
            for child in resource.child_ids.sorted(key=lambda r: (r.sequence or 0, r.id)):
                if child.id in visited:
                    continue
                visited.add(child.id)
                node = _node(child, 'linked')
                node['children'] = _build_children(child, visited)
                result.append(node)
            # Supporting resources second (shown in italics)
            for child in resource.supporting_resource_ids.sorted(key=lambda r: (r.sequence or 0, r.id)):
                if child.id in visited:
                    continue
                visited.add(child.id)
                node = _node(child, 'supporting')
                node['children'] = _build_children(child, visited)
                result.append(node)
            return result

        current_node = _node(self)
        current_node['children'] = _build_children(self, {self.id})

        return {
            'ancestors': ancestors,
            'current': current_node,
        }

    @api.model
    def run_auto_assign(self):
        """Cron-called method: process all resources that have auto_assign=True and whose
        auto_assign_date is today or in the past."""
        today = fields.Date.today()
        resources = self.search([
            ('auto_assign', '=', True),
            ('auto_assign_date', '<=', today),
        ])
        for resource in resources:
            try:
                resource._do_auto_assign(today)
            except Exception as exc:
                _logger.exception('Auto-assign failed for resource %s (%s): %s', resource.id, resource.display_name, exc)

    def _do_auto_assign(self, today):
        """Perform one auto-assignment run for this resource."""
        self.ensure_one()

        # Respect end date
        if self.auto_assign_end_date and today > self.auto_assign_end_date:
            _logger.info('Auto-assign skipped for resource %s: past end date', self.display_name)
            return

        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']

        # Determine students to assign
        if self.auto_assign_all_students:
            if self.subjects:
                students_recs = self.env['op.student'].search([
                    ('course_detail_ids.state', '=', 'running'),
                    ('course_detail_ids.subject_ids', 'in', self.subjects.ids),
                ])
                student_partners = students_recs.mapped('partner_id')
            else:
                student_partners = self.env['res.partner']
        else:
            student_partners = self.auto_assign_student_ids

        if not student_partners:
            _logger.info('Auto-assign skipped for resource %s: no students found', self.display_name)
            return

        # Build submission name
        base_name = self.auto_assign_custom_name or self.display_name or self.name or ''
        submission_name = f'{base_name}'
        submission_label = f'{submission_name} ({today})'

        # Date/time for submissions
        assign_date = today
        assign_time = self.auto_assign_time or 0.0
        date_due = assign_date + self._default_assignment_duration()

        # Collect resources to assign (this resource + all descendants, using wizard logic)
        all_descendants = self._get_all_descendants()
        resources_to_assign = self | all_descendants
        top_level = self
        separator = ' 🢒 '

        assigned_count = 0
        for resource in resources_to_assign:
            # Compute submission name for this resource
            if resource.id == top_level.id:
                res_submission_name = submission_name
            else:
                child_name = resource.name or resource.display_name or ''
                res_submission_name = submission_name + separator + child_name

            # Question handling
            has_question = resource.has_question
            if has_question == 'no':
                use_question = False
            elif has_question == 'yes':
                use_question = resource.question or False
            elif has_question == 'use_parent':
                use_question = (resource.primary_parent_id.question if resource.primary_parent_id else False) or False
            else:
                use_question = False

            for student in student_partners:
                # Determine subjects for this student
                if len(self.subjects) < 2:
                    assigned_subjects = self.subjects
                else:
                    student_record = self.env['op.student'].search([('partner_id', '=', student.id)], limit=1)
                    if student_record:
                        running_courses = student_record.course_detail_ids.filtered(lambda c: c.state == 'running')
                        student_subjects = running_courses.mapped('subject_ids')
                        assigned_subjects = self.subjects & student_subjects
                    else:
                        assigned_subjects = self.subjects

                # Ensure task exists
                task = task_model.search([
                    ('resource_id', '=', resource.id),
                    ('student_id', '=', student.id),
                ], limit=1)
                if not task:
                    task = task_model.create({
                        'resource_id': resource.id,
                        'student_id': student.id,
                        'state': 'assigned',
                        'date_due': date_due,
                    })

                submission_model.create({
                    'task_id': task.id,
                    'submission_label': submission_label,
                    'submission_name': res_submission_name,
                    'date_assigned': assign_date,
                    'time_assigned': assign_time,
                    'date_due': date_due,
                    'allow_subject_editing': self.allow_subject_editing,
                    'state': 'assigned',
                    'question': use_question,
                    'has_question': has_question,
                    'subjects': assigned_subjects.ids,
                    'points_scale': self.points_scale,
                    'notification_state': 'not_sent' if self.auto_assign_notify_student else 'skipped',
                })
                assigned_count += 1

        # Advance next assign date
        frequency = self.auto_assign_frequency or 7
        next_date = assign_date + timedelta(days=frequency)

        # Append to log
        log_entry = (
            f'[{datetime.now().strftime("%Y-%m-%d %H:%M")}] '
            f'Assigned "{submission_name}": created {assigned_count} submission(s) '
            f'for {len(student_partners)} student(s) across {len(resources_to_assign)} resource(s). '
            f'Next run: {next_date}.'
        )
        existing_log = self.auto_assign_log or ''
        self.write({
            'auto_assign_date': next_date,
            'auto_assign_log': f'{log_entry}\n{existing_log}'.strip(),
        })
