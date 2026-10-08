import base64
from io import BytesIO
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.exceptions import UserError, ValidationError


class TestExamPaperImport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.resource = self.env['aps.resources'].create({'name': 'PH1-1P-202104'})

    def _attachment(self, name, content=b'%PDF-1.4'):
        return self.env['ir.attachment'].create({
            'name': name,
            'type': 'binary',
            'datas': content.hex(),
            'mimetype': 'application/pdf',
            'res_model': 'aps.resources',
            'res_id': self.resource.id,
        })

    def test_multi_record_unlink_deletes_rendered_page_attachments(self):
        import_job = self.env['aps.exam.paper.import'].create({
            'name': 'Multi-page unlink',
            'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('multi-unlink-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('multi-unlink-rms.pdf').id,
        })
        attachments = self.env['ir.attachment'].create([
            {
                'name': 'multi-unlink-page-one.png',
                'type': 'binary',
                'datas': 'aGVsbG8=',
                'mimetype': 'image/png',
            },
            {
                'name': 'multi-unlink-page-two.png',
                'type': 'binary',
                'datas': 'aGVsbG8=',
                'mimetype': 'image/png',
            },
        ])
        pages = self.env['aps.exam.paper.page'].create([
            {
                'import_id': import_job.id,
                'document_type': 'question',
                'page_number': page_number,
                'render_dpi': 150,
                'attachment_id': attachment.id,
            }
            for page_number, attachment in enumerate(attachments, start=1)
        ])

        pages.unlink()

        self.assertFalse(pages.exists())
        self.assertFalse(attachments.exists())

    def test_attachment_tokens_are_case_insensitive(self):
        self._attachment('Paper_QUE.pdf')
        self._attachment('Paper_RMS.pdf')
        job = self.env['aps.exam.paper.import'].create_from_resource(self.resource)
        self.assertEqual(job.question_attachment_id.name, 'Paper_QUE.pdf')
        self.assertEqual(job.mark_scheme_attachment_id.name, 'Paper_RMS.pdf')
        self.assertEqual(job.state, 'uploaded')

    def test_attachment_selection_requires_one_of_each(self):
        self._attachment('Paper_QUE.pdf')
        with self.assertRaises(UserError):
            self.env['aps.exam.paper.import'].create_from_resource(self.resource)

    def test_crop_bounds_remove_right_and_bottom_margins(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 1, 'width': 1000, 'height': 1500,
        })

        left, top, right, bottom = importer._crop_bounds({'y1': 0.1}, page, {})

        self.assertEqual((left, top, right, bottom), (75, 150, 925, 1400))

    def test_short_manual_crop_extends_to_next_section_start(self):
        importer = self.env['aps.exam.paper.import']
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Short manual crop paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('short-crop-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('short-crop-rms.pdf').id,
        })
        sections = self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': 'Q1a',
                'display_label': 'Q1a',
                'question_regions': [{
                    'page_number': 1, 'x1': 75, 'y1': 100, 'x2': 925, 'y2': 190,
                    'coordinate_system': 'pixels', 'manual': True,
                }],
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': 'Q1b',
                'display_label': 'Q1b',
                'question_regions': [{
                    'page_number': 1, 'x1': 75, 'y1': 350, 'x2': 925, 'y2': 500,
                    'coordinate_system': 'pixels', 'manual': True,
                }],
            },
        ])
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 1, 'width': 1000, 'height': 1500,
        })

        next_y = importer._next_section_region_y(sections[0], 'question', page, sections[0].question_regions[0])
        bounds = importer._crop_bounds(
            sections[0].question_regions[0], page, {}, next_section_y=next_y,
        )

        self.assertEqual(next_y, 350)
        self.assertEqual(bounds, (75, 100, 925, 350))

    def test_inherited_manual_crop_uses_next_section_after_region_owner(self):
        importer = self.env['aps.exam.paper.import']
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Inherited crop boundaries', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('inherited-crop-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('inherited-crop-rms.pdf').id,
        })
        sections = self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': '1',
                'display_label': 'Q1',
                'question_regions': [{
                    'page_number': 2, 'x1': 176, 'y1': 1220, 'x2': 223, 'y2': 1280,
                    'coordinate_system': 'pixels', 'manual': True,
                }],
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': '1/a',
                'display_label': 'Q1a',
                'question_regions': [{
                    'page_number': 2, 'x1': 250, 'y1': 1318, 'x2': 323, 'y2': 1383,
                    'coordinate_system': 'pixels', 'manual': True,
                }],
            },
            {
                'import_id': job.id, 'sequence': 3, 'source_key': '1/b',
                'display_label': 'Q1b',
                'question_regions': [{
                    'page_number': 2, 'x1': 250, 'y1': 1895, 'x2': 314, 'y2': 1969,
                    'coordinate_system': 'pixels', 'manual': True,
                }],
            },
        ])
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 2, 'width': 2481, 'height': 3508,
        })

        parent_boundary = importer._next_section_region_y(
            sections[1], 'question', page, sections[0].question_regions[0],
        )
        child_boundary = importer._next_section_region_y(
            sections[2], 'question', page, sections[1].question_regions[0],
        )

        self.assertEqual(parent_boundary, 1318)
        self.assertEqual(child_boundary, 1895)

    def test_manual_crop_at_minimum_height_keeps_its_saved_bottom(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 1, 'width': 1000, 'height': 1500,
        })

        bounds = importer._crop_bounds(
            {'manual': True, 'x1': 75, 'y1': 100, 'x2': 925, 'y2': 250},
            page, {}, next_section_y=350,
        )

        self.assertEqual(bounds, (75, 100, 925, 250))

    def test_region_editor_returns_page_picker_defaults(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Region picker paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('picker-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('picker-rms.pdf').id,
        })
        question_attachment = self.env['ir.attachment'].create({
            'name': 'question-page.png', 'type': 'binary', 'datas': b'aGVsbG8=',
            'mimetype': 'image/png',
        })
        self.env['aps.exam.paper.page'].create({
            'import_id': job.id, 'document_type': 'question', 'page_number': 2,
            'render_dpi': 150, 'width': 1000, 'height': 1500,
            'attachment_id': question_attachment.id,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': 'picker',
            'display_label': 'Q1',
            'question_regions': [{
                'page_number': 2, 'x1': 100, 'y1': 120, 'x2': 900, 'y2': 500,
            }],
        })

        data = section.get_region_editor_data()

        self.assertEqual(data['pages']['question'][0]['page_number'], 2)
        self.assertEqual(
            data['pages']['question'][0]['default_region'],
            {'x1': 75, 'y1': 85, 'x2': 925, 'y2': 1400},
        )
        self.assertEqual(
            data['regions']['question'][0]['default_region'],
            {'x1': 75, 'y1': 85, 'x2': 925, 'y2': 1400},
        )

    def test_individual_page_analysis_returns_progress_dialog_action(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Single page analysis paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('single-page-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('single-page-rms.pdf').id,
        })
        page = self.env['aps.exam.paper.page'].create({
            'import_id': job.id, 'document_type': 'question', 'page_number': 1,
            'render_dpi': 150, 'attachment_id': self._attachment('single-page.png').id,
        })
        run = MagicMock()
        run.id = 731

        with patch.object(type(job), '_create_page_analysis_run', return_value=run) as create_run:
            action = page.action_analyse_page_with_ai()

        create_run.assert_called_once_with(
            page,
            model=job.single_page_ai_model_id or job.ai_model_id,
        )
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'aps_exam_page_analysis_progress')
        self.assertEqual(action['params']['run_id'], run.id)
        self.assertEqual(action['params']['run_model'], 'aps.ai.run')

    def test_region_editor_returns_previous_and_next_sections(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Navigation paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('navigation-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('navigation-rms.pdf').id,
        })
        sections = self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': 'one',
                'display_label': 'Q1',
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': 'two',
                'display_label': 'Q2',
            },
            {
                'import_id': job.id, 'sequence': 3, 'source_key': 'three',
                'display_label': 'Q3',
            },
        ])

        data = sections[1].get_region_editor_data()

        self.assertEqual(data['navigation']['position'], 2)
        self.assertEqual(data['navigation']['count'], 3)
        self.assertEqual(data['navigation']['previous']['id'], sections[0].id)
        self.assertEqual(data['navigation']['previous']['label'], 'Q1')
        self.assertEqual(data['navigation']['next']['id'], sections[2].id)
        self.assertEqual(data['navigation']['next']['label'], 'Q3')

        first_navigation = sections[0].get_region_editor_data()['navigation']
        last_navigation = sections[2].get_region_editor_data()['navigation']
        self.assertFalse(first_navigation['previous'])
        self.assertFalse(last_navigation['next'])

    def test_region_editor_can_add_manual_regions_and_update_page_strings(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Manual region paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('manual-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('manual-rms.pdf').id,
        })
        attachments = self.env['ir.attachment'].create([
            {'name': 'question-page-1.png', 'type': 'binary', 'datas': b'aGVsbG8=', 'mimetype': 'image/png'},
            {'name': 'mark-page-3.png', 'type': 'binary', 'datas': b'aGVsbG8=', 'mimetype': 'image/png'},
        ])
        self.env['aps.exam.paper.page'].create([
            {
                'import_id': job.id, 'document_type': 'question', 'page_number': 1,
                'render_dpi': 150, 'width': 1000, 'height': 1500,
                'attachment_id': attachments[0].id,
            },
            {
                'import_id': job.id, 'document_type': 'mark_scheme', 'page_number': 3,
                'render_dpi': 150, 'width': 1000, 'height': 1500,
                'attachment_id': attachments[1].id,
            },
        ])
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': 'manual',
            'display_label': 'Q1',
        })

        section.save_region_editor_changes([], [
            {'document_type': 'question', 'page_number': 1,
             'bounds': {'x1': 10, 'y1': 20, 'x2': 900, 'y2': 1200}},
            {'document_type': 'mark_scheme', 'page_number': 3,
             'bounds': {'x1': 20, 'y1': 30, 'x2': 800, 'y2': 1100}},
        ])

        self.assertEqual(section.question_pages, '1')
        self.assertEqual(section.answer_pages, '3')
        self.assertTrue(section.question_regions[0]['manual_added'])
        self.assertEqual(section.question_regions[0]['document_type'], 'question')
        self.assertTrue(section.answer_regions[0]['manual'])

    def test_region_editor_removes_image_region_without_deleting_rendered_page(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Remove image paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('remove-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('remove-rms.pdf').id,
        })
        page_attachment = self.env['ir.attachment'].create({
            'name': 'remove-page.png', 'type': 'binary', 'datas': b'aGVsbG8=',
            'mimetype': 'image/png',
        })
        page = self.env['aps.exam.paper.page'].create({
            'import_id': job.id, 'document_type': 'question', 'page_number': 1,
            'render_dpi': 150, 'width': 1000, 'height': 1500,
            'attachment_id': page_attachment.id,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': 'remove',
            'display_label': 'Q1',
            'question_pages': '1',
            'question_regions': [{
                'page_number': 1, 'x1': 10, 'y1': 20, 'x2': 900, 'y2': 1200,
            }],
        })

        section.remove_region_editor_region('question', 0)

        self.assertFalse(section.question_regions)
        self.assertFalse(section.question_pages)
        self.assertTrue(page.exists())
        self.assertTrue(page_attachment.exists())

    def test_section_changes_reset_ocr_and_reopen_resource_build(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Changed section paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('changed-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('changed-rms.pdf').id,
            'state': 'completed', 'progress': 100,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': 'changed',
            'display_label': 'Q1', 'ocr_state': 'complete',
            'question_html': '<p>Old question OCR</p>',
            'answer_html': '<p>Old answer OCR</p>',
        })

        section.write({'source_key': 'manual-q1'})

        self.assertEqual(section.source_key, 'manual-q1')
        self.assertEqual(section.ocr_state, 'pending')
        self.assertFalse(section.question_html)
        self.assertFalse(section.answer_html)
        self.assertFalse(section.ocr_model_id)
        self.assertFalse(section.ocr_error)
        self.assertEqual(job.state, 'analysing')
        self.assertEqual(job.progress, 60)
        self.assertFalse(job.completed_at)

    def test_duplicate_section_gets_unique_key_and_fresh_generated_data(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Duplicate section paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('duplicate-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('duplicate-rms.pdf').id,
            'state': 'completed', 'progress': 100,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': '1a',
            'display_label': 'Q1a', 'root_key': 'Q1',
            'question_regions': [{'page_number': 1, 'x1': 1, 'y1': 2, 'x2': 10, 'y2': 20}],
            'answer_regions': [{'page_number': 2, 'x1': 1, 'y1': 2, 'x2': 10, 'y2': 20}],
            'resource_id': self.resource.id,
            'resource_key': str(self.resource.id),
            'question_html': '<p>Generated question</p>',
            'answer_html': '<p>Generated answer</p>',
            'ocr_state': 'complete',
        })

        duplicate = section.copy()

        self.assertEqual(duplicate.source_key, '1a_copy')
        self.assertEqual(duplicate.sequence, 2)
        self.assertEqual(duplicate.display_label, section.display_label)
        self.assertEqual(duplicate.question_regions, section.question_regions)
        self.assertFalse(duplicate.resource_id)
        self.assertFalse(duplicate.resource_key)
        self.assertFalse(duplicate.question_html)
        self.assertFalse(duplicate.answer_html)
        self.assertEqual(duplicate.ocr_state, 'pending')
        self.assertEqual(job.state, 'analysing')

        second_duplicate = section.copy()
        self.assertEqual(second_duplicate.source_key, '1a_copy2')

    def test_region_editor_rejects_wrong_page_and_invalid_bounds(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Invalid region paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('invalid-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('invalid-rms.pdf').id,
        })
        attachment = self.env['ir.attachment'].create({
            'name': 'invalid-page.png', 'type': 'binary', 'datas': b'aGVsbG8=',
            'mimetype': 'image/png',
        })
        self.env['aps.exam.paper.page'].create({
            'import_id': job.id, 'document_type': 'question', 'page_number': 1,
            'render_dpi': 150, 'width': 1000, 'height': 1500,
            'attachment_id': attachment.id,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': 'invalid',
            'display_label': 'Q1',
        })

        with self.assertRaises(ValidationError):
            section.save_region_editor_changes([], [{
                'document_type': 'question', 'page_number': 99,
                'bounds': {'x1': 0, 'y1': 0, 'x2': 10, 'y2': 10},
            }])
        with self.assertRaises(ValidationError):
            section.save_region_editor_changes([], [{
                'document_type': 'question', 'page_number': 1,
                'bounds': {'x1': 0, 'y1': 0, 'x2': 1001, 'y2': 10},
            }])

    def test_crop_regions_are_sorted_by_page_number(self):
        importer = self.env['aps.exam.paper.import']
        regions = [
            {'page_number': 4, 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 10},
            {'page_number': 2, 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 10},
            {'page_number': 2, 'x1': 0, 'y1': 1, 'x2': 10, 'y2': 11},
        ]
        indexed = list(enumerate(regions))
        indexed.sort(key=lambda item: (
            importer._region_page_number(item[1]) is None,
            importer._region_page_number(item[1]) or 0,
            item[0],
        ))
        self.assertEqual([region['page_number'] for _, region in indexed], [2, 2, 4])
        self.assertEqual(indexed[0][0], 1)
        self.assertEqual(indexed[1][0], 2)

    def test_resource_creation_is_idempotent(self):
        importer = self.env['aps.exam.paper.import']
        parent = self.resource
        first = importer._find_or_create_resource('Q1', parent)
        second = importer._find_or_create_resource('Q1', parent)
        self.assertEqual(first, second)

    def test_vision_prompt_requires_no_ocr_output(self):
        prompt = self.env['aps.exam.paper.import']._vision_system_prompt()
        self.assertIn('Do not transcribe OCR', prompt)
        self.assertIn('regions', prompt)
        self.assertIn('raw_label', prompt)
        self.assertIn('second pass', prompt)
        self.assertIn('question_summary', prompt)
        self.assertIn('no more than 20 words', prompt)
        self.assertIn('including labels printed in table headings', prompt)
        self.assertNotIn('exclude headers, footers', prompt)

    def test_resolve_page_labels_across_pages(self):
        resolver = self.env['aps.exam.paper.import']
        root, root_context, part_context = resolver._resolve_page_label('1', 'root', False, False)
        self.assertEqual(root, 'Q1')
        part, root_context, part_context = resolver._resolve_page_label('(a)', 'part', root_context, part_context)
        self.assertEqual(part, 'Q1a')
        subpart, _, _ = resolver._resolve_page_label('(i)', 'subpart', root_context, part_context)
        self.assertEqual(subpart, 'Q1a.i')

    def test_configured_identifiers_match_filename_rules_before_universal_rules(self):
        importer = self.env['aps.exam.paper.import']
        paper_attachment = self._attachment('Task_Paper_que.pdf')
        mark_attachment = self._attachment('Task_Paper_rms.pdf')
        job = importer.create({
            'name': 'Task Paper', 'resource_id': self.resource.id,
            'question_attachment_id': paper_attachment.id,
            'mark_scheme_attachment_id': mark_attachment.id,
        })
        other_attachment = self._attachment('Other_Paper_que.pdf')
        other_mark_attachment = self._attachment('Other_Paper_rms.pdf')
        other_job = importer.create({
            'name': 'Other Paper', 'resource_id': self.env['aps.resources'].create({
                'name': 'Other exam',
            }).id,
            'question_attachment_id': other_attachment.id,
            'mark_scheme_attachment_id': other_mark_attachment.id,
        })
        identifiers = self.env['aps.exam.paper.question.identifier']
        root_rule = identifiers.create({
            'sequence': 1, 'identifier_example': 'Task 1', 'hierarchy_level': '1',
        })
        paper_rule = identifiers.create({
            'sequence': 2, 'identifier_example': 'Task 1A',
            'filename_contains': 'Task_Paper', 'hierarchy_level': '2',
        })
        universal_rule = identifiers.create({
            'sequence': 3, 'identifier_example': 'Task 1A', 'hierarchy_level': '3',
        })
        identifiers.create({
            'sequence': 4, 'identifier_example': '(i)',
            'filename_contains': 'Task_Paper', 'hierarchy_level': '3',
        })
        page_image = self.env['ir.attachment'].create({
            'name': 'task-page.png', 'type': 'binary', 'datas': 'aGVsbG8=',
            'mimetype': 'image/png',
        })
        self.env['aps.exam.paper.page'].create({
            'import_id': job.id, 'document_type': 'question', 'page_number': 1,
            'render_dpi': 150, 'attachment_id': page_image.id, 'ai_state': 'complete',
            'ai_response': {'detections': [
                {'raw_label': 'Task 1', 'label_kind': 'root'},
                {'raw_label': 'Task 1A', 'label_kind': 'part'},
                {'raw_label': '(i)', 'label_kind': 'subpart'},
            ]},
        })

        root = job._resolve_configured_identifier('Task 1', False, False)
        paper_part = job._resolve_configured_identifier('Task 1A', root[1], root[2])
        other_part = other_job._resolve_configured_identifier('Task 1A', 'Task 1', False)
        detected = job._collect_page_detections('question')

        self.assertEqual(root, ('Task 1', 'Task 1', False, 1))
        self.assertEqual(paper_part, ('Task 1A', 'Task 1', ('configured', 'Task 1A'), 2))
        self.assertEqual(other_part, ('Task 1A', 'Task 1', False, 3))
        self.assertEqual(root_rule.regex_pattern, r'Task\ \d+')
        self.assertEqual(paper_rule.regex_pattern, r'Task\ \d+[A-Za-z]+')
        self.assertTrue(universal_rule.regex_pattern)
        self.assertEqual(identifiers._pattern_from_example('q1a'), r'q\d+[A-Za-z]+')
        self.assertEqual([item['label'] for item in detected], ['Task 1', 'Task 1A', 'Task 1A.i'])
        self.assertEqual([item['hierarchy_level'] for item in detected], [1, 2, 3])

    def test_detect_sections_distinguishes_empty_completed_analysis(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Empty analysis paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('empty-que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('empty-rms.pdf').id,
        })
        page_image = self.env['ir.attachment'].create({
            'name': 'empty-question-page.png', 'type': 'binary', 'datas': 'aGVsbG8=',
            'mimetype': 'image/png',
        })
        self.env['aps.exam.paper.page'].create({
            'import_id': job.id, 'document_type': 'question', 'page_number': 1,
            'render_dpi': 150, 'attachment_id': page_image.id, 'ai_state': 'complete',
            'ai_response': {'detections': []},
        })

        with self.assertRaisesRegex(UserError, 'no question labels could be resolved into sections'):
            job._build_sections_from_page_analysis()

    def test_question_and_mark_scheme_labels_share_canonical_keys(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Canonical Map Paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('Canonical_Map_que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('Canonical_Map_rms.pdf').id,
        })
        identifier_model = self.env['aps.exam.paper.question.identifier']
        identifier_model.create([
            {
                'sequence': 1, 'identifier_example': 'Task A1',
                'filename_contains': 'Canonical_Map', 'document_type': 'question',
                'hierarchy_level': '1', 'canonical_key_regex': r'A\d+',
            },
            {
                'sequence': 2, 'identifier_example': 'Task A1a',
                'filename_contains': 'Canonical_Map', 'document_type': 'question',
                'hierarchy_level': '2', 'canonical_key_regex': r'A\d+[A-Za-z]+',
            },
            {
                'sequence': 3, 'identifier_example': 'A1',
                'filename_contains': 'Canonical_Map', 'document_type': 'mark_scheme',
                'hierarchy_level': '1', 'canonical_key_regex': r'A\d+',
            },
            {
                'sequence': 4, 'identifier_example': 'A1a',
                'filename_contains': 'Canonical_Map', 'document_type': 'mark_scheme',
                'hierarchy_level': '2', 'canonical_key_regex': r'A\d+[A-Za-z]+',
            },
        ])
        question_image = self.env['ir.attachment'].create({
            'name': 'canonical-question.png', 'type': 'binary', 'datas': 'aGVsbG8=',
            'mimetype': 'image/png',
        })
        mark_scheme_image = self.env['ir.attachment'].create({
            'name': 'canonical-mark-scheme.png', 'type': 'binary', 'datas': 'aGVsbG8=',
            'mimetype': 'image/png',
        })
        page_model = self.env['aps.exam.paper.page']
        page_model.create([
            {
                'import_id': job.id, 'document_type': 'question', 'page_number': 1,
                'render_dpi': 150, 'attachment_id': question_image.id, 'ai_state': 'complete',
                'ai_response': {'detections': [
                    {'raw_label': 'Task A1', 'label_kind': 'root'},
                    {'raw_label': 'Task A1a', 'label_kind': 'part'},
                    {'raw_label': 'Task A1b', 'label_kind': 'part'},
                ]},
            },
            {
                'import_id': job.id, 'document_type': 'mark_scheme', 'page_number': 1,
                'render_dpi': 150, 'attachment_id': mark_scheme_image.id, 'ai_state': 'complete',
                'ai_response': {'detections': [
                    {'raw_label': 'A1', 'label_kind': 'root'},
                    {'raw_label': 'A1a', 'label_kind': 'part'},
                    {'raw_label': 'A1b', 'label_kind': 'part'},
                ]},
            },
        ])

        job._build_sections_from_page_analysis()

        sections = {section.source_key: section for section in job.section_ids}
        self.assertEqual(set(sections), {'a1', 'a1a', 'a1b'})
        self.assertEqual(sections['a1'].display_label, 'Task A1')
        self.assertEqual(sections['a1'].answer_pages, '1')
        self.assertEqual(sections['a1a'].display_label, 'Task A1a')
        self.assertEqual(sections['a1a'].answer_pages, '1')
        self.assertEqual(sections['a1b'].display_label, 'Task A1b')
        self.assertEqual(sections['a1b'].answer_pages, '1')

    def test_configured_part_supports_contextual_subparts(self):
        label, root, part = self.env['aps.exam.paper.import']._resolve_page_label(
            '(i)', 'subpart', 'Task 1', ('configured', 'Task 1A'),
        )

        self.assertEqual((label, root), ('Task 1A.i', 'Task 1'))
        self.assertEqual(part, ('configured', 'Task 1A'))

    def test_roman_subparts_are_not_resolved_as_alphabetic_parts(self):
        resolver = self.env['aps.exam.paper.import']
        root, root_context, part_context = resolver._resolve_page_label('6', 'root', False, False)
        part, root_context, part_context = resolver._resolve_page_label('(a)', 'part', root_context, part_context)
        self.assertEqual(part, 'Q6a')
        subpart, root_context, part_context = resolver._resolve_page_label('(i)', 'subpart', root_context, part_context)
        self.assertEqual(subpart, 'Q6a.i')
        subpart, root_context, part_context = resolver._resolve_page_label('(ii)', 'subpart', root_context, part_context)
        self.assertEqual(subpart, 'Q6a.ii')

        unresolved, _, _ = resolver._resolve_page_label('(iii)', 'subpart', 'Q6', False)
        self.assertFalse(unresolved)

    def test_combined_part_and_subpart_labels_are_resolved(self):
        resolver = self.env['aps.exam.paper.import']
        for raw_label, root_context, part_context in (
            ('6(a)(i)', False, False),
            ('6a(i)', False, False),
            ('(a) (i)', 'Q6', False),
        ):
            label, root, part = resolver._resolve_page_label(
                raw_label, 'subpart', root_context, part_context,
            )
            self.assertEqual(label, 'Q6a.i', raw_label)
            self.assertEqual(root, 'Q6', raw_label)
            self.assertEqual(part, 'a', raw_label)

    def test_vision_response_accepts_single_object_array(self):
        response = [{
            'image_width': 1241,
            'image_height': 1754,
            'coordinate_system': 'pixels',
            'detections': [],
        }]
        if isinstance(response, list) and len(response) == 1:
            response = response[0]
        self.assertIsInstance(response, dict)
        self.assertIsInstance(response.get('detections'), list)

    def test_page_analysis_shows_returned_labels(self):
        page_model = self.env['aps.exam.paper.page']
        page = page_model.new({
            'ai_state': 'complete',
            'ai_response': {'detections': [
                {'raw_label': '5(a)', 'label_kind': 'part'},
                {'raw_label': '5(c)', 'label_kind': 'part'},
            ]},
        })
        self.assertEqual(page.detected_labels, '5(a) [part]\n5(c) [part]')

        empty_page = page_model.new({'ai_state': 'complete', 'ai_response': {'detections': []}})
        self.assertEqual(empty_page.detected_labels, 'No labels returned')

    def test_section_inclusion_defaults(self):
        section = self.env['aps.exam.paper.section'].new({
            'source_key': '1ai', 'display_label': 'Q1a.i',
        })
        self.assertTrue(section.include_resource)
        self.assertFalse(section.include_parent_question)

    def test_child_section_finds_nearest_lower_level_parent(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Image paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('rms.pdf').id,
        })
        self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': '1',
                'display_label': 'Q1', 'root_key': 'Q1', 'hierarchy_level': 1,
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': '1a',
                'display_label': 'Q1a', 'root_key': 'Q1', 'hierarchy_level': 2,
            },
            {
                'import_id': job.id, 'sequence': 3, 'source_key': '1ai',
                'display_label': 'Q1a.i', 'root_key': 'Q1', 'hierarchy_level': 3,
                'include_parent_question': True,
            },
            {
                'import_id': job.id, 'sequence': 4, 'source_key': '1aii',
                'display_label': 'Q1a.ii', 'root_key': 'Q1', 'hierarchy_level': 3,
            },
            {
                'import_id': job.id, 'sequence': 5, 'source_key': '1b',
                'display_label': 'Q1b', 'root_key': 'Q1', 'hierarchy_level': 2,
                'include_parent_question': True,
            },
            {
                'import_id': job.id, 'sequence': 6, 'source_key': '1bi',
                'display_label': 'Q1b.i', 'root_key': 'Q1', 'hierarchy_level': 3,
                'include_parent_question': True,
            },
        ])

        q1, q1a, q1ai, q1aii, q1b, q1bi = job.section_ids.sorted('sequence')

        self.assertEqual(job._find_parent_section(q1a), self.env['aps.exam.paper.section'])
        self.assertEqual(job._find_parent_section(q1ai), q1a)
        self.assertEqual(job._find_parent_section(q1b), q1)
        self.assertEqual(job._find_parent_section(q1bi), q1b)

    def test_child_section_falls_back_to_root_when_part_is_missing(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Fallback paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('rms.pdf').id,
        })
        sections = self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': '1',
                'display_label': 'Q1', 'root_key': 'Q1', 'hierarchy_level': 1,
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': '1ai',
                'display_label': 'Q1a.i', 'root_key': 'Q1', 'hierarchy_level': 3,
            },
        ])

        self.assertEqual(job._find_parent_section(sections[1]), sections[0])

    def test_section_regions_include_multiple_enabled_parents(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Nested parent paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('rms.pdf').id,
        })
        sections = self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': '4',
                'display_label': '4', 'root_key': 'Q4', 'hierarchy_level': 1,
                'question_regions': [{'detection_label': '4'}],
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': '4c',
                'display_label': '4c', 'root_key': 'Q4', 'hierarchy_level': 2,
                'include_resource': False, 'include_parent_question': True,
                'question_regions': [{'detection_label': '4c'}],
            },
            {
                'import_id': job.id, 'sequence': 3, 'source_key': '4ci',
                'display_label': '4c.i', 'root_key': 'Q4', 'hierarchy_level': 3,
                'include_parent_question': True,
                'question_regions': [{'detection_label': '4c.i'}],
            },
        ])

        regions = job._section_regions(sections[2], 'question')

        self.assertEqual(
            [region['detection_label'] for region in regions],
            ['4', '4c', '4c.i'],
        )

    def test_resource_builder_creates_parent_headings_and_child_inheritance(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Image paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('rms.pdf').id,
        })
        self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': '1',
                'display_label': 'Q1', 'root_key': 'Q1',
                'question_summary': 'Solve the equations and show your working.',
                'question_regions': [{'x1': 0.1, 'y1': 0.1, 'x2': 0.9, 'y2': 0.2}],
                'answer_regions': [{'x1': 0.1, 'y1': 0.1, 'x2': 0.9, 'y2': 0.2}],
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': '1a',
                'display_label': 'Q1a', 'root_key': 'Q1', 'maximum_mark': 2,
                'question_summary': 'Calculate the missing angle.',
                'question_regions': [{'x1': 0.1, 'y1': 0.2, 'x2': 0.9, 'y2': 0.4}],
                'answer_regions': [{'x1': 0.1, 'y1': 0.2, 'x2': 0.9, 'y2': 0.4}],
            },
        ])
        job.action_build_resources()
        q1 = self.resource.child_ids.filtered(lambda r: r.name == 'Q1')
        self.assertEqual(len(q1), 1)
        child = q1.child_ids.filtered(lambda r: r.name == 'Q1a')
        self.assertEqual(len(child), 1)
        self.assertEqual(q1.has_child_resources, 'yes')
        self.assertEqual(q1.marks, 2)
        self.assertEqual(child.has_question, 'use_parent')
        self.assertEqual(child.has_answer, 'use_parent')
        self.assertEqual(child.description, 'Calculate the missing angle.')
        self.assertNotIn('Imported from', child.description)
        self.assertNotIn('Question pages', child.description)
        self.assertEqual(q1.description, 'Solve the equations and show your working.')
        self.assertIn('<h1>Q1a</h1>', q1.question)

        q1.write({'description': 'Teacher root description.'})
        child.write({'description': 'Teacher part description.'})
        job.action_build_resources()
        self.assertEqual(q1.description, 'Teacher root description.')
        self.assertEqual(child.description, 'Teacher part description.')

    def test_resource_builder_adds_content_for_root_only_question(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Standalone question paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('rms.pdf').id,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id,
            'sequence': 1,
            'source_key': '7',
            'display_label': 'Q7',
            'root_key': 'Q7',
            'hierarchy_level': 1,
            'question_summary': 'Determine the value of the unknown.',
            'maximum_mark': 5,
            'question_regions': [{'page_number': 1}],
            'answer_regions': [{'page_number': 1}],
        })

        def image_html(_import, _resource, _section, document_type, log=False):
            return '<img data-document="%s"></img>' % document_type

        with patch.object(
            type(job), '_build_section_image_html', autospec=True,
            side_effect=image_html,
        ):
            job.action_build_resources()

        resource = self.resource.child_ids.filtered(lambda item: item.name == 'Q7')
        self.assertEqual(len(resource), 1)
        self.assertIn('data-document="question"', resource.question)
        self.assertIn('data-document="mark_scheme"', resource.answer)
        self.assertEqual(resource.marks, 5)
        self.assertEqual(resource.description, 'Determine the value of the unknown.')
        self.assertEqual(section.resource_id, resource)
        self.assertEqual(resource.has_child_resources, 'no')

    def test_image_sections_do_not_have_text_fields(self):
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Image paper', 'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('que.pdf').id,
            'mark_scheme_attachment_id': self._attachment('rms.pdf').id,
        })
        section = self.env['aps.exam.paper.section']._fields
        self.assertNotIn('question_text', section)
        self.assertNotIn('mark_scheme_text', section)
        self.assertNotIn('question_ocr', section)
        self.assertNotIn('answer_ocr', section)

    def test_render_dpi_is_configurable(self):
        job = self.env['aps.exam.paper.import'].new({
            'name': 'Paper', 'resource_id': self.resource.id,
            'render_dpi': 200,
        })
        self.assertEqual(job.render_dpi, 200)

    def test_render_dpi_defaults_to_300(self):
        importer = self.env['aps.exam.paper.import']
        job = importer.new({'name': 'Default DPI paper', 'resource_id': self.resource.id})
        self.assertEqual(job.render_dpi, 300)

    def test_render_and_crop_webp_with_ocr_mime_compatibility(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF is required for PDF rendering.')
        from PIL import Image

        pdf = fitz.open()
        pdf_page = pdf.new_page(width=72, height=144)
        pdf_page.insert_text((10, 24), 'Q1')
        pdf_content = pdf.tobytes()
        pdf.close()
        pdf_attachment = self.env['ir.attachment'].create({
            'name': 'question.pdf', 'type': 'binary',
            'datas': base64.b64encode(pdf_content).decode('ascii'),
            'mimetype': 'application/pdf',
        })
        job = self.env['aps.exam.paper.import'].create({
            'name': 'WebP paper', 'resource_id': self.resource.id,
            'question_attachment_id': pdf_attachment.id,
            'mark_scheme_attachment_id': pdf_attachment.id,
            'render_dpi': 300,
        })

        job._render_pdf_pages(pdf_attachment, 'question')

        page = job.page_ids.filtered(lambda item: item.document_type == 'question')
        self.assertEqual((page.width, page.height), (300, 600))
        self.assertEqual(page.attachment_id.mimetype, 'image/webp')
        self.assertTrue(page.attachment_id.name.endswith('.webp'))
        with Image.open(BytesIO(page.attachment_id.raw)) as rendered_image:
            self.assertEqual(rendered_image.format, 'WEBP')
            self.assertEqual(rendered_image.size, (300, 600))
        page_data_uri = job._image_data_uri(page.attachment_id)
        self.assertTrue(page_data_uri.startswith('data:image/webp;base64,'))
        self.assertEqual(base64.b64decode(page_data_uri.split(',', 1)[1]), page.attachment_id.raw)

        section = self.env['aps.exam.paper.section'].create({
            'import_id': job.id, 'sequence': 1, 'source_key': '1',
            'display_label': 'Q1', 'resource_id': self.resource.id,
            'question_regions': [{
                'page_number': 1, 'x1': 0.1, 'y1': 0.1, 'x2': 0.9, 'y2': 0.9,
            }],
        })
        self.assertEqual(
            section._default_editor_region(page),
            {'x1': 30, 'y1': 34, 'x2': 270, 'y2': 560},
        )
        image_html = job._build_section_image_html(self.resource, section, 'question')
        crop_attachment_id = int(image_html.split('/web/image/', 1)[1].split('"', 1)[0])
        crop_attachment = self.env['ir.attachment'].browse(crop_attachment_id)
        self.assertEqual(crop_attachment.mimetype, 'image/webp')
        self.assertTrue(crop_attachment.name.endswith('.webp'))
        with Image.open(BytesIO(crop_attachment.raw)) as crop_image:
            self.assertEqual(crop_image.format, 'WEBP')
            self.assertEqual(crop_image.size, (240, 502))

        png_buffer = BytesIO()
        Image.new('RGB', (40, 40), 'white').save(png_buffer, format='PNG')
        legacy_png = self.env['ir.attachment'].create({
            'name': 'legacy-crop.png', 'type': 'binary',
            'datas': base64.b64encode(png_buffer.getvalue()).decode('ascii'),
            'mimetype': 'image/png',
        })
        model = MagicMock()
        model.model_key = 'test-model'
        model.max_completion_tokens = 2400
        model._execute_logged_router_call.return_value = {'response_json': {}}
        model._extract_message_content.return_value = 'OCR result'

        self.assertEqual(job._ocr_images(model, [crop_attachment, legacy_png], 'question'), 'OCR result')
        payload = model._execute_logged_router_call.call_args.args[0]
        image_items = [item for item in payload['messages'][1]['content'] if item['type'] == 'image_url']
        webp_uri, png_uri = [item['image_url']['url'] for item in image_items]
        self.assertTrue(webp_uri.startswith('data:image/webp;base64,'))
        self.assertEqual(base64.b64decode(webp_uri.split(',', 1)[1]), crop_attachment.raw)
        self.assertTrue(png_uri.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(png_uri.split(',', 1)[1]), legacy_png.raw)

    def test_ai_1000_scale_coordinates_are_not_pixels(self):
        importer = self.env['aps.exam.paper.import']
        self.assertAlmostEqual(importer._coordinate_as_fraction(146, 1754), 0.146)

    def test_pixel_regions_are_not_scaled(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'width': 1062, 'height': 1500,
        })
        region = {'x1': 120, 'y1': 494, 'x2': 220, 'y2': 514}

        scaled = importer._scale_region_to_page(region, page, {
            'image_width': 1062, 'image_height': 1500,
            'coordinate_system': 'pixels',
        })

        self.assertEqual(scaled, region)
        self.assertAlmostEqual(importer._coordinate_as_fraction(247, 1754), 0.247)
        self.assertEqual(importer._coordinate_scale({
            'x1': 447, 'x2': 465, 'y1': 146, 'y2': 160,
        }), 'normalized 0..1000')

    def test_ai_pixel_coordinates_are_scaled_from_reported_image_size(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'width': 1241, 'height': 1754,
        })
        region = importer._scale_region_to_page(
            {'x1': 414, 'y1': 46, 'x2': 440, 'y2': 59},
            page,
            {'image_width': 768, 'image_height': 1085, 'coordinate_system': 'pixels'},
        )
        self.assertEqual(region, {'x1': 669, 'y1': 74, 'x2': 711, 'y2': 95})
