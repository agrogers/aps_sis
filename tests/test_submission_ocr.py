from unittest.mock import patch

from odoo.exceptions import UserError
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
            '<details><summary>OCR Text</summary>',
            self.submission.answer,
        )
        self.assertIn(
            '<p>A sentence continued on this line.</p><p>A new paragraph.</p>',
            self.submission.answer,
        )
        self.assertLess(
            self.submission.answer.index('</p>'),
            self.submission.answer.index('<details><summary>OCR Text</summary>'),
        )

    def test_mixed_text_and_images_processes_only_pages_without_ocr_details(self):
        first_image = '<p><img src="/web/content/101?download=false"></p>'
        second_image = '<p><img src="/web/content/102?download=false"></p>'
        self.submission.write({
            'answer': '<p>Typed instructions.</p>%s%s' % (first_image, second_image),
        })
        first_run = self.submission.submission_ocr_run_id
        with (
            patch.object(
                type(self.submission),
                '_ocr_ai_answer_images',
                autospec=True,
                side_effect=['First page text.', 'Second page text.'],
            ) as ocr,
            patch.object(type(self.submission), '_send_submission_ocr_dm', autospec=True),
            patch.object(first_run, '_write_progress', side_effect=lambda values: first_run.write(values)),
        ):
            first_run._process_submission_ocr_background()

        self.assertEqual(ocr.call_count, 2)
        answer_after_first_run = self.submission.answer
        first_details = self.submission._build_submission_text_version_html('First page text.')
        second_details = self.submission._build_submission_text_version_html('Second page text.')
        self.assertIn(first_image + first_details, answer_after_first_run)
        self.assertIn(second_image + second_details, answer_after_first_run)
        self.assertIn('<p>Typed instructions.</p>', answer_after_first_run)

        third_image = '<p><img src="/web/content/103?download=false"></p>'
        self.submission.write({'answer': answer_after_first_run + third_image})
        second_run = self.submission.submission_ocr_run_id
        with (
            patch.object(
                type(self.submission),
                '_ocr_ai_answer_images',
                autospec=True,
                return_value='Third page text.',
            ) as ocr,
            patch.object(type(self.submission), '_send_submission_ocr_dm', autospec=True),
            patch.object(second_run, '_write_progress', side_effect=lambda values: second_run.write(values)),
        ):
            second_run._process_submission_ocr_background()

        ocr.assert_called_once()
        self.assertEqual(ocr.call_args.args[1], ['<img src="/web/content/103?download=false">'])
        self.assertEqual(self.submission.answer.count('<summary>OCR Text</summary>'), 3)

    def test_background_ocr_error_is_recorded_without_crashing(self):
        self.submission.write({
            'answer': '<p><img src="/web/image/123/answer.png"></p>',
        })
        run = self.submission.submission_ocr_run_id
        with (
            patch.object(
                type(self.submission),
                '_ocr_ai_answer_images',
                autospec=True,
                side_effect=UserError('Only Odoo-hosted images can be OCR-transcribed for word counting.'),
            ),
            patch.object(run, '_write_progress', side_effect=lambda values: run.write(values)),
        ):
            run._process_submission_ocr_background()

        self.assertEqual(self.submission.submission_ocr_state, 'failed')
        self.assertEqual(
            self.submission.submission_ocr_error,
            'Only Odoo-hosted images can be OCR-transcribed for word counting.',
        )
        self.assertEqual(run.state, 'failed')

    def test_mixed_text_still_queues_ocr_but_missing_tag_does_not(self):
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
        self.assertEqual(self.submission.submission_ocr_state, 'pending')
        self.assertTrue(self.submission.submission_ocr_run_id)

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
            'answer': '<p>Typed note.</p><p><img src="/web/image/123/answer.png"></p>',
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

    def test_legacy_text_version_marks_preceding_images_as_processed(self):
        answer = (
            '<p><img src="/web/image/123/first.png"></p>'
            '<p><img src="/web/image/124/second.png"></p>'
            '<details><summary>Text Version</summary><p>Existing OCR.</p></details>'
        )

        self.assertEqual(
            self.submission._get_pending_submission_ocr_image_matches(answer),
            [],
        )
        pending = self.submission._get_pending_submission_ocr_image_matches(
            answer + '<p><img src="/web/image/125/third.png"></p>'
        )
        self.assertEqual(
            [image.group(0) for image in pending],
            ['<img src="/web/image/125/third.png">'],
        )

    def test_text_version_is_escaped_and_keeps_paragraphs(self):
        text_version = self.submission._build_submission_text_version_html(
            'First <word>\ncontinues here.\n\nSecond paragraph.'
        )

        self.assertEqual(
            text_version,
            '<details><summary>OCR Text</summary>'
            '<p>First &lt;word&gt; continues here.</p>'
            '<p>Second paragraph.</p></details>',
        )
