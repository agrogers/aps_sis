import time
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools import html2plaintext


class TestSampleComparison(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['aps.ai.provider'].create({
            'name': 'Sample comparison test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.model = cls.env['aps.ai.model'].create({
            'name': 'Sample comparison model',
            'model_key': 'test/sample-comparison-model',
            'provider_id': cls.provider.id,
            'priority': 5,
        })

    def _create_prompt(self, name='Use Sample Comparison'):
        return self.env['ai_prompts'].create({
            'prompt_name': name,
            'prompt': 'Use relative benchmark comparisons.',
            'message_section': 'additional_context',
            'enabled': True,
        })

    def _create_resource(self, prompt, marks=30):
        return self.env['aps.resources'].create({
            'name': 'Comparison target',
            'marks': marks,
            'question': '<p>Explain the issue.</p>',
            'answer': '<p>Target rubric.</p>',
            'ai_instructions': '<p>Apply the target rubric.</p>',
            'ai_use_question': True,
            'ai_use_model_answer': True,
            'ai_action': 'mark_submission',
            'ai_answer': '<p>Student response.</p>',
            'ai_model_ids': [(6, 0, [self.model.id])],
            'ai_prompt_ids': [(6, 0, [prompt.id])],
        })

    def _get_sample_answer_tag(self):
        tag = self.env['aps.resource.tags'].search([('name', '=ilike', 'Sample Answer')], limit=1)
        return tag or self.env['aps.resource.tags'].create({'name': 'Sample Answer'})

    @staticmethod
    def _comparison(scores_and_results):
        return [
            {'benchmark_id': index, 'benchmark_score': score, 'result': result, 'status': 'complete'}
            for index, (score, result) in enumerate(scores_and_results, start=1)
        ]

    def test_selected_prompt_enables_comparison_only_when_attached(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        other = self.env['aps.resources'].create({'name': 'No comparison'})
        self.assertTrue(resource._uses_sample_comparison())
        self.assertFalse(other._uses_sample_comparison())

    def test_calibration_perfect_monotonic_bracket(self):
        resource = self.env['aps.resources']
        result = resource.calculate_score_range(self._comparison([
            (15, 'BETTER'), (20, 'BETTER'), (25, 'WORSE'), (29, 'WORSE'),
        ]), 30)
        self.assertEqual((result['score_lower'], result['score_upper']), (20, 25))
        self.assertEqual(result['anomaly_count'], 0)

    def test_calibration_same_benchmark_and_all_same(self):
        resource = self.env['aps.resources']
        bracketed = resource.calculate_score_range(self._comparison([
            (15, 'BETTER'), (20, 'SAME'), (25, 'WORSE'), (29, 'WORSE'),
        ]), 30)
        self.assertLessEqual(abs(bracketed['score_estimate'] - 20), 1)
        self.assertLessEqual(bracketed['score_upper'] - bracketed['score_lower'], 2)

        all_same = resource.calculate_score_range(self._comparison([
            (20, 'SAME'), (21, 'SAME'), (20, 'SAME'),
        ]), 30)
        self.assertEqual(all_same['score_estimate'], 20)
        self.assertLessEqual(all_same['score_upper'] - all_same['score_lower'], 2)

    def test_calibration_flags_minor_inversion_without_dropping_evidence(self):
        resource = self.env['aps.resources']
        comparisons = self._comparison([
            (15, 'BETTER'), (20, 'BETTER'), (25, 'WORSE'), (29, 'BETTER'),
        ])
        result = resource.calculate_score_range(comparisons, 30)
        self.assertEqual(len(result['comparisons']), 4)
        anomaly = [item for item in result['comparisons'] if item['benchmark_score'] == 29]
        self.assertEqual(len(anomaly), 1)
        self.assertTrue(anomaly[0]['anomaly'])
        self.assertEqual((result['score_lower'], result['score_upper']), (20, 25))
        self.assertIn(result['confidence'], ('MEDIUM', 'LOW'))

    def test_calibration_three_samples_and_severe_inversion(self):
        resource = self.env['aps.resources']
        three = resource.calculate_score_range(self._comparison([
            (15, 'BETTER'), (25, 'WORSE'), (29, 'WORSE'),
        ]), 30)
        self.assertEqual((three['score_lower'], three['score_upper']), (15, 25))

        severe = resource.calculate_score_range(self._comparison([
            (15, 'WORSE'), (20, 'BETTER'), (25, 'WORSE'), (29, 'BETTER'),
        ]), 30)
        self.assertGreaterEqual(severe['anomaly_count'], 2)
        self.assertEqual(severe['confidence'], 'LOW')
        self.assertGreater(severe['score_upper'] - severe['score_lower'], 5)

    def test_test_four_semantic_conflict_is_reported(self):
        result = self.env['aps.resources'].calculate_score_range(self._comparison([
            (15, 'WORSE'), (20, 'WORSE'), (25, 'BETTER'), (29, 'BETTER'),
        ]), 30)
        self.assertGreaterEqual(result['anomaly_count'], 1)
        self.assertEqual(result['confidence'], 'LOW')

    def test_comparison_context_does_not_disclose_official_score(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        context = resource._build_sample_comparison_context(
            resource._build_ai_feedback_ctx(),
            prompt,
            '<p>Benchmark response text.</p>',
            'Identified benchmark resource',
        )
        self.assertFalse(context['out_of_marks'])
        self.assertEqual(context['note_section_key'], 'answer_2')
        self.assertTrue(context['comparison_pair'])
        self.assertEqual(context['answer_2_resource_name'], 'Identified benchmark resource')
        self.assertEqual(html2plaintext(context['notes']).strip(), 'Benchmark response text.')
        self.assertNotIn('official score', str(context['notes']).casefold())
        self.assertIn('"result"', context['output_schema_override'])
        self.assertIn('Answer 1', context['instructions'])
        self.assertIn('Answer 2', context['instructions'])
        self.assertNotIn('sample answer', context['instructions'].casefold())
        self.assertIn('Do not introduce, assume, or substitute a topic', context['instructions'])

    def test_resource_and_submission_contexts_only_differ_by_student_answer(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        test_answer = '<p>Test response <img src="/web/image/101/test.png"/></p>'
        submission_answer = '<p>Submitted response <img src="/web/image/102/answer.png"/></p>'
        resource.write({
            'ai_answer': test_answer,
            'ai_use_notes': True,
            'notes': '<p>Shared marking note.</p>',
        })
        student = self.env['res.partner'].create({
            'name': 'Marking context parity student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': submission_answer,
            'out_of_marks': resource.marks,
        })

        test_context = resource._build_ai_feedback_ctx(include_reasoning=True)
        submission_context = submission._build_ai_feedback_ctx(include_reasoning=True)
        expected_submission_context = dict(test_context)
        expected_submission_context['student_answer_html'] = submission.answer
        expected_sources = dict(test_context['image_sources'])
        expected_sources['student_answer'] = submission.answer
        expected_submission_context['image_sources'] = expected_sources

        self.assertEqual(submission_context, expected_submission_context)

    def test_resource_and_submission_feedback_share_comparison_and_reasoning_html(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        student = self.env['res.partner'].create({
            'name': 'Marking result parity student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p>Real submission answer.</p>',
        })
        audit = {
            'summary': 'Compared against the benchmark.',
            'comparisons': [],
            'target_maximum': 30,
            'score_lower': 20,
            'score_upper': 20,
            'score_estimate': 20,
            'confidence': 'MEDIUM',
            'anomaly_count': 1,
            'anomaly_severity': 0.0,
        }
        result = {
            'feedback_html': '<p>Teacher feedback.</p>',
            'score': 20,
            'sample_comparison_audit': audit,
            'reasoning_text': 'Reasoning from multiple calls.',
        }

        with patch.object(type(resource), 'write', autospec=True) as resource_write:
            resource._apply_ai_feedback_result(result)
        with patch.object(type(submission), 'write', autospec=True) as submission_write:
            submission._apply_ai_feedback_result(result)

        resource_vals = resource_write.call_args.args[1]
        submission_vals = submission_write.call_args.args[1]
        self.assertEqual(resource_vals['ai_feedback'], submission_vals['feedback'])
        self.assertEqual(resource_vals['ai_score'], submission_vals['score'])
        self.assertIn('Estimated score: 20/30; range: 20-20/30; confidence: MEDIUM;', resource_vals['ai_feedback'])
        self.assertIn('<details><summary>Reasoning</summary>', resource_vals['ai_feedback'])
        self.assertTrue(resource_vals['ai_feedback'].endswith('</details>'))

    def test_resource_and_submission_use_the_same_model_override_route(self):
        resource = self.env['aps.resources'].create({
            'name': 'Ordinary marking route',
            'marks': 30,
            'ai_model_ids': [(6, 0, [self.model.id])],
            'ai_answer': '<p>Test answer.</p>',
        })
        student = self.env['res.partner'].create({
            'name': 'Model route parity student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'answer': '<p>Submission answer.</p>',
            'out_of_marks': resource.marks,
        })
        resource_run = self.env['aps.ai.run'].create({
            'resource_id': resource.id,
            'requested_by_id': self.env.user.id,
            'override_model_id': self.model.id,
        })
        submission_run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
            'override_model_id': self.model.id,
        })

        with patch.object(
            type(self.model),
            'generate_multi_model_feedback',
            autospec=True,
            return_value={'feedback_html': '<p>Generated.</p>'},
        ) as generate:
            resource._generate_ai_feedback_result(ai_run=resource_run)
            submission._generate_ai_feedback_result(ai_run=submission_run)

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args_list[0].args[1], resource)
        self.assertEqual(generate.call_args_list[1].args[1], submission)
        self.assertEqual(generate.call_args_list[0].kwargs['ai_run'], resource_run)
        self.assertEqual(generate.call_args_list[1].kwargs['ai_run'], submission_run)

    def test_only_linked_sample_answer_tagged_resources_are_benchmarks(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        sample_tag = self.env['aps.resource.tags'].create({'name': '  sample answer  '})
        other_tag = self.env['aps.resource.tags'].create({'name': 'Reference'})
        tagged_sample, untagged_sample = self.env['aps.resources'].create([
            {
                'name': 'Tagged benchmark',
                'marks': 30,
                'weight': 20,
                'notes': '<p>Tagged sample answer.</p>',
                'tag_ids': [(6, 0, [sample_tag.id])],
            },
            {
                'name': 'Ordinary linked resource',
                'marks': 30,
                'weight': 29,
                'notes': '<p>This must not be compared.</p>',
                'tag_ids': [(6, 0, [other_tag.id])],
            },
        ])
        resource.write({'supporting_resource_ids': [(6, 0, [tagged_sample.id, untagged_sample.id])]})

        benchmarks = resource._get_sample_comparison_benchmarks()

        self.assertEqual(benchmarks.ids, [tagged_sample.id])

    def test_sample_comparison_benchmarks_are_ordered_by_ascending_weight(self):
        resource = self._create_resource(self._create_prompt())
        sample_tag = self._get_sample_answer_tag()
        samples = self.env['aps.resources'].create([
            {
                'name': 'Stronger benchmark',
                'marks': 30,
                'weight': 26,
                'notes': '<p>Stronger sample answer.</p>',
                'tag_ids': [(6, 0, [sample_tag.id])],
            },
            {
                'name': 'Weakest benchmark',
                'marks': 30,
                'weight': 12,
                'notes': '<p>Weakest sample answer.</p>',
                'tag_ids': [(6, 0, [sample_tag.id])],
            },
            {
                'name': 'Middle benchmark',
                'marks': 30,
                'weight': 19,
                'notes': '<p>Middle sample answer.</p>',
                'tag_ids': [(6, 0, [sample_tag.id])],
            },
        ])
        resource.write({'supporting_resource_ids': [(6, 0, samples.ids)]})

        benchmarks = resource._get_sample_comparison_benchmarks()

        self.assertEqual(benchmarks.mapped('weight'), [12, 19, 26])

    def test_full_workflow_calls_all_samples_then_final_score(self):
        comparison_prompt = self._create_prompt()
        scaling_prompt = self._create_prompt('Use Sample Scaling')
        resource = self._create_resource(comparison_prompt)
        resource.write({'ai_prompt_ids': [(4, scaling_prompt.id)]})
        samples = self.env['aps.resources'].create([
            {
                'name': 'Benchmark %s' % score,
                'marks': 30,
                'weight': score,
                'notes': '<p>Benchmark answer %s.</p>' % score,
                'answer': '<p>Rubric.</p>',
                'tag_ids': [(6, 0, [self._get_sample_answer_tag().id])],
            }
            for score in (15, 20, 25, 29)
        ])
        resource.write({'supporting_resource_ids': [(6, 0, samples.ids)]})
        calls = []

        def fake_generate(model, record, ai_run=None, feedback_context=None):
            calls.append(feedback_context)
            benchmark_text = html2plaintext(feedback_context.get('notes') or '')
            if 'Benchmark answer' in benchmark_text:
                score = int(benchmark_text.rsplit(' ', 1)[-1].rstrip('.'))
                result = 'BETTER' if score <= 20 else 'WORSE'
                raw = '{"result": "%s", "reason": "Compared rubric coverage."}' % result
            else:
                raw = '{"score": 23, "confidence": "HIGH", "feedback": "Good evidence; develop the next point.", "reason": "Consistent with nearby examples."}'
            return {
                'feedback_html': '<p>Feedback.</p>',
                'score': None if 'Benchmark answer' in benchmark_text else 23,
                'score_comment': False,
                'prompt_tokens': 10,
                'completion_tokens': 5,
                'estimated_cost': 0.001,
                'model_id': model.id,
                'model_name': model.display_name,
                'raw_content': raw,
            }

        with patch.object(type(self.model), 'generate_feedback', autospec=True, side_effect=fake_generate):
            result = resource._generate_sample_comparison_feedback()

        self.assertEqual(len(calls), 5)
        self.assertTrue(all(not context['out_of_marks'] for context in calls[:4]))
        self.assertEqual(result['score'], 23)
        self.assertTrue(result['sample_comparison_audit']['prompt_conflict'])
        self.assertEqual(len(result['sample_comparison_audit']['comparisons']), 4)
        self.assertIn('AI MARKING COMPARISON', str(result['sample_comparison_audit_html']))
        self.assertIn('AI FINAL MARK', str(result['sample_comparison_audit_html']))
        self.assertIn('Score: 23/30', str(result['sample_comparison_audit_html']))
        self.assertIn('Range: 20-25/30', str(result['sample_comparison_audit_html']))
        self.assertLess(
            str(result['sample_comparison_audit_html']).index('AI FINAL MARK'),
            str(result['sample_comparison_audit_html']).index('AI MARKING COMPARISON'),
        )

    def test_malformed_comparison_falls_back_to_ordinary_marking(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        sample = self.env['aps.resources'].create({
            'name': 'Benchmark', 'marks': 30, 'weight': 20,
            'notes': '<p>Benchmark answer.</p>',
            'tag_ids': [(6, 0, [self._get_sample_answer_tag().id])],
        })
        resource.write({'child_ids': [(6, 0, sample.ids)]})
        call_contexts = []

        def fake_generate(model, record, ai_run=None, feedback_context=None):
            call_contexts.append(feedback_context)
            if feedback_context.get('notes') == sample.notes:
                raw = 'not json'
                score = None
            else:
                raw = '{"score": 18, "summary": "Fallback feedback."}'
                score = 18
            return {
                'feedback_html': '<p>Fallback feedback.</p>', 'score': score,
                'score_comment': False, 'prompt_tokens': 1, 'completion_tokens': 1,
                'estimated_cost': 0.0, 'model_id': model.id,
                'model_name': model.display_name, 'raw_content': raw,
            }

        with patch.object(type(self.model), 'generate_feedback', autospec=True, side_effect=fake_generate):
            result = resource._generate_sample_comparison_feedback()

        self.assertEqual(result['score'], 18)
        self.assertIn('fallback_reason', result['sample_comparison_audit'])
        self.assertFalse(any(
            (prompt.prompt_name or '').casefold() == 'use sample comparison'
            for prompt in call_contexts[-1]['prompt_ids']
        ))

    def test_background_resource_worker_dispatches_comparison(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        run = self.env['aps.ai.run'].create({
            'resource_id': resource.id,
            'requested_by_id': self.env.user.id,
        })
        result = {
            'score': 18,
            'model_id': self.model.id,
            'model_name': self.model.display_name,
            'sample_comparison_audit_html': '<p>comparison evidence</p>',
            'reasoning_text': 'Reasoning from all marking calls.',
        }
        with patch.object(type(run), '_write_progress', autospec=True) as write_progress, \
                patch.object(type(run), '_commit_background_work', autospec=True), \
                patch.object(type(resource), '_uses_sample_comparison', autospec=True, return_value=True), \
                patch.object(type(resource), '_generate_sample_comparison_feedback', autospec=True, return_value=result) as generate, \
                patch.object(type(resource), '_apply_ai_feedback_result', autospec=True) as apply_result, \
                patch.object(type(resource), '_post_sample_comparison_audit_note', autospec=True) as post_audit:
            run._process_background_record(time.perf_counter())
        generate.assert_called_once_with(resource.with_user(run.requested_by_id), ai_run=run)
        self.assertEqual(apply_result.call_args.args[1], result)
        self.assertEqual(
            write_progress.call_args_list[-1].args[1]['thinking_text'],
            'Reasoning from all marking calls.',
        )
        post_audit.assert_called_once_with(resource.with_user(run.requested_by_id), result)

    def test_background_submission_worker_dispatches_comparison(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        student = self.env['res.partner'].create({
            'name': 'Sample comparison student',
            'is_student': True,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'submission_name': 'Sample comparison submission',
        })
        run = self.env['aps.ai.run'].create({
            'submission_id': submission.id,
            'requested_by_id': self.env.user.id,
        })
        result = {
            'score': 18,
            'model_id': self.model.id,
            'model_name': self.model.display_name,
            'sample_comparison_audit_html': '<p>comparison evidence</p>',
            'reasoning_text': 'Reasoning from all marking calls.',
        }
        with patch.object(type(run), '_write_progress', autospec=True) as write_progress, \
                patch.object(type(run), '_commit_background_work', autospec=True), \
                patch.object(type(submission), '_uses_sample_comparison', autospec=True, return_value=True), \
                patch.object(type(submission), '_generate_sample_comparison_feedback', autospec=True, return_value=result) as generate, \
                patch.object(type(submission), '_apply_ai_feedback_result', autospec=True) as apply_result, \
                patch.object(type(submission), '_finalize_ai_marking_success', autospec=True) as finalize:
            run._process_background_record(time.perf_counter())
        generate.assert_called_once_with(submission.with_user(run.requested_by_id), ai_run=run)
        self.assertEqual(apply_result.call_args.args[1], result)
        self.assertEqual(
            write_progress.call_args_list[-1].args[1]['thinking_text'],
            'Reasoning from all marking calls.',
        )
        finalize.assert_called_once_with(
            submission.with_user(run.requested_by_id),
            result,
            request_origin=run.request_origin,
            run=run,
        )
    def test_comparison_audit_does_not_repeat_score_already_in_benchmark_name(self):
        resource = self.env['aps.resources']
        audit_html = resource._build_sample_comparison_audit_html({
            'summary': 'Compared against one benchmark.',
            'comparisons': [{
                'benchmark_name': 'English Language B 🢒 Exam Papers 🢒 Q11 🢒 Sample Answer (26/30)',
                'official_score': 26,
                'maximum': 30,
                'result': 'WORSE',
            }],
            'target_maximum': 30,
        })

        text = html2plaintext(str(audit_html))
        self.assertIn('Sample Answer (26/30): WORSE', text)
        self.assertNotIn('(26/30) (26/30)', text)

    def test_submission_completion_note_combines_comparison_audit_and_final_mark(self):
        submission = self.env['aps.resource.submission'].new({})
        resource = self.env['aps.resources']
        audit_html = resource._build_sample_comparison_audit_html({
            'summary': 'Compared against one benchmark.',
            'comparisons': [],
            'target_maximum': 30,
            'score_lower': 0,
            'score_upper': 16,
            'score_estimate': 8,
            'confidence': 'MEDIUM',
            'anomaly_count': 0,
            'anomaly_severity': 0.0,
            'final_score': 8,
            'final_confidence': 'MEDIUM',
            'final_reason': 'Within the benchmark range.',
            'final_feedback': '<p>Clear feedback.</p>',
        })
        body = submission._build_ai_completion_note_body({
            'model_name': self.model.display_name,
            'estimated_cost': 0.01,
            'sample_comparison_audit_html': audit_html,
        }, prefix_text='Manual AI marking completed successfully.')

        self.assertTrue(body.startswith('<p><strong>AI FINAL MARK</strong></p>'))
        self.assertIn('AI MARKING COMPARISON', body)
        self.assertIn('AI FINAL MARK', body)
        self.assertEqual(body.count('AI FINAL MARK'), 1)
        self.assertLess(body.index('AI FINAL MARK'), body.index('Manual AI marking completed successfully.'))
        self.assertNotIn('Clear feedback.', body)

    def test_invalid_final_scores_use_estimate_and_schedule_review(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        samples = self.env['aps.resources'].create([
            {
                'name': 'Benchmark %s' % score,
                'marks': 30,
                'weight': score,
                'notes': '<p>Benchmark answer %s.</p>' % score,
                'tag_ids': [(6, 0, [self._get_sample_answer_tag().id])],
            }
            for score in (15, 20, 25)
        ])
        resource.write({'child_ids': [(6, 0, samples.ids)]})

        def fake_generate(model, record, ai_run=None, feedback_context=None):
            if 'Benchmark answer' in html2plaintext(feedback_context.get('notes') or ''):
                score = int(html2plaintext(feedback_context['notes']).rsplit(' ', 1)[-1].rstrip('.'))
                classification = 'BETTER' if score <= 20 else 'WORSE'
                raw = '{"result":"%s","reason":"Relative quality evidence."}' % classification
                returned_score = None
            else:
                raw = '{"score":29,"confidence":"HIGH","feedback":"Specific feedback.","reason":"Outside the range."}'
                returned_score = 29
            return {
                'feedback_html': '<p>Feedback.</p>', 'score': returned_score,
                'score_comment': False, 'prompt_tokens': 1, 'completion_tokens': 1,
                'estimated_cost': 0.001, 'model_id': model.id,
                'model_name': model.display_name, 'raw_content': raw,
            }

        with patch.object(type(self.model), 'generate_feedback', autospec=True, side_effect=fake_generate):
            result = resource._generate_sample_comparison_feedback()

        self.assertTrue(result['sample_comparison_audit']['review_required'])
        self.assertEqual(result['score'], result['sample_comparison_audit']['score_estimate'])
        with patch.object(type(resource), 'activity_schedule', autospec=True) as schedule:
            resource._post_sample_comparison_audit_note(result)
        self.assertTrue(schedule.called)
        self.assertEqual(schedule.call_args.args[1], 'mail.mail_activity_data_todo')
        self.assertEqual(schedule.call_args.kwargs['summary'], 'Review AI sample-comparison mark')

    def test_submission_feedback_appends_collapsible_comparison_and_reasoning(self):
        submission = self.env['aps.resource.submission'].new({'out_of_marks': 30})
        audit = {
            'summary': 'Compared against the benchmark.',
            'comparisons': [],
            'target_maximum': 30,
            'score_lower': 20,
            'score_upper': 20,
            'score_estimate': 20,
            'confidence': 'MEDIUM',
            'anomaly_count': 1,
            'anomaly_severity': 0.0,
        }

        with patch.object(type(submission), 'write', autospec=True) as write:
            submission._apply_ai_feedback_result({
                'feedback_html': '<p>Teacher feedback.</p>',
                'score': 20,
                'sample_comparison_audit': audit,
                'sample_comparison_audit_html': '<p>Unused fallback audit.</p>',
                'reasoning_text': 'First call.\nSecond call <thinking>private text</thinking>.',
            })

        feedback_html = write.call_args.args[1]['feedback']
        self.assertIn('<details><summary>AI Marking Comparison</summary>', feedback_html)
        self.assertLess(
            feedback_html.index('AI FINAL MARK'),
            feedback_html.index('Estimated score:'),
        )
        self.assertIn(
            'Estimated score: 20/30; range: 20-20/30; confidence: MEDIUM; anomalies: 1 (severity 0).',
            feedback_html,
        )
        self.assertIn('<details><summary>Reasoning</summary>', feedback_html)
        self.assertIn('Second call &lt;thinking&gt;private text&lt;/thinking&gt;.', feedback_html)
        self.assertEqual(feedback_html.count('<details>'), 2)
        self.assertLess(
            feedback_html.index('AI Marking Comparison'),
            feedback_html.index('Reasoning'),
        )

    def test_sample_comparison_result_combines_reasoning_from_all_calls(self):
        prompt = self._create_prompt()
        resource = self._create_resource(prompt)
        sample_tag = self._get_sample_answer_tag()
        samples = self.env['aps.resources'].create([
            {
                'name': 'Benchmark %s' % score,
                'marks': 30,
                'weight': score,
                'notes': '<p>Benchmark answer %s.</p>' % score,
                'tag_ids': [(6, 0, [sample_tag.id])],
            }
            for score in (15, 25)
        ])
        resource.write({'child_ids': [(6, 0, samples.ids)]})

        def fake_generate(model, record, ai_run=None, feedback_context=None):
            answer = html2plaintext(feedback_context.get('notes') or '')
            if 'Benchmark answer 15' in answer:
                return {
                    'raw_content': '{"result":"BETTER","reason":"Higher than the lower sample."}',
                    'reasoning_text': 'Reasoning for benchmark 15.',
                }
            if 'Benchmark answer 25' in answer:
                return {
                    'raw_content': '{"result":"WORSE","reason":"Lower than the higher sample."}',
                    'reasoning_text': 'Reasoning for benchmark 25.',
                }
            return {
                'feedback_html': '<p>Marked feedback.</p>',
                'score': 20,
                'score_comment': False,
                'raw_content': '{"score":20,"feedback":"Marked feedback."}',
                'reasoning_text': 'Reasoning for the final mark.',
            }

        with patch.object(type(self.model), 'generate_feedback', autospec=True, side_effect=fake_generate):
            result = resource._generate_sample_comparison_feedback()

        self.assertEqual(result['reasoning_text'].count('Reasoning for benchmark'), 2)
        self.assertIn('Reasoning for benchmark 15.', result['reasoning_text'])
        self.assertIn('Reasoning for benchmark 25.', result['reasoning_text'])
        self.assertIn('Reasoning for the final mark.', result['reasoning_text'])