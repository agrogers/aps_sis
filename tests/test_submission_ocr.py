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

    def test_image_only_answer_is_ocrd_and_student_is_notified(self):
        answer = '<p><img src="/web/image/123/answer.png"></p>'
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
        ):
            self.submission.write({'answer': answer})

        ocr.assert_called_once()
        notify.assert_called_once_with(self.submission)
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
