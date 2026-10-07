from datetime import datetime

from odoo.modules.registry import Registry
from odoo.tests.common import TransactionCase


class TestAutomaticAiRunQueue(TransactionCase):
    def setUp(self):
        super().setUp()
        self.resource = self.env['aps.resources'].create({
            'name': 'Automatic AI queue test',
            'ai_action': 'mark_submission',
        })

    def test_import_link_is_optional_for_other_run_types(self):
        self.assertFalse(self.env['aps.ai.run']._fields['import_id'].required)

    def _create_submissions(self, count):
        students = self.env['res.partner'].create([
            {'name': 'AI Queue Student %s' % index, 'is_student': True}
            for index in range(count)
        ])
        tasks = self.env['aps.resource.task'].create([
            {'resource_id': self.resource.id, 'student_id': student.id}
            for student in students
        ])
        return self.env['aps.resource.submission'].create([
            {
                'task_id': task.id,
                'answer': '<p>Student answer %s</p>' % index,
                'state': 'submitted',
            }
            for index, task in enumerate(tasks, 1)
        ])

    def test_cron_queues_candidates_on_shared_dispatcher(self):
        submissions = self._create_submissions(21)
        submission_model = self.env['aps.resource.submission']

        submission_model.cron_process_auto_ai_marking()

        runs = self.env['aps.ai.run'].search([
            ('submission_id', 'in', submissions.ids),
        ])
        self.assertEqual(len(runs), 21)
        self.assertTrue(all(runs.mapped(lambda run: run.state == 'queued')))
        self.assertTrue(all(runs.mapped('queue_key')))
        self.assertFalse(runs.filtered('queued_for_dispatch'))

        submission_model.cron_process_auto_ai_marking()

        runs.invalidate_recordset()
        self.assertEqual(len(runs), 21)
        self.assertTrue(all(runs.mapped(lambda run: run.state == 'queued')))
        self.assertTrue(all(runs.mapped('queue_key')))
        self.assertFalse(runs.filtered('queued_for_dispatch'))

    def test_submission_and_quick_runs_share_student_lane_in_fifo_order(self):
        submission = self._create_submissions(1)
        student_id = submission.student_id.id
        submission_run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
        })
        quick_run = self.env['aps.ai.quick.run'].create({
            'requested_by_id': self.env.user.id,
            'student_partner_id': student_id,
            'user_text': 'Student-scoped AI job',
        })

        submission_run._queue_background_processing()
        quick_run._queue_background_processing()

        self.assertEqual(submission_run.queue_key, 'student:res.partner:%s' % student_id)
        self.assertEqual(quick_run.queue_key, submission_run.queue_key)
        self.assertEqual(quick_run.queue_shard, submission_run.queue_shard)
        self.assertLess(submission_run.queue_sequence, quick_run.queue_sequence)
        next_run = self.env['aps.ai.quick.run']._get_next_ai_queue_run(submission_run.queue_key)
        self.assertEqual(next_run, submission_run)

    def test_student_lane_advisory_lock_excludes_another_cursor(self):
        lock_key = 'aps_ai_queue:student:res.partner:test-%s' % self.env.uid
        self.env.cr.execute(
            'SELECT pg_try_advisory_lock(hashtextextended(%s, 0))',
            [lock_key],
        )
        self.assertTrue(self.env.cr.fetchone()[0])

        try:
            with Registry(self.env.cr.dbname).cursor() as other_cr:
                other_cr.execute(
                    'SELECT pg_try_advisory_lock(hashtextextended(%s, 0))',
                    [lock_key],
                )
                self.assertFalse(other_cr.fetchone()[0])
        finally:
            self.env.cr.execute(
                'SELECT pg_advisory_unlock(hashtextextended(%s, 0))',
                [lock_key],
            )
            self.assertTrue(self.env.cr.fetchone()[0])

    def test_queue_metadata_serializes_datetime_context(self):
        context_datetime = datetime(2026, 10, 7, 9, 30)
        run = self.env['aps.ai.quick.run'].with_context(
            cron_datetime=context_datetime,
        ).create({
            'requested_by_id': self.env.user.id,
            'user_text': 'Context serialization test',
        })

        run._assign_ai_queue_metadata()

        self.assertEqual(run.queue_context['cron_datetime'], str(context_datetime))

    def test_related_runs_action_filters_same_submission_and_excludes_current(self):
        submission = self._create_submissions(1)
        runs = self.env['aps.ai.run'].create([
            {
                'submission_id': submission.id,
                'requested_by_id': self.env.user.id,
                'state': 'completed',
            },
            {
                'submission_id': submission.id,
                'requested_by_id': self.env.user.id,
                'state': 'failed',
            },
        ])

        action = runs[0].action_view_related_runs()

        self.assertEqual(runs[0].related_record_id, submission.id)
        self.assertEqual(action['res_model'], 'aps.ai.run')
        self.assertEqual(action['views'], [[False, 'list'], [False, 'form']])
        self.assertEqual(
            action['domain'],
            [('submission_id', '=', submission.id), ('id', '!=', runs[0].id)],
        )