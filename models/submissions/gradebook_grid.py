import json
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SENTINEL_ZERO = -0.01


class APSResourceSubmissionGradebook(models.Model):
    """Gradebook grid data methods for aps.resource.submission."""
    _inherit = 'aps.resource.submission'

    # ------------------------------------------------------------------ //
    # Grid data endpoint
    # ------------------------------------------------------------------ //
    @api.model
    def get_gradebook_grid_data(self, subject_category_id=None, resource_id=None, student_id=None):
        """
        Return JSON-serializable grid data for the gradebook.
        Filters by subject_category_id and/or resource_id and/or student_id.
        If resource_id points to a resource that has children, expands to all
        descendant resource submissions sharing the same date_assigned.

        Returns::
            {
                'columns': [...],
                'rows': [...],
                'summary': {...},
                'students': [...],  — student list for the dropdown
            }
        """
        domain = []
        expanded = False

        if resource_id:
            Resource = self.env['aps.resources']
            parent_resource = Resource.browse(resource_id)
            if parent_resource.exists() and parent_resource.child_ids:
                # ── Expand: get descendant + parent resource submissions ──
                expanded = True
                resource_ids = [resource_id] + parent_resource._get_all_descendants().ids

                # Find unique date_assigned + submission_label values
                # from the parent resource's submissions to scope children
                parent_subs = self.search([
                    ('resource_id', '=', resource_id),
                    ('date_assigned', '!=', False),
                ]).mapped(lambda s: (s.date_assigned, s.submission_label))
                parent_subs = list(set(parent_subs))
                parent_dates = [d for d, _ in parent_subs]
                parent_labels = [l for _, l in parent_subs if l]

                if parent_dates:
                    domain.append(('resource_id', 'in', resource_ids))
                    domain.append(('date_assigned', 'in', parent_dates))
                    if parent_labels:
                        domain.append('|')
                        domain.append(('submission_label', 'in', parent_labels))
                        domain.append(('submission_label', '=', False))
                else:
                    # No dates on parent — just get all resource submissions
                    domain.append(('resource_id', 'in', resource_ids))
            else:
                domain.append(('resource_id', '=', resource_id))

        elif subject_category_id:
            domain.append(('subject_categories', 'in', [subject_category_id]))

        if student_id:
            domain.append(('student_id', '=', student_id))

        submissions = self.search(domain, order='student_id,date_assigned,submission_label,submission_order')

        columns = self._get_gradebook_columns(expanded=expanded)
        columns = self._apply_column_prefs(columns)
        rows = []
        is_tree = False

        if expanded and parent_resource.exists() and parent_resource.child_ids:
            is_tree = True
            # ── Tree mode: each student is a root node, submissions are nested
            # under their student by resource hierarchy ──
            # Build a lookup: (student_id, resource_id) -> submission
            sub_by_stu_res = {}
            for sub in submissions:
                key = (sub.student_id.id, sub.resource_id.id)
                if key not in sub_by_stu_res:
                    sub_by_stu_res[key] = sub

            # Sort submissions so parents appear before children in the dataset.
            # Compute depth for each resource to use as sort key.
            def _res_depth(res):
                d = 0
                cur = res
                seen = set()
                while cur.primary_parent_id:
                    if cur.id in seen:
                        break
                    seen.add(cur.id)
                    cur = cur.primary_parent_id
                    d += 1
                return d

            sorted_subs = sorted(submissions, key=lambda s: (
                s.student_id.id,
                _res_depth(s.resource_id),
                s.submission_order or 0,
                s.id,
            ))

            # Track which student root nodes we've already inserted
            student_root_added = set()
            resource_id_int = resource_id  # the selected resource from the dropdown

            for sub in sorted_subs:
                stu_id = sub.student_id.id
                student = sub.student_id

                # ── Insert a student root node the first time we see this student ──
                if stu_id not in student_root_added:
                    student_root_added.add(stu_id)
                    stu_row_id = 'stu_%d' % stu_id
                    rows.append({
                        'id': stu_row_id,
                        'parentId': None,  # top-level root
                        'tree_label': student.display_name or student.name or '',
                        'student_name': student.display_name or student.name or '',
                        'student_id': stu_id,
                        'resource_name': '',
                        'submission_name': '',
                        'score': 0.0,
                        'out_of_marks': 0.0,
                        'result_percent': 0,
                        'state': '',
                        'is_locked': False,
                        'is_resource': True,  # acts as a grouping header
                        'has_child_resources': True,
                        'submission_id': False,
                    })

                is_locked = sub.state == 'complete'
                score_val = sub.score if sub.score != SENTINEL_ZERO else 0.0
                out_of_val = sub.out_of_marks or 0.0
                result_pct = sub.result_percent or 0

                # Determine the submission's parent in the tree
                res = sub.resource_id
                stu_row_id = 'stu_%d' % stu_id

                if res.id == resource_id_int:
                    # ── This submission IS the selected resource → parent = student root ──
                    parent_id = stu_row_id
                else:
                    # ── Child/grandchild: find the parent resource submission for this student ──
                    parent_res = res.primary_parent_id or (res.parent_ids and res.parent_ids[0])
                    parent_sub = None
                    if parent_res:
                        parent_key = (stu_id, parent_res.id)
                        parent_sub = sub_by_stu_res.get(parent_key)
                    if parent_sub:
                        parent_id = 'sub_%d' % parent_sub.id
                    else:
                        # Fallback: attach to the student root
                        parent_id = stu_row_id

                row = {
                    'id': 'sub_%s' % sub.id,
                    'parentId': parent_id,
                    'tree_label': res.display_name or res.name or '',
                    'student_name': sub.student_id.display_name or sub.student_id.name or '',
                    'student_id': sub.student_id.id,
                    'resource_name': res.display_name or res.name or '',
                    'submission_name': sub.submission_name or '',
                    'score': score_val,
                    'out_of_marks': out_of_val,
                    'result_percent': result_pct,
                    'state': sub.state,
                    'is_locked': is_locked,
                    'is_resource': False,
                    'has_child_resources': bool(res.child_ids),
                    'submission_id': sub.id,
                }
                if expanded:
                    row['date_assigned'] = sub.date_assigned.isoformat() if sub.date_assigned else ''
                rows.append(row)
        else:
            # ── Flat mode ──
            for sub in submissions:
                is_locked = sub.state == 'complete'
                score_val = sub.score if sub.score != SENTINEL_ZERO else 0.0
                out_of_val = sub.out_of_marks or 0.0
                result_pct = sub.result_percent or 0

                row = {
                    'id': sub.id,
                    'student_name': sub.student_id.display_name or sub.student_id.name or '',
                    'student_id': sub.student_id.id,
                    'resource_name': sub.resource_id.display_name or sub.resource_id.name or '',
                    'submission_name': sub.submission_name or '',
                    'score': score_val,
                    'out_of_marks': out_of_val,
                    'result_percent': result_pct,
                    'state': sub.state,
                    'is_locked': is_locked,
                    'has_child_resources': bool(sub.resource_id.child_ids),
                    'submission_id': sub.id,
                }
                if expanded:
                    row['date_assigned'] = sub.date_assigned.isoformat() if sub.date_assigned else ''
                rows.append(row)

        summary = self._compute_gradebook_summary(rows)

        # Build student list from these rows
        students = self._extract_students(rows)

        return {
            'columns': columns,
            'rows': rows,
            'summary': summary,
            'students': students,
            'isTreeData': is_tree,
        }

    @api.model
    def _extract_students(self, rows):
        """Extract unique students from row data."""
        seen = set()
        result = []
        for row in rows:
            sid = row.get('student_id')
            sname = row.get('student_name', '')
            if sid and sid not in seen:
                seen.add(sid)
                result.append({'id': sid, 'name': sname})
        result.sort(key=lambda s: s['name'])
        return result

    def _get_gradebook_columns(self, expanded=False):
        """Return column definitions for the gradebook grid."""
        cols = [
            {'id': 'student_name', 'name': _('Student'), 'field': 'student_name',
             'width': 200, 'sortable': True, 'editable': False, 'locked': True},
        ]
        if expanded:
            cols.append({'id': 'date_assigned', 'name': _('Date'), 'field': 'date_assigned',
                         'width': 110, 'sortable': True, 'editable': False, 'locked': True})
        cols.extend([
            {'id': 'resource_name', 'name': _('Resource'), 'field': 'resource_name',
             'width': 250, 'sortable': True, 'editable': False, 'locked': True},
            {'id': 'submission_name', 'name': _('Submission'), 'field': 'submission_name',
             'width': 180, 'sortable': True, 'editable': False, 'locked': True},
            {'id': 'score', 'name': _('Score'), 'field': 'score',
             'width': 120, 'sortable': True, 'editable': True, 'locked': False,
             'cssClass': 'slick-cell-editable'},
            {'id': 'out_of_marks', 'name': _('Out Of'), 'field': 'out_of_marks',
             'width': 100, 'sortable': True, 'editable': False, 'locked': True},
            {'id': 'result_percent', 'name': _('Result %'), 'field': 'result_percent',
             'width': 100, 'sortable': True, 'editable': False, 'locked': True,
             'cssClass': 'slick-cell-percent'},
        ])
        return cols

    @api.model
    def _apply_column_prefs(self, columns):
        """Reorder columns based on saved user preferences. Does NOT filter."""
        prefs = self.load_gradebook_column_prefs()
        if not prefs:
            return columns

        # Build order from pref list
        pref_order = [p["id"] for p in prefs]

        # Reorder columns to match pref order
        col_map = {c["id"]: c for c in columns}
        ordered = []
        for cid in pref_order:
            if cid in col_map:
                ordered.append(col_map[cid])
        # Append any new columns not yet in prefs
        seen = set(pref_order)
        for c in columns:
            if c["id"] not in seen:
                ordered.append(c)
        return ordered

    def _compute_gradebook_summary(self, rows):
        """Compute summary row from grid rows."""
        total_score = 0.0
        total_out_of = 0.0
        data_rows = []
        editable_count = 0
        for row in rows:
            if row.get('is_resource'):
                continue
            data_rows.append(row)
            if not row.get('is_locked', False):
                total_score += (row.get('score') or 0.0)
                total_out_of += (row.get('out_of_marks') or 0.0)
                editable_count += 1

        avg_pct = 0
        if total_out_of:
            avg_pct = int(round((total_score / total_out_of) * 100))

        return {
            'total_score': round(total_score, 2),
            'total_out_of': round(total_out_of, 1),
            'average_percent': avg_pct,
            'row_count': len(data_rows),
            'editable_count': editable_count,
        }

    # ------------------------------------------------------------------ //
    # Score write endpoint
    # ------------------------------------------------------------------ //
    @api.model
    def write_gradebook_score(self, submission_id, new_score, resource_id=None):
        """
        Write a score for a single submission and return updated rows + summary.
        Score changes may cascade up to parent submissions via auto_score,
        so we return ALL rows for the resource context.

        :param submission_id: The submission being edited.
        :param new_score: The new score value.
        :param resource_id: The resource that was selected in the grid (parent).
                            If omitted, falls back to the submission's own resource.

        Returns::
            {
                'updated_row': {...},   — the single row that was directly edited
                'rows': [{...}, ...],    — all rows for this resource (after cascades)
                'summary': {...},
            }
        """
        submission = self.browse(submission_id)
        if not submission.exists():
            raise UserError(_("Submission not found (ID %s).") % submission_id)

        if submission.state == 'complete':
            raise UserError(_("Cannot edit a finalised submission."))

        # Write the score — result_percent recomputes automatically via @api.depends.
        # This also triggers _check_and_update_parent_score() via the write override,
        # which may cascade score changes up to parent submissions.
        submission.write({'score': new_score, 'auto_score': False})

        # Re-fetch to get recomputed values
        submission.invalidate_recordset(['result_percent'])
        score_val = submission.score if submission.score != SENTINEL_ZERO else 0.0
        out_of_val = submission.out_of_marks or 0.0

        updated_row = {
            'id': submission.id,
            'student_name': submission.student_id.display_name or submission.student_id.name or '',
            'resource_name': submission.resource_id.display_name or submission.resource_id.name or '',
            'submission_name': submission.submission_name or '',
            'score': score_val,
            'out_of_marks': out_of_val,
            'result_percent': submission.result_percent or 0,
            'state': submission.state,
            'is_locked': submission.state == 'complete',
            'has_child_resources': bool(submission.resource_id.child_ids),
            'submission_id': submission.id,
        }

        # Re-fetch the full grid data using the selected resource (parent)
        # so cascaded parent score changes are captured.
        grid_resource_id = resource_id or submission.resource_id.id
        grid_data = self.get_gradebook_grid_data(
            subject_category_id=submission.subject_categories[:1].id if submission.subject_categories else None,
            resource_id=grid_resource_id,
        )

        return {
            'updated_row': updated_row,
            'rows': grid_data['rows'],
            'summary': grid_data['summary'],
        }

