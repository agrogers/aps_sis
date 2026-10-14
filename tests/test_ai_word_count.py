from unittest.mock import patch

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

    def test_unselected_prompt_does_not_append_a_count(self):
        resource = self._create_resource('<p>One two three.</p>', with_word_count=False)

        with patch.object(type(resource), 'write', autospec=True) as write:
            resource._apply_ai_feedback_result({'feedback_html': '<p>AI feedback.</p>'})

        self.assertEqual(
            write.call_args.args[1]['ai_feedback'],
            '<p>AI feedback.</p>',
        )
