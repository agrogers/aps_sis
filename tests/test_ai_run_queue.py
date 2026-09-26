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

    def test_cron_queues_all_candidates_and_dispatches_twenty(self):
        submissions = self._create_submissions(21)
        submission_model = self.env['aps.resource.submission']

        submission_model.cron_process_auto_ai_marking()

        runs = self.env['aps.ai.run'].search([
            ('submission_id', 'in', submissions.ids),
        ])
        self.assertEqual(len(runs), 21)
        self.assertEqual(len(runs.filtered(lambda run: run.state == 'running')), 20)
        self.assertEqual(len(runs.filtered(lambda run: run.state == 'queued')), 1)
        self.assertTrue(all(runs.mapped('queued_for_dispatch')))

        submission_model.cron_process_auto_ai_marking()

        runs.invalidate_recordset()
        self.assertEqual(len(runs), 21)
        self.assertEqual(len(runs.filtered(lambda run: run.state == 'running')), 21)
        self.assertFalse(runs.filtered(lambda run: run.state == 'queued'))

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