@api.model
    def write_gradebook_scores(self, score_lines, resource_id=None):
        """
        Write scores for multiple submissions in one call and return updated
        rows + summary.  This is the batched counterpart of write_gradebook_score.

        :param score_lines: List of dicts, each with 'submission_id' and 'score'.
        :param resource_id: The resource that was selected in the grid (parent).

        Returns::
            {
                'rows': [{...}, ...],    — all rows for this resource (after cascades)
                'summary': {...},
            }
        """
        submissions = self.env['aps.resource.submission']
        for line in score_lines:
            sub_id = line['submission_id']
            # In tree mode, the frontend sends numeric IDs (extracted from 'sub_X')
            # but just in case, handle string IDs
            if isinstance(sub_id, str) and sub_id.startswith('sub_'):
                sub_id = int(sub_id.replace('sub_', ''))
            sub = submissions.browse(sub_id)
            if sub.exists() and sub.state != 'complete':
                sub.write({'score': line['score'], 'auto_score': False})

        # Re-fetch the full grid data once after all writes
        grid_resource_id = resource_id
        if not grid_resource_id and score_lines:
            first_id = score_lines[0]['submission_id']
            if isinstance(first_id, str) and first_id.startswith('sub_'):
                first_id = int(first_id.replace('sub_', ''))
            first = submissions.browse(first_id)
            if first.exists():
                grid_resource_id = first.resource_id.id

        grid_data = self.get_gradebook_grid_data(
            subject_category_id=None,
            resource_id=grid_resource_id,
        )
        return {
            'rows': grid_data['rows'],
            'summary': grid_data['summary'],
        }

    # ------------------------------------------------------------------ //
    # Category / Resource lookup helpers
    # ------------------------------------------------------------------ //
    @api.model
    def get_gradebook_categories(self):
        """Return subject categories that have submissions visible to the current user."""
        Submission = self.env['aps.resource.submission']
        domain = []
        # Respect user's record rules
        submissions = Submission.search(domain)
        categories = submissions.mapped('subject_categories')
        # Deduplicate by id
        seen = set()
        result = []
        for cat in categories:
            if cat.id not in seen:
                seen.add(cat.id)
                result.append({'id': cat.id, 'name': cat.display_name or cat.name})
        result.sort(key=lambda c: c['name'])
        return result

    @api.model
    def get_gradebook_resources(self, subject_category_id=None):
        """Return resources that have submissions in the given category."""
        domain = []
        if subject_category_id:
            domain.append(('subject_categories', 'in', [subject_category_id]))
        submissions = self.search(domain)
        resources = submissions.mapped('resource_id')
        seen = set()
        result = []
        for res in resources:
            if res.id not in seen:
                seen.add(res.id)
                has_children = bool(res.child_ids)
                result.append({
                    'id': res.id,
                    'name': res.display_name or res.name,
                    'has_children': has_children,
                })
        result.sort(key=lambda r: r['name'])
        return result

    # ------------------------------------------------------------------ //
    # Column preference persistence (reorder / hide per user)
    # ------------------------------------------------------------------ //
    COLUMN_PREF_KEY = "gradebook_column_prefs"

    @api.model
    def save_gradebook_column_prefs(self, column_prefs):
        """
        Save column order & visibility preferences for the current user.
        column_prefs: list of {id, visible} dicts in desired order.
        """
        prefs = json.dumps(column_prefs)
        return self.env["ir.config_parameter"].sudo().set_param(
            f"{self.COLUMN_PREF_KEY}.{self.env.user.id}", prefs
        )

    @api.model
    def load_gradebook_column_prefs(self):
        """
        Load column order & visibility preferences for the current user.
        Returns list of {id, visible} dicts, or empty list if none saved.
        """
        raw = self.env["ir.config_parameter"].sudo().get_param(
            f"{self.COLUMN_PREF_KEY}.{self.env.user.id}", "[]"
        )
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []