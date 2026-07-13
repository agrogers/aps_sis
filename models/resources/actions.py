import re
import logging
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from markupsafe import Markup
from odoo import _, models, api, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSResource(models.Model):
    _inherit = 'aps.resources'

    def get_formview_action(self, access_uid=None):
        """Always open aps.resources records using the APEX action so the URL
        uses the 'apex-resources' path segment and the APEX menu stays highlighted,
        regardless of which app context the record was opened from."""
        action = self.env.ref('aps_sis.action_aps_resources').sudo().read()[0]
        action.update({
            'res_id': self.id,
            'views': [(False, 'form')],
        })
        return action

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

        result: dict[str, date | bool] = {
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

    # ------------------------------------------------------------------
    # Open parent/grandparent source record in a popup dialog
    # ------------------------------------------------------------------

    def _get_field_source_record(self, field_name):
        """Walk up the primary_parent_id chain to find the record that actually
        owns the given field's content (i.e. has something other than
        'use_parent' for the corresponding has_* selection).

        Returns the source record, or False if none can be resolved.
        """
        self.ensure_one()
        has_field_map = {
            'question': 'has_question',
            'answer': 'has_answer',
            'notes': 'has_notes',
        }
        has_field = has_field_map.get(field_name)
        if not has_field:
            return self.primary_parent_id or False

        current = self.primary_parent_id
        visited = {self.id}
        while current:
            if current.id in visited:
                # Cycle detected – stop traversal
                break
            visited.add(current.id)
            if getattr(current, has_field, None) != 'use_parent':
                return current
            current = current.primary_parent_id
        return False

    def _action_open_field_source_popup(self, field_name, label):
        """Build and return a dialog action for editing the source record of
        the given inherited field.
        """
        self.ensure_one()
        source = self._get_field_source_record(field_name)
        if not source:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Parent Found',
                    'message': f'Could not locate the parent record that provides the {label}.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': f'Edit Parent: {source.display_name}',
            'res_model': 'aps.resources',
            'res_id': source.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_parent_notes_popup(self):
        return self._action_open_field_source_popup('notes', 'Notes')

    @api.model
    def get_notes_popup_action(self, resource_id):
        """Return an act_window action dict to open the notes popup for a resource.
        Uses sudo for the view lookup so students without ir.ui.view access can call this."""
        view = self.env['ir.model.data'].sudo()._xmlid_to_res_id(
            'aps_sis.view_aps_resource_notes_popup', raise_if_not_found=False
        )
        view_id = view or False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resource Notes',
            'res_model': 'aps.resources',
            'res_id': resource_id,
            'view_mode': 'form',
            'views': [[view_id, 'form']],
            'target': 'new',
        }

    def action_open_parent_question_popup(self):
        return self._action_open_field_source_popup('question', 'Question')

    def action_open_parent_answer_popup(self):
        return self._action_open_field_source_popup('answer', 'Answer')

    @staticmethod
    def _extract_top_headings_from_html(html_content):
        """Return a list of text strings for every heading at the top-most
        heading level present in *html_content*.

        E.g. if the HTML contains H2 and H3 tags but no H1, only the H2
        texts are returned (in document order).
        """
        class _HeadingCollector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.headings = []          # list of (level, text)
                self._in_heading = False
                self._current_level = None
                self._current_text = []

            def handle_starttag(self, tag, attrs):
                if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    self._in_heading = True
                    self._current_level = int(tag[1])
                    self._current_text = []

            def handle_endtag(self, tag):
                if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    text = ''.join(self._current_text).strip()
                    if text:
                        self.headings.append((self._current_level, text))
                    self._in_heading = False
                    self._current_level = None
                    self._current_text = []

            def handle_data(self, data):
                if self._in_heading:
                    self._current_text.append(data)

        collector = _HeadingCollector()
        collector.feed(html_content)

        if not collector.headings:
            return []

        top_level = min(level for level, _ in collector.headings)
        return [text for level, text in collector.headings if level == top_level]

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

    def action_get_or_create_submission(self):
        """Return an action opening the most recent submission for the current
        student on this resource.  If no submission exists, create a task and
        submission first (no due date)."""
        self.ensure_one()
        student = self.env.user.partner_id

        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']

        # Find existing task for this resource + student
        task = task_model.search([
            ('resource_id', '=', self.id),
            ('student_id', '=', student.id),
        ], limit=1)

        submission = False
        if task:
            # Most recent submission
            submission = submission_model.search([
                ('task_id', '=', task.id),
            ], order='id desc', limit=1)

        if not submission:
            # Create task if missing
            if not task:
                task = task_model.create({
                    'resource_id': self.id,
                    'student_id': student.id,
                    'state': 'assigned',
                })
            # Create a minimal submission with no due date
            submission = submission_model.create({
                'task_id': task.id,
                'submission_name': self.display_name or self.name or '',
                'date_assigned': fields.Date.today(),
                'state': 'assigned',
                'question': self.question if self.has_question == 'yes' else False,
                'has_question': self.has_question,
                'points_scale': self.points_scale,
                'subjects': self.subjects.ids,
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aps.resource.submission',
            'res_id': submission.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_ai_test_mark(self):
        """Start a background AI run for the resource test prompt."""
        self.ensure_one()
        if self.ai_action == 'none':
            raise UserError(_('AI Action must not be "None" to use the test prompt.'))

        active_run = self.env['aps.ai.run'].sudo().search([
            ('resource_id', '=', self.id),
            ('state', 'in', ('queued', 'running')),
        ], limit=1, order='create_date desc, id desc')
        if active_run:
            return self._build_ai_run_notification(
                active_run,
                _('AI Marking In Progress'),
                _('AI marking is already running in the background for this resource.'),
            )

        run = self.env['aps.ai.run'].sudo().create({
            'resource_id': self.id,
            'requested_by_id': self.env.user.id,
            'state': 'queued',
            'status_message': _('Queued and waiting to start...'),
            'request_origin': 'manual',
        })
        run._queue_background_processing()
        return self._build_ai_run_notification(
            run,
            _('AI Marking Started'),
            _('AI marking is running in the background. You can close the progress dialog at any time.'),
        )

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
                safe_name = resource.display_name.encode('ascii', errors='replace').decode('ascii')
                _logger.exception('Auto-assign failed for resource %s (%s): %s', resource.id, safe_name, exc)

    def _do_auto_assign(self, today):
        """Perform one auto-assignment run for this resource."""
        self.ensure_one()

        # Respect end date
        if self.auto_assign_end_date and today > self.auto_assign_end_date:
            safe_name = self.display_name.encode('ascii', errors='replace').decode('ascii')
            _logger.info('Auto-assign skipped for resource %s (id=%s): past end date', safe_name, self.id)
            return

        task_model = self.env['aps.resource.task']
        submission_model = self.env['aps.resource.submission']

        # Determine students to assign
        if self.auto_assign_all_students:
            if self.subjects:
                students_recs = self.env['aps.student'].search([])
                enrollments = self.env['aps.student.class'].search([
                    ('state', '=', 'enrolled'),
                    ('home_class_id.subject_id', 'in', self.subjects.ids),
                ])
                student_partners = enrollments.mapped('student_id.partner_id')
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
        date_due = assign_date + timedelta(days=self.auto_assign_due_days or 6)

        # Collect resources to assign (this resource + all descendants, using wizard logic)
        all_descendants = self._get_all_descendants()
        resources_to_assign = self | all_descendants
        top_level = self

        # Resolve submission names using custom-name-aware helper
        name_map = resources_to_assign._resolve_submission_names(top_level, top_level_name=submission_name)

        assigned_count = 0
        for resource in resources_to_assign:
            # Compute submission name for this resource
            res_submission_name = name_map.get(resource.id, submission_name)

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
                    student_record = self.env['aps.student'].search([('partner_id', '=', student.id)], limit=1)
                    if student_record:
                        student_subjects = student_record.enrollment_ids.filtered(
                            lambda e: e.state == 'enrolled'
                        ).mapped('home_class_id.subject_id')
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

    # ------------------------------------------------------------------
    # Resource Hierarchy client-action data
    # ------------------------------------------------------------------
    @api.model
    def get_hierarchy_data(self, subject_id=False):
        """Return the full resource hierarchy for the client-action view.

        Starting from resources with ``show_in_hierarchy=True``, walk down the
        child_ids tree collecting connected resources also flagged for the
        hierarchy.

        Args:
            subject_id: optional ``op.subject`` id to restrict to one subject.

        Returns a list of subject-root dicts, each containing BFS levels.
        """
        # 1. Determine subjects to display
        if subject_id:
            subjects = self.env['aps.subject'].browse(subject_id).exists()
        else:
            subjects = self.env['aps.subject'].search([], order='name')

        # 2. Find all hierarchy-eligible resources, prefetch children
        all_resources = self.search([('show_in_hierarchy', '=', True)])
        all_resources.mapped('child_ids')

        result = []
        for subject in subjects:
            subject_resources = all_resources.filtered(
                lambda r, s=subject: s in r.subjects
            )
            if not subject_resources:
                continue

            # Root = those whose parents are NOT in the subject set
            root_resources = subject_resources.filtered(
                lambda r, sr=subject_resources: not (r.parent_ids & sr)
            )
            if not root_resources:
                continue

            # BFS level-by-level
            levels = []
            current_level = root_resources.sorted(key=lambda r: (r.sequence or 0, r.name or ''))
            visited = set(current_level.ids)

            while current_level:
                level_data = []
                next_level = self.env['aps.resources']
                for res in current_level:
                    level_data.append({
                        'id': res.id,
                        'name': res.name or '',
                        'type_name': res.type_id.name if res.type_id else '',
                        'type_color': res.type_id.color if res.type_id else '',
                        'parent_ids': (res.parent_ids & subject_resources).ids,
                        'subject_ids': res.subjects.ids,
                    })
                    children = (res.child_ids & subject_resources).filtered(
                        lambda c: c.id not in visited
                    )
                    for child in children:
                        visited.add(child.id)
                    next_level |= children
                if level_data:
                    levels.append(level_data)
                current_level = next_level.sorted(
                    key=lambda r: (r.sequence or 0, r.name or '')
                )

            if levels:
                result.append({
                    'subject_id': subject.id,
                    'subject_name': subject.name or '',
                    'levels': levels,
                })

        return result

    @api.model
    def get_hierarchy_subjects(self):
        """Return subjects that have at least one hierarchy-visible resource."""
        resources = self.search([('show_in_hierarchy', '=', True)])
        subjects = resources.mapped('subjects')
        return [
            {
                'id': s.id,
                'name': s.name,
                'color': (s.category_id.color_rgb or '') if s.category_id else '',
                'icon_url': ('/web/image/aps.subject/%d/icon' % s.id) if s.icon
                    else ('/web/image/aps.subject.category/%d/icon' % s.category_id.id) if s.category_id and s.category_id.icon
                    else '',
            }
            for s in subjects.sorted('name')
        ]

    @api.model
    def get_hierarchy_table_data(self, subject_id=False, category_id=False):
        """Return hierarchy data structured for HTML table rendering.

        Each subject group includes a tree with computed *colspan* values
        and the overall *max_depth* so the JS client can build rows of
        ``<td>`` elements with proper ``colspan`` / ``rowspan``.

        Args:
            subject_id: filter to a single subject (takes precedence).
            category_id: filter to all subjects in this category.
        """
        if subject_id:
            subjects = self.env['aps.subject'].browse(subject_id).exists()
        elif category_id:
            subjects = self.env['aps.subject'].search(
                [('category_id', '=', category_id)], order='name',
            )
        else:
            subjects = self.env['aps.subject'].search([], order='name')

        all_resources = self.search([('show_in_hierarchy', '=', True)])
        all_resources.mapped('child_ids')  # prefetch
        all_resources.mapped('tag_ids')    # prefetch
        all_resources.mapped('supporting_resources_buttons')  # prefetch

        def _build_node(resource, subject_resources, visited):
            children = (
                (resource.child_ids & subject_resources)
                .filtered(lambda c: c.id not in visited)
                .sorted(key=lambda r: (r.sequence or 0, r.name or ''))
            )
            child_nodes = []
            for child in children:
                visited.add(child.id)
                child_nodes.append(_build_node(child, subject_resources, visited))
            colspan = sum(c['colspan'] for c in child_nodes) if child_nodes else 1
            return {
                'id': resource.id,
                'name': resource.name or '',
                'children': child_nodes,
                'colspan': colspan,
                'has_children': bool(child_nodes),
                'tag_ids': resource.tag_ids.ids,
                'has_notes': resource.has_notes or 'no',
                'links': resource.supporting_resources_buttons or [],
            }

        def _tree_depth(nodes):
            """0 for leaves only, 1 if one level of children, etc."""
            if not nodes:
                return 0
            max_d = 0
            for n in nodes:
                if n['children']:
                    max_d = max(max_d, 1 + _tree_depth(n['children']))
            return max_d

        result = []
        for subject in subjects:
            subject_resources = all_resources.filtered(
                lambda r, s=subject: s in r.subjects
            )
            if not subject_resources:
                continue
            root_resources = subject_resources.filtered(
                lambda r, sr=subject_resources: not (r.parent_ids & sr)
            ).sorted(key=lambda r: (r.sequence or 0, r.name or ''))
            if not root_resources:
                continue

            visited = set()
            root_nodes = []
            for root in root_resources:
                if root.id not in visited:
                    visited.add(root.id)
                    root_nodes.append(_build_node(root, subject_resources, visited))
            if not root_nodes:
                continue

            cat_color = ''
            if subject.category_id and subject.category_id.color_rgb:
                cat_color = subject.category_id.color_rgb

            # Prefer subject icon, fall back to category icon.
            # Return the /web/image URL so the browser loads it directly.
            if subject.icon:
                icon_url = '/web/image/aps.subject/%d/icon' % subject.id
            elif subject.category_id and subject.category_id.icon:
                icon_url = '/web/image/aps.subject.category/%d/icon' % subject.category_id.id
            else:
                icon_url = False

            result.append({
                'subject_id': subject.id,
                'subject_name': subject.name or '',
                'color': cat_color,
                'icon_url': icon_url,
                'roots': root_nodes,
                'total_cols': sum(n['colspan'] for n in root_nodes),
                'max_depth': _tree_depth(root_nodes),
            })

        return result

    @api.model
    def get_hierarchy_tags(self):
        """Return resource tags marked for hierarchy display."""
        tags = self.env['aps.resource.tags'].search([
            ('use_in_hierarchy', '=', True),
        ], order='name')
        return [
            {
                'id': t.id,
                'name': t.name,
                'color_hex': t.color_hex or '',
                'color_applies_to_fill': t.color_applies_to_fill,
                'color_applies_to_border': t.color_applies_to_border,
            }
            for t in tags
        ]

    # ------------------------------------------------------------------
    # Course Explorer client-action data
    # ------------------------------------------------------------------

    @api.model
    def get_course_explorer_subject_categories(self):
        """Return subject categories that have at least one hierarchy-visible
        resource with notes (has_notes != 'no')."""
        resources = self.search([
            ('show_in_hierarchy', '=', True),
            ('has_notes', '!=', 'no'),
        ])
        categories = resources.mapped('subject_categories')
        return [
            {
                'id': c.id,
                'name': c.name or '',
                'resource_count': len(resources.filtered(
                    lambda r, cat=c: cat in r.subject_categories
                )),
            }
            for c in categories.sorted('name')
        ]

    @staticmethod
    def _add_lazy_loading(html):
        """Add loading="lazy" to all <img> tags that don't already have it."""
        if not html:
            return html
        # Match <img tags that don't already have loading= attribute
        return re.sub(
            r'(<img\b)(?![^>]*\bloading=)',
            r'\1 loading="lazy"',
            html,
        )

    def _resolve_notes(self):
        """Return the resource's own notes HTML, if it has any.

        Returns (resolved_notes_html, source_resource_id) or (False, False)
        if the resource has no notes (has_notes != 'yes').
        """
        self.ensure_one()
        html = self.notes or ''
        # NOTE: Lazy-loading and aspect-ratio injection are now applied in
        # the write()/create() overrides (overrides.py), so the HTML stored
        # in the database is already processed. No need to modify on read.
        # Old approach (removed):
        #   html = self._add_lazy_loading(html)
        #   html, changed = self._ensure_image_aspect_ratios(html)
        #   if changed:
        #       self.sudo().with_context(_skip_image_ratio_hook=True).write({'notes': html})
        return (Markup(html) if html else False), self.id

    @api.model
    def get_course_explorer_data(self, subject_category_id=False):
        """Return tree and content data for the course explorer view.

        Builds a recursive tree of resources with ``show_in_hierarchy=True``.
        Resources with notes (``has_notes != 'no'``) are included as content
        nodes.  Parent resources that have no notes of their own are still
        included in the tree when they are ancestors of resources that do
        have notes, so the hierarchy is always complete.

        Each content section resolves ``has_notes='use_parent'`` up the
        parent chain and deduplicates so identical inherited content is not
        rendered twice.

        Args:
            subject_category_id: optional ``aps.subject.category`` id.

        Returns:
            dict with keys ``tree`` (list of root node dicts) and
            ``contentSections`` (list of section dicts).
        """
        # Base domain: hierarchy-visible resources
        base_domain = [('show_in_hierarchy', '=', True)]
        if subject_category_id:
            base_domain.append(('subject_categories', 'in', subject_category_id))

        all_hier = self.search(base_domain)
        all_hier.mapped('child_ids')
        all_hier.mapped('parent_ids')
        all_hier.mapped('primary_parent_id')
        all_hier.mapped('subject_categories')

        # Resources that have notes (or use_parent)
        has_notes_res = all_hier.filtered(lambda r: r.has_notes != 'no')

        # Include ancestor resources that are parents of has_notes resources
        # but don't have notes themselves — they serve as structural nodes.
        extra_parents = self.env['aps.resources']
        for res in has_notes_res:
            for parent in res.parent_ids:
                if parent in all_hier and parent.has_notes == 'no':
                    extra_parents |= parent

        # All resources that appear in the tree
        all_resources = has_notes_res | extra_parents
        filtered_ids = set(all_resources.ids)

        # Identify parents whose notes are "suppressed" because they have
        # children that use_parent.  These parents get a heading-only
        # section (no HTML content).
        suppressed_parents = set()
        for res in all_resources:
            if res.has_notes == 'yes':
                children_use_parent = any(
                    c.has_notes == 'use_parent'
                    for c in (res.child_ids & all_resources)
                )
                if children_use_parent:
                    suppressed_parents.add(res.id)

        # Build sections_map:
        # - Parents with has_notes='yes' that are suppressed → heading-only
        # - Children with has_notes='use_parent' → resolved notes + heading
        # - Other has_notes='yes' resources → own notes + heading
        # - No deduplication: each child gets unique resolved content
        sections_map = {}

        for res in all_resources:
            if res.id in suppressed_parents:
                # Parent whose notes are suppressed: heading only, no HTML
                sections_map[res.id] = {
                    'id': res.id,
                    'name': res.name or '',
                    'html': '',
                    'visible': True,
                    'headingOnly': True,
                    'resolvedFrom': False,
                }
            else:
                notes_html, source_id = res._resolve_notes()
                if not notes_html:
                    continue
                sections_map[res.id] = {
                    'id': res.id,
                    'name': res.name or '',
                    'html': notes_html,
                    'visible': True,
                    'headingOnly': False,
                    'resolvedFrom': source_id if source_id != res.id else False,
                }

        # Determine root nodes: resources whose parents are NOT in
        # the filtered set (or have no parents at all).
        def _is_root(resource):
            if not resource.parent_ids:
                return True
            return not bool(resource.parent_ids & all_resources)

        root_resources = all_resources.filtered(_is_root).sorted(
            key=lambda r: (r.sequence or 0, r.name or '')
        )

        # Build recursive tree
        visited = set()

        def _build_node(resource, depth=0):
            if resource.id in visited:
                return None
            visited.add(resource.id)
            children = (resource.child_ids & all_resources).filtered(
                lambda c: c.id not in visited
            ).sorted(key=lambda r: (r.sequence or 0, r.name or ''))
            child_nodes = []
            for child in children:
                node = _build_node(child, depth + 1)
                if node:
                    child_nodes.append(node)
            return {
                'id': resource.id,
                'name': resource.name or '',
                'has_notes': resource.has_notes or 'no',
                'depth': depth,
                'has_children': bool(child_nodes),
                'children': child_nodes,
            }

        tree = []
        for root in root_resources:
            if root.id not in visited:
                node = _build_node(root)
                if node:
                    tree.append(node)

        # Compute sectionId for every tree node:
        # 1. Nodes with a visible section → own id
        # 2. Structural parents → nearest descendant's section id
        # 3. If no descendant has a section → nearest ancestor's section id
        #
        # Also compute highlightIds: set of all section IDs that would
        # "belong" to this node (self + all descendants). Used so that
        # when a child is active but hidden (parent collapsed), the
        # parent gets highlighted instead.
        def _assign_section_ids(nodes, ancestor_section_id=False, depth=0):
            for node in nodes:
                sec = sections_map.get(node['id'])
                if sec:
                    sec['depth'] = depth
                if sec and sec['visible']:
                    node['sectionId'] = node['id']
                    _assign_section_ids(
                        node.get('children', []),
                        ancestor_section_id=node['id'],
                        depth=depth + 1,
                    )
                else:
                    desc_id = _find_first_visible_section(
                        node.get('children', [])
                    )
                    node['sectionId'] = desc_id or ancestor_section_id or False
                    _assign_section_ids(
                        node.get('children', []),
                        ancestor_section_id=node['sectionId'] or ancestor_section_id,
                        depth=depth + 1,
                    )
                # Collect all section IDs that belong to this subtree
                node['highlightIds'] = set()
                if node.get('sectionId'):
                    node['highlightIds'].add(node['sectionId'])
                for child in node.get('children', []):
                    node['highlightIds'].update(child.get('highlightIds', set()))

        def _find_first_visible_section(nodes):
            for node in nodes:
                sec = sections_map.get(node['id'])
                if sec and sec['visible']:
                    return node['id']
                result = _find_first_visible_section(node.get('children', []))
                if result:
                    return result
            return False

        _assign_section_ids(tree)

        # Enrich each section with quiz-type child/supporting resources.
        # A quiz is any resource whose type has assessment=True.
        # Pre-fetch task data for the current student in a single query.
        student = self.env.user.partner_id
        quiz_resource_ids = set()
        for res in all_resources:
            for child in res.child_ids:
                if child.type_id and child.type_id.assessment:
                    quiz_resource_ids.add(child.id)
            for sup in res.supporting_resource_ids:
                if sup.type_id and sup.type_id.assessment:
                    quiz_resource_ids.add(sup.id)

        task_map = {}  # resource_id -> task record
        if quiz_resource_ids and student:
            tasks = self.env['aps.resource.task'].search([
                ('resource_id', 'in', list(quiz_resource_ids)),
                ('student_id', '=', student.id),
            ])
            for task in tasks:
                task_map[task.resource_id.id] = task

        for res in all_resources:
            sec = sections_map.get(res.id)
            if not sec:
                continue
            quizzes = []
            seen_quiz_ids = set()
            # Child resources that are quizzes
            for child in res.child_ids:
                if child.type_id and child.type_id.assessment and child.id not in seen_quiz_ids:
                    seen_quiz_ids.add(child.id)
                    task = task_map.get(child.id)
                    quizzes.append({
                        'id': child.id,
                        'name': child.name or '',
                        'typeName': child.type_id.name or '',
                        'weightedResult': task.weighted_result if task else 0,
                        'attempts': task.submission_count if task else 0,
                        'lastResult': task.last_result if task else 0,
                        'state': task.state if task else 'unassigned',
                    })
            # Supporting resources that are quizzes
            for sup in res.supporting_resource_ids:
                if sup.type_id and sup.type_id.assessment and sup.id not in seen_quiz_ids:
                    seen_quiz_ids.add(sup.id)
                    task = task_map.get(sup.id)
                    quizzes.append({
                        'id': sup.id,
                        'name': sup.name or '',
                        'typeName': sup.type_id.name or '',
                        'weightedResult': task.weighted_result if task else 0,
                        'attempts': task.submission_count if task else 0,
                        'lastResult': task.last_result if task else 0,
                        'state': task.state if task else 'unassigned',
                    })
            sec['quizzes'] = quizzes
            # Average weighted result across quizzes for this section
            wrs = [q['weightedResult'] for q in quizzes if q.get('weightedResult')]
            sec['avgWeightedResult'] = round(sum(wrs) / len(wrs), 1) if wrs else 0

        # Propagate avgWeightedResult, hasQuizzes and quiz submission
        # status to tree nodes.
        def _apply_avg_to_tree(nodes):
            for node in nodes:
                sec = sections_map.get(node['id'])
                if sec:
                    node['avgWeightedResult'] = sec.get('avgWeightedResult', 0)
                    node['hasQuizzes'] = bool(sec.get('quizzes'))
                    quizzes = sec.get('quizzes', [])
                    if quizzes:
                        node['allQuizzesSubmitted'] = all(
                            q.get('attempts', 0) > 0
                            for q in quizzes
                        )
                    else:
                        node['allQuizzesSubmitted'] = True
                else:
                    node['avgWeightedResult'] = 0
                    node['hasQuizzes'] = False
                    node['allQuizzesSubmitted'] = True
                _apply_avg_to_tree(node.get('children', []))
        _apply_avg_to_tree(tree)

        # Collect content sections in tree traversal order (depth-first).
        # Parents appear before their children, each level sorted by
        # (sequence, name) — matching the visual tree order exactly.
        ordered_sections = []
        seen_section_ids = set()

        def _collect_sections(nodes):
            for node in nodes:
                sec = sections_map.get(node['id'])
                if sec and sec['visible'] and sec['id'] not in seen_section_ids:
                    sec['depth'] = node.get('depth', 0)
                    ordered_sections.append(sec)
                    seen_section_ids.add(sec['id'])
                _collect_sections(node.get('children', []))

        _collect_sections(tree)

        return {
            'tree': tree,
            'contentSections': ordered_sections,
        }

    # ------------------------------------------------------------------
    # Course Explorer student progress tracking
    # ------------------------------------------------------------------

    def _compute_resource_progress(self, student_id):
        """Compute progress for a single resource for a given student.

        Returns a dict with:
          - progress: float 0-100
          - hasCheckbox: bool (True if this resource provided notes to the section)
          - submissionState: str or None
        """
        self.ensure_one()
        result = {
            'progress': 0.0,
            'hasCheckbox': False,
            'submissionState': None,
        }

        # Find the task for this resource and student, then get the submission.
        # We search via task because submission.student_id and
        # submission.resource_id are non-stored related fields, making direct
        # searches on them unreliable.
        task = self.env['aps.resource.task'].search([
            ('resource_id', '=', self.id),
            ('student_id', '=', student_id),
        ], limit=1)

        if task:
            submission = self.env['aps.resource.submission'].search([
                ('task_id', '=', task.id),
            ], order='date_assigned desc, id desc', limit=1)
            if submission:
                result['progress'] = submission.progress or 0.0
                result['submissionState'] = submission.state

        return result

    def _compute_children_average_progress(self, children_nodes, student_id):
        """Compute average progress from child tree nodes."""
        if not children_nodes:
            return 0.0
        total = sum(child.get('progress', 0.0) for child in children_nodes)
        return total / len(children_nodes) if children_nodes else 0.0

    @api.model
    def get_course_explorer_progress(self, student_id):
        """Return progress data for all resources in the tree for a given student.

        Includes both content resources (has_notes != 'no') and structural
        parent resources (has_notes == 'no') that serve as hierarchy nodes,
        so the tree always has complete progress data.

        Args:
            student_id: partner ID of the current student

        Returns:
            dict mapping resource_id -> progress data
        """
        if not student_id:
            return {}

        # Content resources
        has_notes_res = self.search([
            ('show_in_hierarchy', '=', True),
        ])

        # Structural parents: resources that are ancestors
        # of content resources — they need progress data for the tree display.
        extra_parents = self.env['aps.resources']
        for res in has_notes_res:
            for parent in res.parent_ids:
                if parent.show_in_hierarchy:
                    extra_parents |= parent

        all_resources = has_notes_res | extra_parents

        result = {}
        for res in all_resources:
            data = res._compute_resource_progress(student_id)
            result[res.id] = data

        return result

    @api.model
    def toggle_resource_completion(self, resource_id):
        """Toggle the completion state of a resource for the current student.

        - If no submission exists, create one (task + submission) with state='submitted' and progress=100
        - If submission exists with state='submitted', change to state='assigned' and progress=0
        - If submission exists with state='assigned', change to state='submitted' and progress=100

        Returns:
            dict with new state, progress, and parent progress updates
        """
        student = self.env.user.partner_id
        if not student:
            return {'error': 'No student partner found'}

        resource = self.browse(resource_id)
        if not resource.exists():
            return {'error': 'Resource not found'}

        # Find or create task
        task = self.env['aps.resource.task'].search([
            ('resource_id', '=', resource.id),
            ('student_id', '=', student.id),
        ], limit=1)

        if not task:
            task = self.env['aps.resource.task'].create({
                'resource_id': resource.id,
                'student_id': student.id,
                'state': 'assigned',
            })

        # Find existing submission
        submission = self.env['aps.resource.submission'].search([
            ('task_id', '=', task.id),
        ], order='date_assigned desc, id desc', limit=1)

        if submission:
            # Toggle state
            if submission.state == 'submitted':
                submission.write({
                    'state': 'assigned',
                    'progress': 0.0,
                })
                new_state = 'assigned'
                new_progress = 0.0
            else:
                submission.write({
                    'state': 'submitted',
                    'date_submitted': fields.Date.today(),
                    'progress': 100.0,
                })
                new_state = 'submitted'
                new_progress = 100.0
        else:
            # Create new submission with submitted state
            submission = self.env['aps.resource.submission'].create({
                'task_id': task.id,
                'submission_name': resource.display_name or resource.name or '',
                'date_assigned': fields.Date.today(),
                'state': 'submitted',
                'date_submitted': fields.Date.today(),
                'progress': 100.0,
            })
            new_state = 'submitted'
            new_progress = 100.0

        # Collect parent updates from the auto-propagated data.
        # Walk the full ancestor chain (not just immediate parents) so
        # the UI can update progress rings on every level.
        parent_updates = {}
        visited = set()
        to_process = list(resource.parent_ids)
        while to_process:
            parent = to_process.pop(0)
            if parent.id in visited:
                continue
            visited.add(parent.id)
            parent_task = self.env['aps.resource.task'].search([
                ('resource_id', '=', parent.id),
                ('student_id', '=', student.id),
            ], limit=1)
            if parent_task:
                parent_sub = self.env['aps.resource.submission'].search([
                    ('task_id', '=', parent_task.id),
                ], order='date_assigned desc, id desc', limit=1)
                if parent_sub:
                    parent_updates[parent.id] = {
                        'progress': parent_sub.progress,
                        'name': parent.name or '',
                    }
            for grandparent in parent.parent_ids:
                if grandparent.id not in visited:
                    to_process.append(grandparent)

        return {
            'resourceId': resource.id,
            'newState': new_state,
            'newProgress': new_progress,
            'parentUpdates': parent_updates,
        }
