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
                # ── Expand: get ALL descendant resource submissions ──
                expanded = True
                descendant_ids = parent_resource._get_all_descendants().ids

                # Find unique date_assigned values from the parent resource's submissions
                parent_dates = self.search([
                    ('resource_id', '=', resource_id),
                    ('date_assigned', '!=', False),
                ]).mapped('date_assigned')
                parent_dates = list(set(parent_dates))

                if parent_dates:
                    domain.append(('resource_id', 'in', descendant_ids))
                    domain.append(('date_assigned', 'in', parent_dates))
                else:
                    # No dates on parent — just get all descendant submissions
                    domain.append(('resource_id', 'in', descendant_ids))
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
                'score_contributes_to_parent': sub.resource_id.score_contributes_to_parent,
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
        count = 0
        for row in rows:
            if not row.get('is_locked', False):
                total_score += row.get('score', 0.0)
                total_out_of += row.get('out_of_marks', 0.0)
                count += 1

        avg_pct = 0
        if total_out_of:
            avg_pct = int(round((total_score / total_out_of) * 100))

        return {
            'total_score': round(total_score, 2),
            'total_out_of': round(total_out_of, 1),
            'average_percent': avg_pct,
            'row_count': len(rows),
            'editable_count': count,
        }

    # ------------------------------------------------------------------ //
    # Score write endpoint
    # ------------------------------------------------------------------ //
    @api.model
    def write_gradebook_score(self, submission_id, new_score):
        """
        Write a score for a single submission and return updated row + summary.
        Returns::
            {
                'updated_row': {...},
                'summary': {...},
            }
        """
        submission = self.browse(submission_id)
        if not submission.exists():
            raise UserError(_("Submission not found (ID %s).") % submission_id)

        if submission.state == 'complete':
            raise UserError(_("Cannot edit a finalised submission."))

        # Write the score — result_percent recomputes automatically via @api.depends
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
            'score_contributes_to_parent': submission.resource_id.score_contributes_to_parent,
            'submission_id': submission.id,
        }

        # Recompute summary — we need the full context, so re-fetch grid data
        # But for efficiency, just recompute from the single updated row context
        # by fetching all rows for the same resource
        grid_data = self.get_gradebook_grid_data(
            subject_category_id=submission.subject_categories[:1].id if submission.subject_categories else None,
            resource_id=submission.resource_id.id,
        )

        return {
            'updated_row': updated_row,
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