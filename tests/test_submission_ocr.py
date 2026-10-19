from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestSubmissionOcr(TransactionCase):
    def setUp(self):
        super().setUp()
        self.student = self.env['res.partner'].create({
            'name': 'OCR Test Student',
            'is_student': True,
        })
        self.ocr_tag = self.env['aps.resource.tags'].create({
            'name': 'OCR Required',
        })
        self.resource = self.env['aps.resources'].create({
            'name': 'OCR Test Resource',
            'tag_ids': [(6, 0, [self.ocr_tag.id])],
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': self.resource.id,
            'student_id': self.student.id,
        })
        self.submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
        })

    def test_image_only_answer_is_queued_without_running_ocr_in_request(self):
        answer = '<p><img src="/web/image/123/answer.png"></p>'
        with (
            patch.object(
                type(self.submission),
                '_ocr_ai_answer_images',
                autospec=True,
                return_value='A sentence\ncontinued on this line.\n\nA new paragraph.',
            ) as ocr,
        ):
            self.submission.write({'answer': answer})

        ocr.assert_not_called()
        self.assertEqual(self.submission.submission_ocr_state, 'pending')
        self.assertEqual(self.submission.answer, answer)
        run = self.submission.submission_ocr_run_id
        self.assertTrue(run)
        self.assertEqual(run.processor_key, 'submission_ocr')
        self.assertEqual(run.state, 'queued')

    def test_background_ocr_appends_text_and_notifies(self):
        answer = '<p><img src="/web/image/123/answer.png"></p>'
        self.submission.write({'answer': answer})
        run = self.submission.submission_ocr_run_id
        with (
            patch.object(
                type(self.submission),
                '_ocr_ai_answer_images',
                autospec=True,
                return_value='A sentence\ncontinued on this line.\n\nA new paragraph.',
            ) as ocr,
            patch.object(
                type(self.submission),
                '_send_submission_ocr_dm',
                autospec=True,
            ) as notify,
            patch.object(run, '_write_progress', side_effect=lambda values: run.write(values)),
        ):
            run._process_submission_ocr_background()

        ocr.assert_called_once()
        notify.assert_called_once_with(self.submission)
        self.assertEqual(self.submission.submission_ocr_state, 'succeeded')
        self.assertEqual(run.state, 'completed')
        self.assertIn(
            '<details><summary>Text Version</summary>',
            self.submission.answer,
        )
        self.assertIn(
            '<p>A sentence continued on this line.</p><p>A new paragraph.</p>',
            self.submission.answer,
        )

    def test_submission_text_or_missing_tag_does_not_trigger_ocr(self):
        with patch.object(
            type(self.submission),
            '_ocr_ai_answer_images',
            autospec=True,
        ) as ocr:
            self.resource.write({'tag_ids': [(5, 0, 0)]})
            self.submission.write({
                'answer': '<p><img src="/web/image/123/answer.png"></p>',
            })
            self.resource.write({'tag_ids': [(6, 0, [self.ocr_tag.id])]})
            self.submission.write({
                'answer': '<p>Typed text.</p><img src="/web/image/123/answer.png">',
            })

        ocr.assert_not_called()

    def test_completion_and_manual_grade_are_deferred_until_ocr_attempt(self):
        self.submission.write({
            'answer': '<p><img src="/web/image/123/answer.png"></p>',
        })

        self.submission.write({'score': 4, 'feedback': '<p>Teacher feedback</p>', 'state': 'complete'})

        self.assertEqual(self.submission.state, 'submitted')
        self.assertNotEqual(self.submission.score, 4)
        self.assertEqual(self.submission.submission_ocr_deferred_actions['score'], 4)

        run = self.submission.submission_ocr_run_id
        with (
            patch.object(type(self.submission), '_ocr_ai_answer_images', autospec=True, return_value=''),
            patch.object(run, '_write_progress', side_effect=lambda values: run.write(values)),
        ):
            run._process_submission_ocr_background()

        self.assertEqual(self.submission.submission_ocr_state, 'failed')
        self.assertEqual(self.submission.state, 'complete')
        self.assertEqual(self.submission.score, 4)
        self.assertEqual(self.submission.feedback, '<p>Teacher feedback</p>')
        self.assertFalse(self.submission.submission_ocr_deferred_actions)

    def test_create_complete_image_submission_is_deferred(self):
        task = self.env['aps.resource.task'].create({
            'resource_id': self.resource.id,
            'student_id': self.student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p><img src="/web/image/123/answer.png"></p>',
            'state': 'complete',
            'score': 3,
        })

        self.assertEqual(submission.state, 'submitted')
        self.assertNotEqual(submission.score, 3)
        self.assertEqual(submission.submission_ocr_deferred_actions['state'], 'complete')
        self.assertTrue(submission.submission_ocr_run_id)

    def test_faculty_can_retry_failed_ocr(self):
        self.submission.write({
            'answer': '<p><img src="/web/image/123/answer.png"></p>',
        })
        first_run = self.submission.submission_ocr_run_id
        self.submission.write({
            'submission_ocr_state': 'failed',
            'submission_ocr_error': 'No transcription returned.',
        })

        with patch.object(type(self.submission), '_get_current_faculty', return_value=True):
            result = self.submission.action_retry_submission_ocr()

        retry_run = self.submission.submission_ocr_run_id
        self.assertNotEqual(retry_run, first_run)
        self.assertEqual(retry_run.state, 'queued')
        self.assertEqual(self.submission.submission_ocr_state, 'pending')
        self.assertEqual(result['tag'], 'display_notification')

    def test_text_version_is_escaped_and_keeps_paragraphs(self):
        text_version = self.submission._build_submission_text_version_html(
            'First <word>\ncontinues here.\n\nSecond paragraph.'
        )

        self.assertEqual(
            text_version,
            '<details><summary>Text Version</summary>'
            '<p>First &lt;word&gt; continues here.</p>'
            '<p>Second paragraph.</p></details>',
        )
