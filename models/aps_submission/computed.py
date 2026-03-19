from datetime import datetime, time

import pytz
from odoo import models, fields, api

from .constants import sentinel_zero


class APSResourceSubmission(models.Model):
    _inherit = 'aps.resource.submission'

    # region - Computed Fields

    @api.depends('date_submitted', 'date_due', 'state', 'points_scale')
    def _compute_points(self):
        for record in self:
            if record.state in ['complete', 'submitted'] and record.date_submitted:
                if not record.date_due:
                    points = 3  # on time if no due date
                else:
                    days_from_due_date = record.date_submitted - record.date_due
                    days_diff = days_from_due_date.days

                    if days_diff > 2:  # very late (more than 2 days after due)
                        points = 1
                    elif days_diff > 0:  # late (1-2 days after due)
                        points = 2
                    elif days_diff >= -1:  # on time (on due date or 1 day early)
                        points = 3
                    elif days_diff >= -2:  # early (2 days early)
                        points = 4
                    else:  # very early (more than 2 days early)
                        points = 5

                record.points = int(points * record.points_scale)
            else:
                record.points = 0

    @api.depends('resource_id.type_id', 'resource_id.type_id.icon')
    def _compute_type_icon(self):
        # This is needed because without it the icon is never cached properly.
        # That means there is a lot of annoying downloads on every page refresh.
        # It is duplicated in other models as well.
        for record in self:
            record.type_icon = record.resource_id.type_id.icon if record.resource_id.type_id else False

    @api.depends('subjects', 'subjects.icon')
    def _compute_subject_icons(self):
        for record in self:
            if record.subjects:
                first = record.subjects[:1]
                record.subject_icons = first.icon if first else False
            else:
                record.subject_icons = False

    @api.depends('date_due', 'state')
    def _compute_days_till_due(self):
        today = fields.Date.today()
        for record in self:
            if not record.date_due or record.state != 'assigned':
                record.days_till_due = 999  # Arbitrary large number for no due date, essentially "not due"
                continue

            record.days_till_due = (record.date_due - today).days

    @api.depends('date_assigned', 'time_assigned')
    def _compute_submission_active(self):
        # There are problems with the way Odoo handles timezones and datetimes. Odoo stores datetimes in UTC
        # and converts to local time based on the user's timezone.
        # However, for the purpose of activating submissions based on the assigned date and time,
        # we want to use a fixed timezone (Myanmar) regardless of the user's actual timezone.
        # This is because the activation of submissions should be consistent for all users based on Myanmar local time.

        # I would prefer to filter records in the cron itself but I cant. I could filter just for non-active records
        # but that would cause problems with records that need to be deactivated when the assigned date is in the future. So instead I fetch all records that could possibly be active or inactive based on the assigned date and then filter them in Python. This is not ideal but it is necessary due to the limitations of Odoo's timezone handling and the need for consistent activation based on Myanmar local time.
        # Having two separate cron jobs for activation and deactivation would improve things because I can run the activaiton cron every minute and the deactivation cron every hour for example. But for simplicity I will keep it as one cron job that runs every 15 minutes and checks for both activation and deactivation candidates.

        # Hardcoded timezone for Myanmar (UTC+6:30, no DST) / this needs to be changed to use the TZ of the user who created the record or the server action
        FIXED_TZ_NAME = 'Asia/Yangon'
        tz = pytz.timezone(FIXED_TZ_NAME)

        # Current time in UTC (what Odoo uses internally)
        now_utc = fields.Datetime.now()

        # Current local time/date in Myanmar timezone (for domain filtering)
        now_local = now_utc.astimezone(tz)
        today_local = now_local.date()
        today_str = today_local.strftime('%Y-%m-%d')

        # Fetch only potential candidates based on date in Myanmar local time
        candidates_domain = [
            '|',
            '&', ('submission_active', '=', False), ('date_assigned', '<=', today_str),
            '&', ('submission_active', '=', True),
                 '|', ('date_assigned', '=', False), ('date_assigned', '>', today_str),
        ]

        candidates = self.search(candidates_domain)

        to_activate = self.env['aps.resource.submission']
        to_deactivate = self.env['aps.resource.submission']

        for record in candidates:
            if record.submission_active:
                # Already active → deactivate if date is future or missing
                to_deactivate |= record
                continue

            # Activation candidates (inactive)
            if not record.date_assigned:
                continue  # no date → skip or handle separately

            # Interpret date_assigned + time_assigned as local Myanmar time
            local_date = fields.Date.from_string(record.date_assigned)

            if not record.time_assigned or record.time_assigned == 0:
                # No time specified → activate at 00:00 Myanmar time
                local_dt_naive = datetime.combine(local_date, time(0, 0))
            else:
                # time_assigned is float hours (e.g. 13.5 → 13:30)
                hours = int(record.time_assigned)
                minutes = int((record.time_assigned - hours) * 60)
                local_dt_naive = datetime.combine(local_date, time(hours, minutes))

            # Make it timezone-aware (assume input was meant in Myanmar local time)
            local_dt_aware = tz.localize(local_dt_naive, is_dst=None)  # is_dst=None raises error on ambiguous times (rare)

            # Convert to naive UTC datetime for comparison with Odoo's now_utc
            assign_utc = local_dt_aware.astimezone(pytz.UTC).replace(tzinfo=None)

            # Activate if current UTC time has passed the assigned UTC time
            if now_utc >= assign_utc:
                to_activate |= record

        # Apply batch updates
        if to_activate:
            to_activate.write({'submission_active': True})
        if to_deactivate:
            to_deactivate.write({'submission_active': False})

    @api.model
    def recompute_submission_active_status(self):
        """Recompute active status for all submissions. Called by cron job daily."""
        submissions = self.search([])
        submissions._compute_submission_active()

    @api.depends('date_assigned', 'submission_active')
    def _compute_active_datetime(self):
        for record in self:
            if record.submission_active and not record.active_datetime:
                record.active_datetime = fields.Datetime.now()
            elif not record.submission_active:
                record.active_datetime = False

    @api.depends('feedback')
    def _compute_has_feedback(self):
        for record in self:
            record.has_feedback = bool(record.feedback and record.feedback.strip())

    @api.depends('date_assigned')
    def _compute_date_due(self):
        for record in self:
            if record.date_assigned:
                # Set due date to 7 days after assignment
                record.date_due = fields.Date.add(record.date_assigned, days=7)
            else:
                record.date_due = False

    @api.depends('date_due', 'date_submitted', 'date_completed', 'state')
    def _compute_due_status(self):

        now = fields.Date.today()
        for record in self:

            # Use completion date if submission is complete, otherwise use current date
            # Handle case where date_submitted is not set yet during state transition
            if record.state in ['submitted', 'complete'] and record.date_submitted:
                compare_date = record.date_submitted
            else:
                compare_date = now

            if not record.date_due:
                if record.state == 'assigned':
                    record.due_status = False
                else:
                    record.due_status = 'on-time'
            else:
                # Early: submitted 1 day or more before due date
                due_date_minus_1 = fields.Date.add(record.date_due, days=-1)

                if record.date_due and compare_date < due_date_minus_1:
                    # if the submission is well before the due date
                    record.due_status = 'early' if record.state in ['submitted', 'complete'] else False
                elif compare_date <= record.date_due:
                    # If the submission is within 1 day of the due date then it is on-time
                    record.due_status = 'on-time' if record.state in ['submitted', 'complete'] else False
                else:
                    # If due date has passed, then the submission is late regardless of State
                    record.due_status = 'late'

    @api.depends()
    def _compute_is_current_user_faculty(self):
        faculty = self._get_current_faculty()
        for record in self:
            record.is_current_user_faculty = bool(faculty)

    @api.depends('reviewed_by')
    def _compute_is_current_user_reviewed(self):
        faculty = self._get_current_faculty()
        for record in self:
            record.is_current_user_reviewed = bool(faculty) and (faculty in record.reviewed_by)

    @api.depends('resource_id.has_answer', 'resource_id.primary_parent_id.has_answer')
    def _compute_model_answer_is_notes(self):
        for record in self:
            resource = record.resource_id
            record.model_answer_is_notes = bool(
                resource
                and (
                    resource.has_answer == 'yes_notes'
                    or (resource.has_answer == 'use_parent' and resource.primary_parent_id and resource.primary_parent_id.has_answer == 'yes_notes')
                )
            )

    @api.depends('score', 'out_of_marks')  # Needed to trigger recompute when related model fields change fields change
    def _compute_result_percent(self):
        """Auto-calculate result_percent based on score and out_of_marks"""
        for record in self:
            if record.score and record.score != sentinel_zero and record.out_of_marks and record.out_of_marks != sentinel_zero:
                record.result_percent = int(round((record.score / record.out_of_marks) * 100))
            elif record.score == sentinel_zero or not record.out_of_marks or record.out_of_marks == sentinel_zero:
                record.result_percent = 0

    @api.depends('date_assigned', 'submission_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.submission_name} ({record.date_assigned})"

    # endregion - Computed Fields
