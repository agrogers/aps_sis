import logging

from odoo import SUPERUSER_ID, api, fields


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Submission = env['aps.resource.submission']
    state_field = env['ir.model.fields']._get(Submission._name, 'state')
    state_labels = {'submitted': set(), 'not_submitted': set()}
    for language in env['res.lang'].search([('active', '=', True)]):
        selection = Submission.with_context(lang=language.code).fields_get(
            ['state']
        )['state']['selection']
        for value, label in selection:
            if value in ('submitted', 'assigned', 'complete'):
                key = 'submitted' if value == 'submitted' else 'not_submitted'
                state_labels[key].add(label)

    messages = env['mail.message'].sudo().search([
        ('model', '=', Submission._name),
        ('res_id', '!=', False),
        ('tracking_value_ids.field_id', '=', state_field.id),
    ], order='create_date desc, id desc')
    submissions = Submission.browse(messages.mapped('res_id')).exists()
    submission_by_id = {record.id: record for record in submissions}
    timestamps = {}
    for message in messages:
        submission = submission_by_id.get(message.res_id)
        student = submission.student_id if submission else False
        if (
            not student
            or message.author_id != student
            or message.create_uid.partner_id != student
        ):
            continue
        if any(
            tracking.field_id == state_field
            and tracking.new_value_char in state_labels['submitted']
            and tracking.old_value_char in state_labels['not_submitted']
            for tracking in message.tracking_value_ids
        ):
            timestamps.setdefault(submission.id, message.create_date)

    cr.execute(
        'SELECT id FROM aps_resource_submission WHERE time_submitted IS NULL'
    )
    submission_ids = [row[0] for row in cr.fetchall()]
    updated = 0
    for submission_id in submission_ids:
        timestamp = timestamps.get(submission_id)
        if not timestamp:
            continue
        cr.execute(
            'UPDATE aps_resource_submission '
            'SET time_submitted = %s WHERE id = %s AND time_submitted IS NULL',
            (fields.Datetime.to_string(timestamp), submission_id),
        )
        updated += cr.rowcount

    _logger.info(
        'Backfilled time_submitted for %s submissions from student-authored '
        'chatter transitions; %s records had no matching transition.',
        updated,
        len(submission_ids) - updated,
    )