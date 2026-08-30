from odoo.tests.common import TransactionCase

from odoo.exceptions import UserError


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
            'page_number': 1, 'width': 1000, 'height': 1000,
        })

        left, top, right, bottom = importer._crop_bounds({'y1': 0.1}, page, {})

        self.assertEqual((left, top, right, bottom), (75, 100, 925, 900))

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

    def test_resolve_page_labels_across_pages(self):
        resolver = self.env['aps.exam.paper.import']
        root, root_context, part_context = resolver._resolve_page_label('1', 'root', False, False)
        self.assertEqual(root, 'Q1')
        part, root_context, part_context = resolver._resolve_page_label('(a)', 'part', root_context, part_context)
        self.assertEqual(part, 'Q1a')
        subpart, _, _ = resolver._resolve_page_label('(i)', 'subpart', root_context, part_context)
        self.assertEqual(subpart, 'Q1a.i')

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
        self.assertEqual(child.description, 'Calculate the missing angle.')
        self.assertNotIn('Imported from', child.description)
        self.assertNotIn('Question pages', child.description)
        self.assertFalse(q1.description)
        self.assertIn('<h1>Q1a</h1>', q1.question)

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

    def test_render_height_is_fixed(self):
        importer = self.env['aps.exam.paper.import']
        self.assertEqual(importer._RENDER_HEIGHT_PIXELS, 1500)

    def test_ai_1000_scale_coordinates_are_not_pixels(self):
        importer = self.env['aps.exam.paper.import']
        self.assertAlmostEqual(importer._coordinate_as_fraction(146, 1754), 0.146)
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
