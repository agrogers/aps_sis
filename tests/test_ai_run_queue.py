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

    def test_run_fails_before_dispatch_when_question_and_model_answer_are_image_only(self):
        resource = self.env['aps.resources'].create({
            'name': 'Image-only marking context',
            'ai_action': 'mark_submission_use_answer',
            'question': '<p><img src="/web/image/101/question.png"></p>',
            'ai_use_question': True,
            'answer': (
                '<p>Do not penalise the answer for spelling and grammar mistakes as long as '
                'the meaning can still be understood.</p>'
                '<p><img src="/web/image/102/model-answer.png"></p>'
            ),
        })
        resource.write({'has_question': 'yes'})
        student = self.env['res.partner'].create({
            'name': 'Image Context Student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p>Student response text.</p>',
            'question': '<p><img src="/web/image/101/question.png"></p>',
            'state': 'submitted',
        })
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
        })

        run._on_ai_queue_run_start()

        self.assertEqual(run.state, 'failed')
        self.assertIn('Student Answer: provided', run.error_message)
        self.assertIn(
            'Model Answer: Content absent [Image only present; image inclusion prompt inactive]',
            run.error_message,
        )
        self.assertIn(
            'Question: Content absent [Image only present; image inclusion prompt inactive]',
            run.error_message,
        )
        self.assertIn('AI marking was not sent', submission.feedback)

    def test_text_in_either_marking_context_field_allows_preflight(self):
        resource = self.env['aps.resources'].create({
            'name': 'Text marking context',
            'ai_action': 'mark_submission',
            'question': '<p><img src="/web/image/101/question.png"></p>',
            'answer': '<p>Use the marking rubric below.</p>',
            'ai_use_question': True,
            'ai_use_model_answer': True,
        })
        resource.write({'has_question': 'yes'})
        student = self.env['res.partner'].create({
            'name': 'Text Context Student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p>Student response text.</p>',
            'question': '<p><img src="/web/image/101/question.png"></p>',
            'state': 'submitted',
        })

        self.assertFalse(submission._get_ai_marking_content_preflight())

    def test_model_answer_image_is_usable_when_image_prompt_is_active(self):
        include_model_answer_images = self.env['ai_prompts'].create({
            'prompt_name': 'Include Model Answer Images',
            'prompt': 'Include model answer images.',
            'enabled': True,
            'always_include': True,
        })
        resource = self.env['aps.resources'].create({
            'name': 'Image rubric with image prompt',
            'ai_action': 'mark_submission_use_answer',
            'answer': (
                '<p>Do not penalise the answer for spelling and grammar mistakes as long as '
                'the meaning can still be understood.</p>'
                '<p><img src="/web/image/102/model-answer.png"></p>'
            ),
            'ai_prompt_ids': [(6, 0, [include_model_answer_images.id])],
        })
        student = self.env['res.partner'].create({
            'name': 'Image Rubric Student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p>Student response text.</p>',
            'state': 'submitted',
        })

        self.assertIn(
            include_model_answer_images,
            resource.ai_active_prompts,
        )
        self.assertFalse(submission._get_ai_marking_content_preflight())

    def test_model_answer_image_without_image_prompt_still_fails_preflight(self):
        resource = self.env['aps.resources'].create({
            'name': 'Image rubric without image prompt',
            'ai_action': 'mark_submission_use_answer',
            'answer': (
                '<p>Do not penalise the answer for spelling and grammar mistakes as long as '
                'the meaning can still be understood.</p>'
                '<p><img src="/web/image/102/model-answer.png"></p>'
            ),
        })
        student = self.env['res.partner'].create({
            'name': 'Image Rubric No Prompt Student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p>Student response text.</p>',
            'state': 'submitted',
        })

        preflight = submission._get_ai_marking_content_preflight()

        self.assertTrue(preflight)
        self.assertIn('Model Answer: Content absent [Image only present; image inclusion prompt inactive]', preflight['error_text'])

    def test_generic_spelling_reminder_does_not_count_as_model_answer(self):
        self.assertEqual(
            self.env['aps.resource.submission']._get_ai_context_content_status(
                '<p>* Do not penalise the answer for spelling and grammar mistakes as long as '
                'the meaning can still be understood.</p><img src="/web/image/102/model-answer.png">'
            ),
            'image_only',
        )