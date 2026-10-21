import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import html2plaintext


class TestAIWordCount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['aps.ai.provider'].create({
            'name': 'Word count test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.model = cls.env['aps.ai.model'].create({
            'name': 'Word count test model',
            'model_key': 'test/word-count-model',
            'provider_id': cls.provider.id,
        })

    def _create_resource(self, answer, with_word_count=True):
        prompt_ids = []
        if with_word_count:
            prompt = self.env['ai_prompts'].create({
                'prompt_name': 'Show Word Count',
                'prompt': 'Show the word count.',
                'message_section': 'additional_context',
                'enabled': True,
            })
            prompt_ids.append(prompt.id)
        return self.env['aps.resources'].create({
            'name': 'Word count resource',
            'marks': 10,
            'ai_action': 'mark_submission',
            'ai_answer': answer,
            'ai_model_ids': [(6, 0, [self.model.id])],
            'ai_prompt_ids': [(6, 0, prompt_ids)],
        })

    def _create_submission(self, resource, answer):
        student = self.env['res.partner'].create({
            'name': 'Word count student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        return self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': answer,
        })

    def test_prompt_is_a_code_control_and_counts_html_answer(self):
        answer = (
            '<p>Hello, <strong>world!</strong></p>'
            '<p>Second paragraph has 4 words.</p>'
        )
        resource = self._create_resource(answer)

        context = resource._build_ai_feedback_ctx()
        self.assertNotIn(
            'Show Word Count',
            context['image_prompt_names'],
        )
        self.assertIn(
            'Word Count: 7 \\ Paragraph Count: 2',
            html2plaintext(resource._append_ai_word_count('<p>AI feedback.</p>')),
        )

    def test_submission_count_is_last_after_no_score_feedback(self):
        resource = self._create_resource('<p>Resource answer.</p>')
        answer = '<p>One two three.</p><p>Four five.</p>'
        submission = self._create_submission(resource, answer)

        with patch.object(type(submission), 'write', autospec=True) as write:
            submission._apply_ai_feedback_result({
                'feedback_html': '<p>AI feedback.</p>',
                'score_comment': 'No score returned.',
            })

        feedback = write.call_args.args[1]['feedback']
        self.assertTrue(
            html2plaintext(feedback).rstrip().endswith(
                'Word Count: 5 \\ Paragraph Count: 2'
            )
        )

    def test_div_blocks_are_counted_as_separate_paragraphs(self):
        answer = (
            '<div><span>First paragraph has two chunks.</span> '
            '<span>They still count as one paragraph.</span></div>'
            '<div><span>Second paragraph.</span></div>'
        )
        answer_text = self.env['aps.resources']._html_to_ai_answer_text(answer)

        self.assertEqual(
            sum(bool(paragraph.strip()) for paragraph in answer_text.splitlines()),
            2,
        )

    def test_image_text_is_ocrd_before_counting(self):
        resource = self._create_resource(
            '<p>Typed answer.</p><p><img src="/web/image/101/answer.png"></p>'
        )
        with patch.object(
            type(resource),
            '_ocr_ai_answer_images',
            autospec=True,
            return_value='Scanned three words.',
        ) as ocr:
            feedback = resource._append_ai_word_count('<p>AI feedback.</p>')

        ocr.assert_called_once()
        self.assertIn(
            'Word Count: 5 \\ Paragraph Count: 2',
            html2plaintext(feedback),
        )

    def test_scanner_attachment_url_is_ocrd_without_allowing_external_urls(self):
        image_bytes = b'scanner image bytes'
        attachment = self.env['ir.attachment'].create({
            'name': 'scan.jpg',
            'type': 'binary',
            'datas': base64.b64encode(image_bytes),
            'mimetype': 'image/jpeg',
        })
        resource = self._create_resource('')
        self.model.write({'supports_vision': True})
        image_src = f'/web/content/{attachment.id}?download=false'
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or 'http://localhost:8069'
        same_origin_src = '%s%s' % (base_url.rstrip('/'), image_src)

        with (
            patch.object(
                type(self.model),
                '_execute_logged_router_call',
                return_value={'response_json': {}},
            ) as execute,
            patch.object(
                type(self.model),
                '_extract_message_content',
                return_value='Scanned answer.',
            ),
        ):
            for src in (image_src, same_origin_src):
                text = resource._ocr_ai_answer_images(
                    [f'<img src="{src}">'],
                    model_id=self.model.id,
                )

        self.assertEqual(text, 'Scanned answer.')
        image_content = execute.call_args.args[0]['messages'][1]['content'][1]
        image_url = image_content['image_url']['url']
        self.assertTrue(image_url.startswith('data:image/jpeg;base64,'))
        self.assertEqual(
            base64.b64decode(image_url.split(',', 1)[1]),
            image_bytes,
        )
        with self.assertRaises(UserError):
            resource._ocr_ai_answer_images(
                ['<img src="https://example.invalid/web/content/1?download=false">'],
                model_id=self.model.id,
            )

    def test_unselected_prompt_does_not_append_a_count(self):
        resource = self._create_resource('<p>One two three.</p>', with_word_count=False)

        with patch.object(type(resource), 'write', autospec=True) as write:
            resource._apply_ai_feedback_result({
                'feedback_html': '<p>AI feedback.</p>',
                'score': 5,
            })

        self.assertEqual(
            write.call_args.args[1]['ai_feedback'],
            '<p>AI feedback.</p>',
        )
