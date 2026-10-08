import time
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools import html2plaintext


class TestSampleScaling(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['aps.ai.provider'].create({
            'name': 'Sample scaling test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.first_model = cls.env['aps.ai.model'].create({
            'name': 'First scaling model',
            'model_key': 'test/first-scaling-model',
            'provider_id': cls.provider.id,
            'priority': 5,
        })
        cls.sample_model = cls.env['aps.ai.model'].create({
            'name': 'Sample-specific model',
            'model_key': 'test/sample-specific-model',
            'provider_id': cls.provider.id,
            'priority': 10,
        })

    def _create_scaling_prompt(self):
        return self.env['ai_prompts'].create({
            'prompt_name': 'Use Sample Scaling',
            'prompt': 'Calibrate the student mark using the supplied marked samples.',
            'message_section': 'additional_context',
            'enabled': True,
        })

    def _create_target_resource(self, prompt):
        return self.env['aps.resources'].create({
            'name': 'Extended response question',
            'marks': 30,
            'question': '<p>Explain the issue.</p>',
            'answer': '<p>Target rubric and model answer.</p>',
            'ai_instructions': '<p>Assess the response against the rubric.</p>',
            'ai_use_question': True,
            'ai_use_model_answer': True,
            'ai_action': 'mark_submission',
            'ai_answer': '<p>Student response for AI Test.</p>',
            'ai_model_ids': [(6, 0, [self.first_model.id, self.sample_model.id])],
            'ai_prompt_ids': [(6, 0, [prompt.id])],
        })

    def _create_submission(self, resource):
        student = self.env['res.partner'].create({
            'name': 'Sample scaling audit student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        return self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'submission_name': 'Sample scaling audit submission',
        })

    def test_selected_prompt_enables_sample_scaling(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        other_resource = self.env['aps.resources'].create({'name': 'Normal resource'})

        self.assertTrue(resource._uses_sample_scaling())
        self.assertFalse(other_resource._uses_sample_scaling())

    def test_sample_context_uses_notes_as_answer_and_answer_as_rubric(self):
        prompt = self._create_scaling_prompt()
        target = self._create_target_resource(prompt)
        sample = self.env['aps.resources'].create({
            'name': 'Official sample',
            'marks': 30,
            'notes': '<p>Official sample response.</p>',
            'answer': '<p>Sample-specific rubric.</p>',
        })
        marking_prompts = target.ai_active_prompts.filtered(
            lambda record: record.prompt_name != 'Use Sample Scaling'
        )

        context = target._build_sample_feedback_context(
            sample,
            target._build_ai_feedback_ctx(),
            marking_prompts,
            False,
        )

        self.assertEqual(context['student_answer_html'], sample.notes)
        self.assertEqual(context['model_answer'], sample.answer)
        self.assertTrue(context['use_model_answer'])
        self.assertEqual(context['out_of_marks'], sample.marks)
        self.assertEqual(context['prompt_ids'], marking_prompts)

    def test_feedback_engine_accepts_context_override(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        feedback_context = {
            'instructions': 'Use this independent sample rubric.',
            'out_of_marks': 30,
        }

        with patch.object(
            type(self.first_model),
            '_run_feedback',
            autospec=True,
            return_value={'score': 23},
        ) as run_feedback:
            result = self.first_model.generate_feedback(
                resource,
                feedback_context=feedback_context,
            )

        self.assertEqual(result['score'], 23)
        self.assertEqual(run_feedback.call_args.kwargs['feedback_context'], feedback_context)

    def test_sample_order_guard_uses_normalized_scores(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        correctly_ordered = [
            {'official_score': 16, 'ai_score': 15, 'maximum': 30},
            {'official_score': 29, 'ai_score': 25, 'maximum': 30},
        ]
        reversed_order = [
            {'official_score': 16, 'ai_score': 27, 'maximum': 30},
            {'official_score': 29, 'ai_score': 20, 'maximum': 30},
        ]

        self.assertFalse(resource._get_sample_scaling_rank_error(correctly_ordered))
        self.assertTrue(resource._get_sample_scaling_rank_error(reversed_order))

    def test_materially_different_sample_rubric_blocks_scaling(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        target_context = resource._build_ai_feedback_ctx()
        sample_context = dict(target_context, model_answer='<p>An unrelated rubric.</p>')

        error = resource._get_sample_rubric_compatibility_error([
            {'name': 'Mismatched sample', 'context': sample_context},
        ], target_context)

        self.assertIn('Mismatched sample', error)

    def test_results_table_total_supports_marks_and_ao_columns(self):
        table = (
            '| Criterion | AO1 | AO2 |\n'
            '| --- | ---: | ---: |\n'
            '| Analysis | 8 | 10 |\n'
            '| Total | 18 |  |'
        )
        ratio_table = (
            '| Criterion | Marks |\n'
            '| --- | --- |\n'
            '| Evidence | 3/5 |'
        )

        self.assertEqual(
            self.env['aps.resources']._parse_sample_scaling_results_table_total(table),
            18,
        )
        self.assertEqual(
            self.env['aps.resources']._parse_sample_scaling_results_table_total(ratio_table),
            3,
        )

    def test_full_sample_scaling_pins_main_model_and_returns_calibrated_mark(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        sample_one = self.env['aps.resources'].create({
            'name': 'Official marker sample 1',
            'marks': 30,
            'weight': 29,
            'notes': '<p>High-scoring official sample.</p>',
            'answer': resource.answer,
            'ai_model_id': self.sample_model.id,
        })
        sample_two = self.env['aps.resources'].create({
            'name': 'Official marker sample 2',
            'marks': 30,
            'weight': 16,
            'notes': '<p>Mid-scoring official sample.</p>',
            'answer': '<p>A different sample rubric, which should not block scaling.</p>',
            'ai_model_id': self.sample_model.id,
        })
        results_prompt = self.env['ai_prompts'].create({
            'prompt_name': 'Criteria Results',
            'prompt': 'Show the marks awarded for each criterion.',
            'message_section': 'results_table',
            'enabled': True,
        })
        resource.write({
            'supporting_resource_ids': [(6, 0, [sample_one.id])],
            'child_ids': [(6, 0, [sample_two.id])],
            'ai_prompt_ids': [(4, results_prompt.id)],
        })
        calls = []
        final_score = {'value': 18}
        table_total = {'value': 18}
        sample_scores = {'high': 25, 'mid': 15}

        def mocked_generate_feedback(model, record, ai_run=None, feedback_context=None):
            calls.append((model.id, feedback_context))
            answer_text = html2plaintext(feedback_context.get('student_answer_html') or '')
            if feedback_context.get('prompt_ids').ids == [prompt.id]:
                score = 18
            elif 'High-scoring official sample' in answer_text:
                score = sample_scores['high']
            elif 'Mid-scoring official sample' in answer_text:
                score = sample_scores['mid']
            elif 'calibrated total mark is 18' in (feedback_context.get('instructions') or ''):
                score = final_score['value']
            else:
                score = 13
            raw_content = '{"score": %s}' % score
            if 'calibrated total mark is 18' in (feedback_context.get('instructions') or ''):
                raw_content = (
                    '{"score": %s, "results_table": "| Criterion | Marks |\\n'
                    '| --- | --- |\\n| AO1 | %s |"}'
                ) % (score, table_total['value'])
            return {
                'feedback_html': '<p>Marked feedback.</p>',
                'score': score,
                'score_comment': 'Rubric-based mark.',
                'prompt_tokens': 10,
                'completion_tokens': 5,
                'estimated_cost': 0.001,
                'model_id': model.id,
                'model_name': model.display_name,
                'raw_content': raw_content,
            }

        with patch.object(
            type(self.first_model),
            'generate_feedback',
            autospec=True,
            side_effect=mocked_generate_feedback,
        ):
            result = resource._generate_sample_scaled_feedback(
                ai_run=SimpleNamespace(override_model_id=self.sample_model),
            )

        self.assertEqual(len(calls), 5)
        self.assertEqual({model_id for model_id, _context in calls}, {self.first_model.id})
        self.assertEqual(calls[2][1]['student_answer_html'], resource.ai_answer)
        self.assertEqual(result['score'], 18)
        self.assertEqual(result['sample_scaling_audit']['status'], 'applied')
        self.assertEqual(result['sample_scaling_audit']['student_original_score'], 13.0)
        self.assertEqual(len(result['sample_scaling_audit']['samples']), 2)
        self.assertIn('18/30', result['sample_scaling_audit_html'])

        final_score['value'] = 19
        table_total['value'] = 19
        with patch.object(
            type(self.first_model),
            'generate_feedback',
            autospec=True,
            side_effect=mocked_generate_feedback,
        ):
            score_mismatch_result = resource._generate_sample_scaled_feedback()

        self.assertEqual(score_mismatch_result['score'], 13)
        self.assertEqual(score_mismatch_result['sample_scaling_audit']['status'], 'failed')
        self.assertIn('did not reconcile', score_mismatch_result['sample_scaling_audit']['reason'])

        final_score['value'] = 18
        table_total['value'] = 17
        with patch.object(
            type(self.first_model),
            'generate_feedback',
            autospec=True,
            side_effect=mocked_generate_feedback,
        ):
            table_mismatch_result = resource._generate_sample_scaled_feedback()

        self.assertEqual(table_mismatch_result['score'], 13)
        self.assertEqual(table_mismatch_result['sample_scaling_audit']['status'], 'failed')
        self.assertIn('Results Table totals', table_mismatch_result['sample_scaling_audit']['reason'])

        sample_scores.update(high=15, mid=25)
        with patch.object(
            type(self.first_model),
            'generate_feedback',
            autospec=True,
            side_effect=mocked_generate_feedback,
        ):
            reversed_rank_result = resource._generate_sample_scaled_feedback()

        self.assertEqual(reversed_rank_result['score'], 13)
        self.assertEqual(reversed_rank_result['sample_scaling_audit']['status'], 'skipped')
        self.assertIn('Fewer than two correctly ordered', reversed_rank_result['sample_scaling_audit']['reason'])

    def test_sample_scaling_audit_uses_one_resource_chatter_note(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        audit_html = resource._build_sample_scaling_audit_html({'status': 'applied'})

        with patch.object(type(resource), 'message_post', autospec=True) as message_post:
            resource._post_sample_scaling_audit_note({
                'sample_scaling_audit_html': audit_html,
            })

        self.assertEqual(message_post.call_count, 1)
        self.assertEqual(message_post.call_args.kwargs['subtype_xmlid'], 'mail.mt_note')
        self.assertIn('Sample scaling:', str(message_post.call_args.kwargs['body']))

    def test_submission_completion_note_includes_sample_scaling_audit(self):
        resource = self.env['aps.resources'].create({
            'name': 'Sample scaling audit resource',
            'marks': 30,
        })
        submission = self._create_submission(resource)
        audit_html = resource._build_sample_scaling_audit_html({'status': 'applied'})
        result = {
            'model_name': self.first_model.display_name,
            'estimated_cost': 0.01,
            'sample_scaling_audit_html': audit_html,
        }

        with patch.object(type(submission), 'message_post', autospec=True) as message_post:
            submission._finalize_ai_marking_success(result, request_origin='manual')

        self.assertEqual(message_post.call_count, 1)
        self.assertIn('Sample scaling:', str(message_post.call_args.kwargs['body']))

    def test_resource_background_worker_dispatches_sample_scaling(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        run = self.env['aps.ai.run'].create({
            'resource_id': resource.id,
            'requested_by_id': self.env.user.id,
        })
        result = {
            'score': 18,
            'model_id': self.first_model.id,
            'model_name': self.first_model.display_name,
            'sample_scaling_audit_html': resource._build_sample_scaling_audit_html({'status': 'applied'}),
        }

        with patch.object(type(run), '_write_progress', autospec=True), \
                patch.object(type(run), '_commit_background_work', autospec=True), \
                patch.object(type(resource), '_uses_sample_scaling', autospec=True, return_value=True), \
                patch.object(type(resource), '_generate_sample_scaled_feedback', autospec=True, return_value=result) as generate, \
                patch.object(type(resource), '_apply_ai_feedback_result', autospec=True) as apply_result, \
                patch.object(type(resource), '_post_sample_scaling_audit_note', autospec=True) as post_audit:
            run._process_background_resource(time.perf_counter())

        generate.assert_called_once_with(resource.with_user(run.requested_by_id), ai_run=run)
        self.assertEqual(apply_result.call_args.args[1], result)
        self.assertEqual(post_audit.call_args.args[1], result)

    def test_submission_background_worker_dispatches_sample_scaling(self):
        prompt = self._create_scaling_prompt()
        resource = self._create_target_resource(prompt)
        submission = self._create_submission(resource)
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
        })
        result = {
            'score': 18,
            'model_id': self.first_model.id,
            'model_name': self.first_model.display_name,
            'sample_scaling_audit_html': resource._build_sample_scaling_audit_html({'status': 'applied'}),
        }

        with patch.object(type(run), '_write_progress', autospec=True), \
                patch.object(type(run), '_commit_background_work', autospec=True), \
                patch.object(type(submission), '_uses_sample_scaling', autospec=True, return_value=True), \
                patch.object(type(submission), '_generate_sample_scaled_feedback', autospec=True, return_value=result) as generate, \
                patch.object(type(submission), '_apply_ai_feedback_result', autospec=True) as apply_result, \
                patch.object(type(submission), '_finalize_ai_marking_success', autospec=True) as finalize:
            run._process_background_submission(time.perf_counter())

        generate.assert_called_once_with(submission.with_user(run.requested_by_id), ai_run=run)
        self.assertEqual(apply_result.call_args.args[1], result)
        self.assertEqual(finalize.call_args.args[1], result)
