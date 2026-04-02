from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval
from .model import sentinel_zero
import logging

_logger = logging.getLogger(__name__)


class APSResourceSubmissionActions(models.Model):
    _inherit = 'aps.resource.submission'

# region - Action Methods
    def action_mark_complete(self):
        today = fields.Date.today()

        for record in self:
            faculty = self._get_current_faculty()
            if not faculty:
                raise UserError("Only faculty members can mark submissions as complete.")

            if record.state == 'complete':
                continue  # or raise / log / skip

            record.write({
                'state': 'complete',
                'date_completed': today,
            })

        # Optional success message
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_mark_complete_next(self):
        """Mark current submission complete and open the next submission in the current list."""
        self.ensure_one()

        faculty = self._get_current_faculty()
        if not faculty:
            raise UserError("Only faculty members can mark submissions as complete.")

        # Prefer active_ids to preserve the exact current client-side list order.
        active_ids = self.env.context.get('active_ids') or []
        next_id = False

        if active_ids and self.id in active_ids:
            current_index = active_ids.index(self.id)
            if current_index + 1 < len(active_ids):
                next_id = active_ids[current_index + 1]

        # Fallback for contexts that don't pass active_ids (e.g., direct form access).
        if not next_id:
            active_domain = self.env.context.get('active_domain')
            domain = []
            if isinstance(active_domain, (list, tuple)):
                domain = list(active_domain)
            elif isinstance(active_domain, str) and active_domain.strip():
                try:
                    domain = safe_eval(
                        active_domain,
                        {
                            'uid': self.env.uid,
                            'active_id': self.id,
                            'active_ids': active_ids,
                            'context': dict(self.env.context),
                        },
                    )
                except Exception:
                    _logger.warning("Could not evaluate active_domain: %s", active_domain)
                    domain = []

            if domain:
                record_set = self.search(domain)
                if self in record_set:
                    ordered_ids = record_set.ids
                    current_index = ordered_ids.index(self.id)
                    if current_index + 1 < len(ordered_ids):
                        next_id = ordered_ids[current_index + 1]

        if self.state != 'complete':
            self.write({
                'state': 'complete',
                'date_completed': fields.Date.today(),
            })

        if not next_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Done',
                    'message': 'Submission marked as complete. No next submission in this list.',
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }

        view_id = self.env.ref('aps_sis.view_aps_resource_submission_form_for_students').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('My Submissions'),
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'res_id': next_id,
            'target': 'current',
            'context': {
                'default_notebook_page': 'question_page',
            },
        }

    def action_mark_submitted(self):
        self.write({
            'state': 'submitted',
            'date_submitted': fields.Date.today(),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_mark_unsubmitted(self):
        self.write({
            'state': 'assigned',
            'date_submitted': False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_resubmit(self):
        """Resubmit the submission by creating a copy with cleared fields."""
        faculty = self._get_current_faculty()
        faculty_id = faculty.id if faculty else False
        
        for record in self:
            new_submission = record.copy({
                'assigned_by': faculty_id,
                'date_due': False,
                'answer': None,
                'feedback': None,
                'reviewed_by': [(5,)],  # Clear many2many
                'review_requested_by': [(5,)],  # Clear many2many
                'state': 'assigned',  # Reset to assigned
                'date_submitted': False,
                'date_completed': False,
                'score': sentinel_zero,
                'result_percent': 0,
                'active_datetime': False,
                'submission_active': True,

            })
        
        # Open the new submission form
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resubmitted Submission',
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': new_submission.id,
            'target': 'current',
        }

    def action_set_due_status_on_time(self):
        self.write({
            'due_status': 'on-time',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': f"Processed {len(self)} submission(s).",
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_mark_reviewed(self):
        faculty = self._get_current_faculty()
        if not faculty:
            raise UserError("Only faculty members can mark submissions as reviewed.")

        for record in self:
            record.write({
                'reviewed_by': [(4, faculty.id)],
                'review_requested_by': [(3, faculty.id)],
            })

        return True

    def action_open_student_dashboard(self):
        """Open the student dashboard for the current submission's student."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.student_id.name} - Dashboard',
            'res_model': 'aps.resource.submission',
            'view_mode': 'graph,calendar,list',
            'domain': [('student_id', '=', self.student_id.id)],
            'context': {'search_default_student_id': self.student_id.id},
            'target': 'current',
        }

    def action_open_submission(self):
        """Open the submission form view."""
        self.ensure_one()
        view_id = self.env.ref('aps_sis.view_aps_resource_submission_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'views': [(view_id, 'form')] if view_id else [],  # only include if view exists
        }
    
    def action_open_submission_student_view(self):
        """Open the submission form view for students."""
        self.ensure_one()
        view_id = self.env.ref('aps_sis.view_aps_resource_submission_form_for_students').id
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'aps.resource.submission',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'context': {
                'default_notebook_page': 'question_page',
            },
            'views': [(view_id, 'form')] if view_id else [],  # only include if view exists
        }

    def action_open_task(self):
        """Open the linked task's form view."""
        self.ensure_one()
        if not self.task_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.task_id.display_name,
            'res_model': 'aps.resource.task',
            'view_mode': 'form',
            'res_id': self.task_id.id,
            'target': 'current',
        }

# endregion - Action Methods
