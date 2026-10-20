import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestFreeformAssessment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['aps.ai.provider'].create({
            'name': 'Freeform assessment test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.model = cls.env['aps.ai.model'].create({
            'name': 'Freeform assessment vision model',
            'model_key': 'test/freeform-assessment-model',
            'provider_id': cls.provider.id,
            'supports_vision': True,
        })

    def _create_prompt(self, name, text, sequence=10, enabled=True):
        return self.env['ai_prompts'].create({
            'prompt_name': name,
            'prompt': text,
            'sequence': sequence,
            'enabled': enabled,
        })

    def _create_resource(self, prompts=None, tags=None):
        return self.env['aps.resources'].create({
            'name': 'Scanned exam resource',
            'ai_action': 'mark_scanned_exam',
            'ai_model_ids': [(6, 0, [self.model.id])],
            'ai_prompt_ids': [(6, 0, [prompt.id for prompt in prompts or []])],
            'tag_ids': [(6, 0, tags.ids)] if tags else False,
        })

    def _create_submission(self, resource, answer, state='submitted'):
        student = self.env['res.partner'].create({
            'name': 'Freeform assessment student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        return self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': answer,
            'state': state,
        })

    @staticmethod
    def _page_response(question, page_note=''):
        return {
            'page_readable': True,
            'page_note': page_note,
            'questions': [question] if question else [],
        }

    @staticmethod
    def _question(number, root, score, maximum, continues=False):
        return {
            'question_number': number,
            'root_question_number': root,
            'question_text': 'Explain the answer.',
            'student_answer': 'The student response.',
            'maximum_marks': maximum,
            'awarded_marks': score,
            'justification': 'The response earns marks for the correct explanation.',
            'continues_previous_page': continues,
            'needs_review': False,
        }

    @staticmethod
    def _router_result(response):
        return {
            'response_json': {
                'choices': [{
                    'message': {'content': json.dumps(response)},
                }],
                'usage': {},
            },
            'prompt_tokens': 10,
            'completion_tokens': 20,
            'estimated_cost': 0.01,
        }

    def test_preflight_accepts_scans_without_resource_question_or_maximum(self):
        prompt = self._create_prompt('Biology Freeform Assessment', 'Assess the scanned response.')
        resource = self._create_resource(prompts=[prompt])
        submission = self._create_submission(
            resource,
            '<p><img src="/web/image/101/page-1.png"></p>',
        )

        self.assertFalse(submission.question)
        self.assertFalse(submission.model_answer)
        self.assertFalse(submission.out_of_marks)
        self.assertFalse(submission._get_ai_marking_content_preflight())
        self.assertTrue(submission._is_auto_ai_marking_enabled())

    def test_prompts_are_matched_by_name_and_combined_in_sequence(self):
        later = self._create_prompt(
            'Freeform Assessment - accepted alternatives',
            'Accept scientifically equivalent wording.',
            sequence=20,
        )
        first = self._create_prompt(
            'Biology Freeform Assessment',
            'Assess the scanned response.',
            sequence=10,
        )
        disabled = self._create_prompt(
            'Freeform Assessment - disabled',
            'Do not use this instruction.',
            sequence=5,
            enabled=False,
        )
        resource = self._create_resource(prompts=[later, disabled, first])
        submission = self._create_submission(
            resource,
            '<img src="/web/image/102/page-1.png">',
        )

        self.assertEqual(
            submission._get_freeform_assessment_prompts().ids,
            [first.id, later.id],
        )

    def test_default_freeform_assessment_prompt_is_seeded_and_available(self):
        prompt = self.env.ref('aps_sis.prompt_freeform_assessment_default')
        resource = self._create_resource(prompts=[prompt])

        self.assertTrue(prompt.enabled)
        self.assertIn('Freeform Assessment', prompt.prompt_name)
        self.assertIn('partial credit', prompt.prompt.casefold())
        self.assertEqual(resource._get_freeform_assessment_prompts().ids, [prompt.id])

    def test_preflight_requires_page_image_but_not_freeform_prompt(self):
        resource = self._create_resource()
        no_prompt = self._create_submission(
            resource,
            '<img src="/web/image/103/page-1.png">',
        )
        self.assertFalse(no_prompt._get_ai_marking_content_preflight())

        no_image = self._create_submission(resource, '<p>Typed text only.</p>')
        self.assertIn(
            'page image',
            no_image._get_ai_marking_content_preflight()['error_text'],
        )

    def test_marking_works_without_freeform_assessment_prompt(self):
        resource = self._create_resource()
        submission = self._create_submission(
            resource,
            '<img src="/web/image/111/page-1.png">',
        )
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
            'state': 'running',
        })
        responses = [
            self._page_response(self._question('Q1', 'Q1', 1, 1)),
            {
                'paper_total': {'awarded_marks': 1, 'maximum_marks': 1},
                'groups': [
                    {'question_number': 'Q1', 'awarded_marks': 1, 'maximum_marks': 1, 'summary': 'Correct.'},
                ],
                'summary': 'The answer is correct.',
            },
        ]
        calls = []

        def fake_execute(model, payload, request_type, **kwargs):
            calls.append(request_type)
            return self._router_result(responses[len(calls) - 1])

        with (
            patch.object(
                type(self.model),
                '_prepare_feedback_image_with_reason',
                autospec=True,
                return_value=('data:image/png;base64,AA==', None),
            ),
            patch.object(
                type(self.model),
                '_execute_logged_router_call',
                autospec=True,
                side_effect=fake_execute,
            ),
            patch.object(type(run), '_write_progress', autospec=True),
            patch.object(type(run), '_commit_background_work', autospec=True),
        ):
            result = submission._generate_ai_feedback_result(ai_run=run)

        self.assertEqual(
            calls,
            ['freeform_assessment_page', 'freeform_assessment_summary'],
        )
        self.assertEqual(result['score'], 1)
        self.assertEqual(result['maximum_mark'], 1)
        self.assertIn('The answer is correct.', result['feedback_html'])

    def test_scanned_mode_does_not_queue_transcription_ocr(self):
        prompt = self._create_prompt('Freeform Assessment', 'Assess the answer.')
        ocr_tag = self.env['aps.resource.tags'].create({'name': 'OCR Required'})
        resource = self._create_resource(prompts=[prompt], tags=ocr_tag)

        submission = self._create_submission(
            resource,
            '<img src="/web/image/104/page-1.png">',
        )

        self.assertEqual(submission.submission_ocr_state, 'not_required')
        self.assertFalse(self.env['aps.ai.run'].search([
            ('submission_id', '=', submission.id),
            ('processor_key', '=', 'submission_ocr'),
        ]))

        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
            'request_origin': 'automatic',
            'attempt_number': 1,
            'state': 'queued',
        })
        run._on_ai_queue_run_start()

        self.assertEqual(submission.ai_auto_mark_state, 'running')
        self.assertFalse(run.error_message)

    def test_prompt_preview_shows_page_and_final_instructions(self):
        prompt = self._create_prompt('Freeform Assessment - Chemistry', 'Assess chemical reasoning.')
        resource = self._create_resource(prompts=[prompt])

        action = resource.action_preview_prompt()
        wizard = self.env['aps.prompt.preview.wizard'].browse(action['res_id'])

        self.assertIn('PAGE ANALYSIS SYSTEM PROMPT', wizard.prompt_text)
        self.assertIn('FINAL AGGREGATION SYSTEM PROMPT', wizard.prompt_text)
        self.assertIn('Assess chemical reasoning.', wizard.prompt_text)
        self.assertIn('"questions": [', wizard.prompt_text)

    def test_prompt_preview_works_without_freeform_assessment_prompt(self):
        resource = self._create_resource()

        action = resource.action_preview_prompt()
        wizard = self.env['aps.prompt.preview.wizard'].browse(action['res_id'])

        self.assertIn('PAGE ANALYSIS SYSTEM PROMPT', wizard.prompt_text)
        self.assertIn('FINAL AGGREGATION SYSTEM PROMPT', wizard.prompt_text)

    def test_json_mode_system_prompts_contain_lowercase_json(self):
        submission_model = self.env['aps.resource.submission']
        for stage in ('page', 'final'):
            system_prompt = submission_model._build_freeform_assessment_system_prompt(
                'Mark fairly.',
                stage,
            )
            self.assertIn('json', system_prompt)

    def test_pages_are_marked_in_order_and_continuations_replace_prior_scores(self):
        first_prompt = self._create_prompt(
            'Biology Freeform Assessment',
            'Assess biological accuracy.',
            sequence=10,
        )
        second_prompt = self._create_prompt(
            'Freeform Assessment - language',
            'Accept equivalent terminology.',
            sequence=20,
        )
        resource = self._create_resource(prompts=[first_prompt, second_prompt])
        submission = self._create_submission(
            resource,
            '<img src="/web/image/105/page-1.png">'
            '<img src="/web/image/106/page-2.png">',
        )
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
            'state': 'running',
        })
        responses = [
            self._page_response(self._question('Q1a', 'Q1', 1, 4)),
            {
                'page_readable': True,
                'page_note': '',
                'questions': [
                    self._question('Q1a', 'Q1', 2, 4, continues=True),
                    self._question('Q2', 'Q2', 3, 3),
                ],
            },
            {
                'paper_total': {'awarded_marks': 5, 'maximum_marks': 7},
                'groups': [
                    {'question_number': 'Q1', 'awarded_marks': 2, 'maximum_marks': 4, 'summary': 'Good progress.'},
                    {'question_number': 'Q2', 'awarded_marks': 3, 'maximum_marks': 3, 'summary': 'Fully correct.'},
                ],
                'summary': 'The student demonstrates strong understanding.',
            },
        ]
        calls = []

        def fake_execute(model, payload, request_type, **kwargs):
            calls.append((request_type, payload, kwargs))
            return self._router_result(responses[len(calls) - 1])

        with (
            patch.object(
                type(self.model),
                '_prepare_feedback_image_with_reason',
                autospec=True,
                return_value=('data:image/png;base64,AA==', None),
            ),
            patch.object(
                type(self.model),
                '_execute_logged_router_call',
                autospec=True,
                side_effect=fake_execute,
            ),
            patch.object(type(run), '_write_progress', autospec=True),
            patch.object(type(run), '_commit_background_work', autospec=True),
        ):
            result = submission._generate_ai_feedback_result(ai_run=run)

        self.assertEqual(
            [call[0] for call in calls],
            [
                'freeform_assessment_page',
                'freeform_assessment_page',
                'freeform_assessment_summary',
            ],
        )
        for _request_type, payload, _kwargs in calls[:2]:
            image_parts = [
                part for part in payload['messages'][1]['content']
                if part.get('type') == 'image_url'
            ]
            self.assertEqual(len(image_parts), 1)
            text_parts = [
                part for part in payload['messages'][1]['content']
                if part.get('type') == 'text'
            ]
            self.assertEqual(len(text_parts), 1)
            self.assertIn('json', text_parts[0]['text'])
        second_page_text = calls[1][1]['messages'][1]['content'][0]['text']
        self.assertIn('page 2 of 2', second_page_text)
        self.assertIn('Q1a', second_page_text)
        self.assertIn('json', calls[2][1]['messages'][1]['content'])
        self.assertEqual(result['score'], 5)
        self.assertEqual(result['maximum_mark'], 7)
        self.assertIn('data-embedded="tableOfContent"', result['feedback_html'])
        self.assertIn('<h1>AI Paper Summary</h1>', result['feedback_html'])
        self.assertIn(
            '<tr><td><strong>Known score:</strong> 5/7</td></tr>',
            result['feedback_html'],
        )
        self.assertNotIn('Unknown maximum marks', result['feedback_html'])
        self.assertIn('<h1 id="freeform-q1">Q1) 2/4</h1>', result['feedback_html'])
        self.assertIn('<h2 id="freeform-q1a">Q1a - 2/4</h2>', result['feedback_html'])
        self.assertIn('<h1 id="freeform-q2">Q2) 3/3</h1>', result['feedback_html'])
        self.assertIn('Justification:', result['feedback_html'])
        write_values = submission._get_ai_feedback_result_write_vals(result)
        self.assertEqual(write_values['score'], 5)
        self.assertEqual(write_values['out_of_marks'], 7)

    def test_missing_question_maximum_preserves_feedback_and_continues(self):
        prompt = self._create_prompt('Freeform Assessment', 'Assess the answer.')
        resource = self._create_resource(prompts=[prompt])
        submission = self._create_submission(
            resource,
            '<img src="/web/image/109/page-1.png">'
            '<img src="/web/image/110/page-2.png">',
        )
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
            'state': 'running',
        })
        unscored_question = self._question('Q2a', 'Q2', None, None)
        unscored_question.update({
            'justification': 'The answer appears correct, but no maximum mark is shown.',
            'needs_review': True,
        })
        responses = [
            self._page_response(self._question('Q1', 'Q1', 1, 2)),
            {
                'page_readable': True,
                'page_note': '',
                'questions': [
                    unscored_question,
                    self._question('Q3', 'Q3', 3, 4),
                ],
            },
            {
                'paper_total': {'awarded_marks': 4, 'maximum_marks': 6},
                'groups': [
                    {'question_number': 'Q1', 'awarded_marks': 1, 'maximum_marks': 2, 'summary': 'Good work.'},
                    {'question_number': 'Q3', 'awarded_marks': 3, 'maximum_marks': 4, 'summary': 'Mostly correct.'},
                ],
                'summary': 'Q2a appears correct, but its maximum mark is missing.',
            },
        ]
        calls = []

        def fake_execute(model, payload, request_type, **kwargs):
            calls.append(request_type)
            return self._router_result(responses[len(calls) - 1])

        with (
            patch.object(
                type(self.model),
                '_prepare_feedback_image_with_reason',
                autospec=True,
                return_value=('data:image/png;base64,AA==', None),
            ),
            patch.object(
                type(self.model),
                '_execute_logged_router_call',
                autospec=True,
                side_effect=fake_execute,
            ),
            patch.object(type(run), '_write_progress', autospec=True),
            patch.object(type(run), '_commit_background_work', autospec=True),
        ):
            result = submission._generate_ai_feedback_result(ai_run=run)

        self.assertEqual(
            calls,
            [
                'freeform_assessment_page',
                'freeform_assessment_page',
                'freeform_assessment_summary',
            ],
        )
        self.assertIsNone(result['score'])
        self.assertIsNone(result['maximum_mark'])
        self.assertIn('Q2a', result['feedback_html'])
        self.assertIn('<h1>AI Paper Summary</h1>', result['feedback_html'])
        self.assertIn(
            '<tr><td><strong>Known score:</strong> 4/6</td></tr>',
            result['feedback_html'],
        )
        self.assertNotIn('Unknown maximum marks', result['feedback_html'])
        self.assertIn('Not scored', result['feedback_html'])
        self.assertIn('answer appears correct', result['feedback_html'])
        self.assertIn('Known-mark subtotals', result['feedback_html'])
        self.assertIn('<h1 id="freeform-q3">Q3) 3/4</h1>', result['feedback_html'])
        self.assertNotIn('Q3 - Known subtotal', result['feedback_html'])

        write_values = submission._get_ai_feedback_result_write_vals(result)
        self.assertNotIn('score', write_values)
        self.assertNotIn('out_of_marks', write_values)
        submission._apply_ai_feedback_result(result)
        self.assertIn('Q2a', submission.feedback)
        self.assertIn('Q3', submission.feedback)

    def test_only_groups_with_unscored_items_show_known_subtotal(self):
        resource = self._create_resource()
        submission = self._create_submission(resource, '<img src="/web/image/112/page-1.png">')
        questions = [
            self._question('Q7a', 'Q7', 2, 3),
            self._question('Q7b', 'Q7', None, None),
            self._question('Q8', 'Q8', 1, 1),
        ]

        feedback_html = submission._build_freeform_feedback_html(
            questions,
            complete=True,
            summary='Some marks remain unknown.',
        )

        self.assertIn(
            '<h1 id="freeform-q7">Q7) Known subtotal: 2/3</h1>',
            feedback_html,
        )
        self.assertIn('<h1 id="freeform-q8">Q8) 1/1</h1>', feedback_html)

    def test_page_failure_keeps_completed_feedback_without_final_score(self):
        prompt = self._create_prompt('Freeform Assessment', 'Assess the response.')
        resource = self._create_resource(prompts=[prompt])
        submission = self._create_submission(
            resource,
            '<img src="/web/image/107/page-1.png">'
            '<img src="/web/image/108/page-2.png">',
        )
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
            'state': 'running',
        })
        first_page = self._router_result(
            self._page_response(self._question('Q1', 'Q1', 1, 2))
        )
        call_count = {'value': 0}

        def fake_execute(model, payload, request_type, **kwargs):
            call_count['value'] += 1
            if call_count['value'] == 1:
                return first_page
            raise UserError('second page could not be read')

        with (
            patch.object(
                type(self.model),
                '_prepare_feedback_image_with_reason',
                autospec=True,
                return_value=('data:image/png;base64,AA==', None),
            ),
            patch.object(
                type(self.model),
                '_execute_logged_router_call',
                autospec=True,
                side_effect=fake_execute,
            ),
            patch.object(type(run), '_write_progress', autospec=True),
            patch.object(type(run), '_commit_background_work', autospec=True),
        ):
            with self.assertRaisesRegex(UserError, 'second page'):
                submission._generate_ai_feedback_result(ai_run=run)

        self.assertIn('<h1 id="freeform-q1">', submission.feedback)
        self.assertFalse(submission.out_of_marks)
