from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class APSResourceSubmissionNotifications(models.Model):
    _inherit = 'aps.resource.submission'

# region - Notifications    
    def _notify_new_submission(self, subject_ids):
        """Creates an activity for each newly added faculty member."""
        # Search for faculty records to get their associated User IDs
        
        new_setting_to_receive_notifications = False
        
        if not new_setting_to_receive_notifications:
            return

        subjects = self.env['op.subject'].browse(list(subject_ids))

        for subject in subjects:
            # Most op.faculty models link to a user via a 'user_id' field
            for faculty in subject.faculty_ids:
                if faculty.emp_id.user_id:
                    self.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=faculty.emp_id.user_id.id,
                        summary=_(f"New submission by {self.student_id.display_name} for {self.display_name}"),
                        note=_(f"A task has been submitted which you may need to review or complete."),
                        date_deadline=fields.Date.add(fields.Date.today(), days=1),  
                        request_partner_id=self.env.user.partner_id.id
                    )

    def _notify_new_faculty_reviewers(self, faculty_ids):
        """Creates an activity for each newly added faculty member."""
        # Search for faculty records to get their associated User IDs
        faculties = self.env['op.faculty'].browse(list(faculty_ids))
        
        for faculty in faculties:
            # Most op.faculty models link to a user via a 'user_id' field
            if faculty.emp_id.user_id:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=faculty.emp_id.user_id.id,
                    summary=_(f"Review Requested by {self.env.user.display_name} for {self.submission_name} ({self.student_id.display_name})"),
                    note=_(f"You have been requested to review the resource submission: {self.submission_name}"),
                    date_deadline=fields.Date.add(fields.Date.today(), days=1),  
                    request_partner_id=self.env.user.partner_id.id
                )

    @api.model
    def send_active_notifications(self):
        """Send notifications for submissions that became active at least 10 minutes ago. Called by cron every 10 minutes."""
        from datetime import timedelta
        mins_before_notification = int(
            self.env['ir.config_parameter'].sudo().get_param('apex.mins_before_notification')
        ) or 10
        threshold_time = fields.Datetime.now() - timedelta(minutes=mins_before_notification)
        submissions = self.search([
            ('submission_active', '=', True),
            ('notification_state', '=', 'not_sent'),
            ('active_datetime', '!=', False),
            ('active_datetime', '<=', threshold_time),
        ])
        for submission in submissions:
            if submission.student_id and submission.student_id.email:
                # Send email notification
                template = self.env.ref('aps_sis.apex_submission_active_email_template', raise_if_not_found=False)
                if template:
                    # Example in email template or chatter
                    view = self.env.ref('aps_sis.view_aps_resource_submission_form_for_students')
                    if view:
                        record_url = f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/web#id={submission.id}&model={self._name}&view_id={view.id}"
                    else:
                        record_url = f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}"
                 
                context = {
                    'question': submission.question,  
                    'submission_name': submission.submission_name,
                    'date_assigned': submission.date_assigned,  
                    'date_due': submission.date_due,
                    'record_url': record_url,
                }
                try:
                    template.with_context(context).send_mail(submission.id, force_send=True)
                    submission.notification_state = 'sent'
                except Exception as e:
                    _logger.error(f"Failed to send email notification for submission {submission.id}: {str(e)}")
                    submission.notification_state = 'failed'

            if submission.notification_state == 'not_sent':
                # Fallback: post message
                try:
                    submission.message_post(
                        body=_("Your task '%s' is now active.") % submission.display_name,
                        partner_ids=[submission.student_id.id],
                        message_type='notification',
                        subtype_xmlid='mail.mt_note'
                    )
                    submission.notification_state = 'posted'
                except Exception as e:
                    _logger.error(f"Failed to post notification message for submission {submission.id}: {str(e)}")
                    submission.notification_state = 'failed'

# endregion - Notifications
