import math
from datetime import timedelta
from urllib.parse import parse_qs, quote, urlsplit

from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools.safe_eval import safe_eval
from .model import sentinel_zero
import logging

_logger = logging.getLogger(__name__)


class APSResourceSubmissionActions(models.Model):
    _inherit = 'aps.resource.submission'

# region - Action Methods
    @api.model
    def get_sticker_award_catalog(self, submission_id=None):
        if not self.env.user.has_group('aps_sis.group_aps_teacher'):
            raise AccessError(_('Only teachers can view the sticker award catalog.'))
        return self.env['aui.sticker'].get_catalog()

    @api.model
    def _resolve_sticker_award(self, sticker_id):
        if isinstance(sticker_id, bool):
            raise ValidationError(_('Select a valid sticker.'))
        try:
            sticker_id = int(sticker_id)
        except (TypeError, ValueError) as error:
            raise ValidationError(_('Select a valid sticker.')) from error
        sticker = self.env['aui.sticker'].sudo().search([
            ('id', '=', sticker_id),
            ('active', '=', True),
        ], limit=1)
        if not sticker:
            raise ValidationError(_('The selected sticker is not available.'))
        base_url = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', '')
            .rstrip('/')
        )
        return {
            'sticker_id': sticker.id,
            'name': sticker.name,
            'image_url': f"{base_url}/aui_enhancements/{quote(sticker.image_path, safe='/')}",
        }

    @api.model
    def _create_sticker_award_placement(
        self,
        sticker,
        student_user,
        placement_values,
        url_scope_prefixes,
        days_to_live,
    ):
        self.env['aui.user.sticker'].with_user(student_user).sudo().create({
            **placement_values,
            'user_id': student_user.id,
            'sticker_id': sticker['sticker_id'],
            'include_url_prefixes': url_scope_prefixes,
            'expires_at': fields.Datetime.now() + timedelta(days=days_to_live),
        })

    @api.model
    def _get_sticker_award_base_url(self):
        try:
            request_base_url = request.httprequest.url_root
        except RuntimeError:
            request_base_url = ''
        if request_base_url:
            return request_base_url.rstrip('/')
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', '')
            .rstrip('/')
        )

    @api.model
    def _get_sticker_award_url_scope(self, submission, validated_url, base_url):
        sticker_model = self.env['aui.user.sticker'].sudo()
        parsed_url = urlsplit(validated_url)
        configured_base_url = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', '')
            .rstrip('/')
        )
        base_urls = [
            candidate
            for candidate in (configured_base_url, base_url)
            if candidate
        ]
        base_urls = list(dict.fromkeys(base_urls))

        matched_base_url = None
        for candidate_base_url in base_urls:
            candidate_base = urlsplit(candidate_base_url)
            candidate_base_path = candidate_base.path.rstrip('/')
            candidate_expected_path = f"{candidate_base_path}/web" or '/web'
            candidate_odoo_path = f"{candidate_base_path}/odoo" or '/odoo'
            modern_odoo_route = (
                parsed_url.path == candidate_odoo_path
                or parsed_url.path.startswith(f"{candidate_odoo_path}/")
            )
            if parsed_url.path == candidate_expected_path or modern_odoo_route:
                matched_base_url = candidate_base_url
                break
        if not matched_base_url:
            raise ValidationError(_('The sticker must be limited to this submission page.'))

        parsed_base_url = urlsplit(matched_base_url)
        base_path = parsed_base_url.path.rstrip('/')
        expected_path = f"{base_path}/web" or '/web'
        odoo_path = f"{base_path}/odoo" or '/odoo'
        route = parse_qs(parsed_url.fragment)
        legacy_record_route = (
            parsed_url.path == expected_path
            and route.get('model') == [submission._name]
            and route.get('id') == [str(submission.id)]
        )
        if parsed_url.path == expected_path and not legacy_record_route:
            raise ValidationError(_('The sticker must be limited to this submission page.'))

        scope_base_url = matched_base_url.rstrip('/')
        model_route = f"{scope_base_url}/odoo/{submission._name}/{submission.id}"
        if legacy_record_route:
            url_scope = model_route
        else:
            current_path = parsed_url.path.rstrip('/')
            last_path_part = current_path.rsplit('/', 1)[-1]
            if last_path_part.isdigit() and last_path_part != str(submission.id):
                raise ValidationError(
                    _('The sticker must be limited to this submission page.')
                )
            current_record_path = (
                current_path
                if last_path_part == str(submission.id)
                else f"{current_path}/{submission.id}"
            )
            path_segments = [
                segment for segment in current_path.split('/') if segment
            ]
            has_submission_route = any(
                'submission' in segment.casefold()
                for segment in path_segments
            )
            has_submission_id = str(submission.id) in path_segments
            if has_submission_route and has_submission_id:
                url_scope = model_route
            else:
                url_scope = (
                    f"{scope_base_url}{current_record_path}"
                )
        return sticker_model._validate_url_prefix(url_scope)

    @api.model
    def award_sticker(
        self,
        submission_id,
        sticker_id,
        days_to_live,
        url_prefix,
        position_x,
        position_y,
        size,
    ):
        if not self.env.user.has_group('aps_sis.group_aps_teacher'):
            raise AccessError(_('Only teachers can award stickers.'))
        if not isinstance(submission_id, int) or isinstance(submission_id, bool):
            raise ValidationError(_('Select a valid submission.'))

        submission = self.browse(submission_id).exists()
        if not submission:
            raise ValidationError(_('The selected submission is not available.'))
        submission.ensure_one()
        submission.check_access('write')
        if not submission._get_current_faculty():
            raise AccessError(_('Only faculty members can award stickers.'))
        if not submission.student_id:
            raise UserError(_('This submission does not have a student.'))

        if isinstance(days_to_live, bool):
            raise ValidationError(_('Sticker duration must be a whole number of days.'))
        try:
            duration = float(days_to_live)
        except (TypeError, ValueError) as error:
            raise ValidationError(_('Sticker duration must be a whole number of days.')) from error
        if not math.isfinite(duration) or not duration.is_integer() or not 1 <= duration <= 3650:
            raise ValidationError(_('Sticker duration must be from 1 to 3650 whole days.'))
        days_to_live = int(duration)

        sticker = self._resolve_sticker_award(sticker_id)

        sticker_model = self.env['aui.user.sticker'].sudo()
        placement_values = sticker_model._validated_values({
            'position_x': position_x,
            'position_y': position_y,
            'size': size,
        })
        validated_url = sticker_model._validate_url_prefix(url_prefix)
        base_url = self._get_sticker_award_base_url()
        model_route = f"{base_url}/odoo/{submission._name}/{submission.id}"
        url_scope_prefixes = [self._get_sticker_award_url_scope(
            submission,
            validated_url,
            base_url,
        )]
        record_url = model_route

        student_user = self.env['res.users'].sudo().search([
            ('partner_id', '=', submission.student_id.id),
            ('active', '=', True),
        ], limit=1)
        if not student_user:
            raise UserError(_('The student needs an active Odoo user account to receive a sticker.'))

        self._create_sticker_award_placement(
            sticker,
            student_user,
            placement_values,
            url_scope_prefixes,
            days_to_live,
        )
        student_user.write({'aui_stickers_enabled': True})

        body = Markup(
            '<p>You earned a sticker. Good job!</p>'
            '<p><a href="{record_url}">{record_name}</a></p>'
            '<p><img src="{image_url}" alt="{sticker_name}" '
            'style="width: 64px; height: auto;"/></p>'
        ).format(
            record_url=record_url,
            record_name=submission.display_name or _('Submission'),
            image_url=sticker['image_url'],
            sticker_name=sticker['name'],
        )
        channel = self.env['discuss.channel'].channel_get(
            partners_to=sorted({
                self.env.user.partner_id.id,
                submission.student_id.id,
            }),
            pin=False,
        )
        channel.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return True

    @api.model
    def action_repair_course_explorer_submissions(self):
        """Rebuild Course Explorer records from existing leaf submissions.

        This is intentionally a global maintenance operation. It treats the
        newest submission for each student/resource leaf pair as the source
        record, marks it as Course Explorer, and lets the normal parent
        propagation code recreate the derived ancestor chain. Other records
        are preserved for manual review and cleanup.
        """
        submissions = self.search([
            ('task_id', '!=', False),
            ('student_id', '!=', False),
            ('resource_id', '!=', False),
        ])
        candidates = {}
        skipped = 0
        for submission in submissions:
            resource = submission.resource_id
            if not resource:
                skipped += 1
                continue
            visible_content_children = resource.child_ids.filtered(
                lambda child: child.show_in_hierarchy and child.has_notes != 'no'
            )
            if visible_content_children:
                continue
            key = (submission.student_id.id, resource.id)
            current = candidates.get(key)
            if not current or (submission.create_date, submission.id) > (
                current.create_date, current.id
            ):
                candidates[key] = submission

        repaired = 0
        parents_created = 0
        parents_reused = 0
        for submission in candidates.values():
            if not submission.is_course_explorer:
                submission.write({'is_course_explorer': True})
                repaired += 1
            if submission.state == 'assigned' and submission.date_assigned:
                submission.with_context(course_explorer_repair=True).write({
                    'date_assigned': False,
                })

            before = self.search_count([
                ('task_id.student_id', '=', submission.student_id.id),
                ('task_id.resource_id', 'in', submission.resource_id.parent_ids.ids),
                ('is_course_explorer', '=', True),
            ])
            submission._propagate_progress_to_parents()
            after = self.search_count([
                ('task_id.student_id', '=', submission.student_id.id),
                ('task_id.resource_id', 'in', submission.resource_id.parent_ids.ids),
                ('is_course_explorer', '=', True),
            ])
            parents_created += max(after - before, 0)
            parents_reused += min(before, after)

        return {
            'scanned': len(submissions),
            'leaf_candidates': len(candidates),
            'repaired': repaired,
            'parents_created': parents_created,
            'parents_reused': parents_reused,
            'skipped': skipped,
            'duplicates_preserved': max(len(submissions) - len(candidates), 0),
        }

    def action_mark_complete(self):
        today = fields.Date.today()
        deferred_count = 0

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
            if record.state != 'complete' and record.submission_ocr_deferred_actions:
                deferred_count += 1

        # Optional success message
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Done',
                'message': (
                    _('%s submission(s) will be completed after the OCR attempt.') % deferred_count
                    if deferred_count else f"Processed {len(self)} submission(s)."
                ),
                'type': 'info' if deferred_count else 'success',
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

        if self.state != 'complete' and self.submission_ocr_deferred_actions:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Completion Deferred'),
                    'message': _('This submission will be completed after its OCR attempt.'),
                    'type': 'info',
                },
            }

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

    def action_mark_submitted_next(self):
        """Mark current submission submitted and open the next submission in the current list."""
        self.ensure_one()

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

        self.write({
            'state': 'submitted',
            'date_submitted': fields.Date.today(),
        })

        if not next_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Done',
                    'message': 'Submission marked as submitted. No next submission in this list.',
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

    def action_open_resource(self):
        """Open the linked resource's form view."""
        self.ensure_one()
        if not self.resource_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.resource_id.display_name,
            'res_model': 'aps.resources',
            'view_mode': 'form',
            'res_id': self.resource_id.id,
            'target': 'current',
        }

# endregion - Action Methods
