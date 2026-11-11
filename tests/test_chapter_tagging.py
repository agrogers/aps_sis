import json
import time
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.resources.chapter_tagging import (
    chapter_labels,
    chapter_markdown,
    chapter_summary_candidates,
    chapter_text,
)


class TestChapterTagging(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['aps.ai.provider'].create({
            'name': 'Chapter tagging test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.model = cls.env['aps.ai.model'].create({
            'name': 'Chapter tagging test model',
            'model_key': 'test/chapter-tagging',
            'provider_id': cls.provider.id,
        })
        cls.subject = cls.env['aps.subject'].create({'name': 'Chapter tagging subject'})
        cls.summary = cls.env['aps.resources'].create({
            'name': 'Textbook summary',
            'notes': '<p>Ch01: Cells</p><p>Chapter 2: Plants</p><p>Ch03: Animals</p><p>Ch04: Ecology</p>',
            'tag_ids': [(4, cls.env.ref('aps_sis.tag_textbook_chapter_summary').id)],
            'subjects': [(6, 0, cls.subject.ids)],
        })

    def _resource(self, **values):
        return self.env['aps.resources'].create({
            'name': 'Chapter tagging resource',
            'question': '<p>Describe a cell.</p>',
            'subjects': [(6, 0, self.subject.ids)],
            'ai_model_ids': [(6, 0, self.model.ids)],
            **values,
        })

    def _queue(self, resources):
        wizard = self.env['aps.chapter.tagging.wizard'].create({
            'resource_ids': [(6, 0, resources.ids)],
            'summary_id': self.summary.id,
        })
        with patch.object(type(self.env['aps.ai.run']), '_queue_background_processing') as queue:
            action = wizard.action_tag_chapters()
        self.assertEqual(queue.call_count, len(resources))
        self.assertEqual(action['tag'], 'aps_chapter_tagging_progress')
        self.assertEqual(action['params']['run_labels'], resources.mapped('display_name'))
        self.assertEqual(action['params']['run_model'], 'aps.ai.run')
        return self.env['aps.ai.run'].browse(action['params']['run_ids'])

    def _process(self, run, chapters):
        response = {
            'response_json': {'choices': [{'message': {'content': json.dumps({'chapters': chapters})}}]},
            'prompt_tokens': 10, 'completion_tokens': 5, 'estimated_cost': 0.001,
        }
        with (
            patch.object(type(self.model), '_get_generation_candidates', return_value=self.model),
            patch.object(type(self.model), '_execute_logged_router_call', return_value=response) as call,
            patch.object(type(run), '_write_progress', autospec=True, side_effect=lambda record, vals: record.write(vals)),
        ):
            run._process_specialised_background(time.perf_counter())
        return call.call_args

    def test_text_extraction_excludes_images_and_non_text_content(self):
        self.assertEqual(chapter_text(
            '<p>Cell <b>structure</b> &amp; function</p>'
            '<img src="data:image/png;base64,IMAGE" alt="not evidence">'
            '<svg><text>not evidence</text></svg><script>not evidence</script>'
        ), 'Cell structure & function')
        self.assertFalse(chapter_text('<p>&nbsp;<img src="/web/image/123"></p>'))
        self.assertFalse(chapter_text(False))

    def test_prompt_text_preserves_html_outline_structure_as_markdown(self):
        self.summary.write({
            'notes': (
                '<h1>UNIT 1: Organisms and Life Processes</h1>'
                '<h2>Chapter 1: Life Processes</h2>'
                '<ul><li>Cell structure</li><li>Movement of substances</li></ul>'
            ),
        })
        resource = self._resource(
            question=(
                '<h2>Question 1</h2><p>Describe cell structure.</p>'
                '<ul><li>Nucleus</li><li>Cell membrane</li></ul>'
            ),
        )
        run = self._queue(resource)

        self.assertIn('# UNIT 1: Organisms and Life Processes', run.chapter_summary_text)
        self.assertIn('## Chapter 1: Life Processes', run.chapter_summary_text)
        self.assertIn('- Cell structure', run.chapter_summary_text)
        self.assertIn('Question:\n## Question 1', run.chapter_input_text)
        self.assertIn('- Cell membrane', run.chapter_input_text)
        self.assertNotIn('<h1>', run.chapter_summary_text)
        self.assertNotIn('<ul>', run.chapter_input_text)

    def test_chapter_labels_are_canonical(self):
        self.assertEqual(
            chapter_labels('Chapter 1: Cells; CH02: Plants; Ch 23: Ecology; Chapter 1 repeated'),
            {'Ch01', 'Ch02', 'Ch23'},
        )

    def test_action_creates_one_run_per_resource_and_snapshots_text(self):
        resources = self._resource(answer='<p>Cell membrane.</p>', notes='<p>Biology.</p>')
        resources |= self._resource(question='<p><img src="/web/image/123"></p>')
        runs = self._queue(resources)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs.mapped('resource_id'), resources)
        self.assertTrue(all(run.processor_key == 'chapter_tagging' for run in runs))
        self.assertEqual(
            runs[0]._get_processor_display_name(),
            'Chapter tagging: %s' % resources[0].display_name,
        )
        statuses = self.env['aps.ai.run'].action_get_run_statuses(runs.ids)
        self.assertEqual([status['id'] for status in statuses], runs.ids)
        self.assertEqual([status['state'] for status in statuses], ['queued', 'queued'])
        self.assertEqual(runs[0].chapter_input_fields, 'Question, Model Answer, Note')
        self.assertIn('Cell membrane.', runs[0].chapter_input_text)
        self.assertEqual(runs[1].chapter_input_fields, 'None')
        self.assertFalse(runs[1].chapter_input_text)
        resources[0].write({'question': '<p>Changed after queueing.</p>'})
        self.assertIn('Describe a cell.', runs[0].chapter_input_text)

    def test_wizard_defaults_keep_selection_and_do_not_guess_between_textbooks(self):
        resource = self._resource()
        other_subject = self.env['aps.subject'].create({'name': 'Different summary subject'})
        self.env['aps.resources'].create({
            'name': 'Different-subject textbook summary',
            'notes': '<p>Ch01: Different subject</p>',
            'tag_ids': [(4, self.env.ref('aps_sis.tag_textbook_chapter_summary').id)],
            'subjects': [(6, 0, other_subject.ids)],
        })
        wizard_model = self.env['aps.chapter.tagging.wizard'].with_context(
            active_model='aps.resources', active_ids=resource.ids,
        )
        defaults = wizard_model.default_get([
            'resource_ids', 'summary_id', 'eligible_summary_ids',
        ])
        self.assertEqual(defaults['resource_ids'], [(6, 0, resource.ids)])
        self.assertEqual(defaults['summary_id'], self.summary.id)
        self.assertEqual(
            defaults['eligible_summary_ids'], [(6, 0, self.summary.ids)],
        )
        wizard = wizard_model.create({
            'resource_ids': [(6, 0, resource.ids)],
            'summary_id': self.summary.id,
        })
        self.assertEqual(wizard.eligible_summary_ids, self.summary)
        self.summary.copy({'name': 'Another textbook'})
        defaults = wizard_model.default_get(['summary_id'])
        self.assertFalse(defaults.get('summary_id'))

    def test_summary_lookup_matches_tag_display_name(self):
        same_name_tag = self.env['aps.resource.tags'].create({
            'name': 'Textbook Chapter Summary',
        })
        summary = self.env['aps.resources'].create({
            'name': 'Summary with separately created tag',
            'tag_ids': [(4, same_name_tag.id)],
            'subjects': [(6, 0, self.subject.ids)],
        })

        self.assertIn(summary, chapter_summary_candidates(self.env, self._resource()))

    def test_wizard_requires_a_summary_matching_every_resource_subject(self):
        other_subject = self.env['aps.subject'].create({'name': 'Other chapter tagging subject'})
        resources = self._resource() | self._resource(
            subjects=[(6, 0, other_subject.ids)],
        )
        wizard = self.env['aps.chapter.tagging.wizard'].create({
            'resource_ids': [(6, 0, resources.ids)],
            'summary_id': self.summary.id,
        })
        self.assertFalse(wizard.eligible_summary_ids)
        with self.assertRaisesRegex(UserError, 'share a subject with every selected resource'):
            wizard.action_tag_chapters()

    def test_runs_share_queue_lane_to_avoid_duplicate_tag_creation(self):
        runs = self._queue(self._resource() | self._resource())
        self.assertEqual(runs[0]._get_ai_queue_key(), runs[1]._get_ai_queue_key())
        self.assertEqual(runs[0]._get_ai_queue_key(), 'aps_sis:chapter_tagging')
        standard_run = self.env['aps.ai.run'].create({
            'resource_id': runs[0].resource_id.id,
            'requested_by_id': self.env.uid,
        })
        self.assertEqual(
            standard_run._get_ai_queue_key(),
            'record:aps.resources:%s' % standard_run.resource_id.id,
        )

    def test_summary_requires_text_and_chapter_labels(self):
        self.summary.write({'notes': '<p><img src="/web/image/123"></p>'})
        with self.assertRaises(UserError):
            self._queue(self._resource())

    def test_text_only_payload_ignores_marking_field_switches(self):
        resource = self._resource(
            question='<p>Describe a cell.</p><img src="data:image/png;base64,IMAGE">',
            answer='<p>Cell membrane.</p>', notes='<p>Biology.</p>',
            ai_use_question=False, ai_use_model_answer=False, ai_use_notes=False,
        )
        run = self._queue(resource)
        call = self._process(run, ['Ch01'])
        payload = call.args[0]
        self.assertTrue(all(isinstance(message['content'], str) for message in payload['messages']))
        text = payload['messages'][1]['content']
        self.assertIn('Cell membrane.', text)
        self.assertIn('Biology.', text)
        self.assertNotIn('IMAGE', text)
        self.assertNotIn('image_url', text)
        self.assertEqual(call.kwargs['related_record'], resource)
        self.assertEqual(run.state, 'completed')
        self.assertIn('Fields sent: Question, Model Answer, Note.', run.result_message)

    def test_tags_are_append_only_deduplicated_and_limited_to_three(self):
        existing = self.env['aps.resource.tags'].create([{'name': 'Keep me'}, {'name': 'Ch01'}])
        resource = self._resource(tag_ids=[(6, 0, existing.ids)])
        run = self._queue(resource)
        self._process(run, ['Ch01', 'Ch01', 'Ch02', 'Ch03', 'Ch04'])
        self.assertEqual(set(resource.tag_ids.mapped('name')), {'Keep me', 'Ch01', 'Ch02', 'Ch03'})
        self.assertIn('Added tags: Ch02, Ch03.', run.result_message)
        self.assertIn('Tags already present: Ch01.', run.result_message)
        self._process(run, ['Ch01', 'Ch02', 'Ch03'])
        self.assertNotIn('Added tags:', run.result_message)
        self.assertIn('Tags already present:', run.result_message)

    def test_no_match_is_logged_without_changing_tags(self):
        resource = self._resource()
        original_tags = resource.tag_ids
        run = self._queue(resource)
        self._process(run, [])
        self.assertEqual(resource.tag_ids, original_tags)
        self.assertIn('No textbook chapter matched', run.result_message)

    def test_invalid_responses_never_add_tags(self):
        resource = self._resource()
        run = self._queue(resource)
        for chapters in [['Ch01', 'Ch99'], 'Ch01', [1], [None]]:
            with self.subTest(chapters=chapters), self.assertRaises(UserError):
                self._process(run, chapters)
            self.assertFalse(resource.tag_ids)
        for response in [{}, [], {'chapters': None}]:
            with self.assertRaises(UserError):
                run._validate_chapter_response(response, {'Ch01'})

    def test_image_only_run_skips_provider_and_other_runs_continue(self):
        resources = self._resource(question='<img src="/web/image/123">', answer=False, notes=False)
        resources |= self._resource()
        runs = self._queue(resources)
        with (
            patch.object(type(self.model), '_execute_logged_router_call') as call,
            patch.object(type(runs), '_write_progress', autospec=True, side_effect=lambda record, vals: record.write(vals)),
        ):
            runs[0]._process_background()
        call.assert_not_called()
        self.assertEqual(runs[0].state, 'skipped')
        self.assertIn('No fields sent', runs[0].result_message)
        self._process(runs[1], ['Ch01'])
        self.assertEqual(runs[1].state, 'completed')

    def test_provider_failure_is_caught_and_does_not_stop_next_run(self):
        resources = self._resource() | self._resource()
        runs = self._queue(resources)
        with (
            patch.object(type(self.model), '_get_generation_candidates', return_value=self.model),
            patch.object(type(self.model), '_execute_logged_router_call', side_effect=UserError('Provider unavailable')),
            patch.object(type(runs), '_write_progress', autospec=True, side_effect=lambda record, vals: record.write(vals)),
            patch.object(type(runs), '_recover_background_failure') as recover,
        ):
            runs[0]._process_background()
        recover.assert_called_once()
        self.assertIn('Provider unavailable', str(recover.call_args.args[0]))
        self.assertEqual(runs[0].chapter_input_fields, 'Question')
        self.assertFalse(resources[0].tag_ids)
        self._process(runs[1], ['Ch02'])
        self.assertEqual(runs[1].state, 'completed')
