from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestExamQuestionIdentifierData(TransactionCase):
    def test_seeded_rules_are_disabled_and_descriptive(self):
        rules = self.env['aps.exam.paper.question.identifier'].browse([
            self.env.ref('aps_sis.exam_question_identifier_rule_explicit').id,
            self.env.ref('aps_sis.exam_question_identifier_rule_part').id,
            self.env.ref('aps_sis.exam_question_identifier_rule_subpart').id,
        ])

        self.assertEqual(len(rules), 3)
        self.assertTrue(all(not rule.active for rule in rules))
        self.assertTrue(all(rule.description for rule in rules))
        self.assertEqual([rule.hierarchy_level for rule in rules], ['1', '2', '3'])

        rules[0].active = True
        self.assertTrue(rules[0].active)

    def test_component_rules_are_seeded_active(self):
        rules = self.env['aps.exam.paper.question.identifier'].browse([
            self.env.ref('aps_sis.exam_question_identifier_root_component').id,
            self.env.ref('aps_sis.exam_question_identifier_part_component').id,
            self.env.ref('aps_sis.exam_question_identifier_subpart_component').id,
        ])

        self.assertTrue(all(rule.active for rule in rules))
        self.assertEqual([rule.hierarchy_level for rule in rules], ['1', '2', '3'])

    def test_rule_parser_matches_legacy_contextual_labels(self):
        rules = self.env['aps.exam.paper.question.identifier'].search(
            [('active', '=', True)], order='sequence, id',
        )
        resolver = self.env['aps.exam.paper.import']
        context = resolver._empty_identifier_context()
        legacy_root = False
        legacy_part = False
        cases = [
            ('1', 'root', '1'),
            ('(a)', 'part', '1/a'),
            ('(i)', 'subpart', '1/a/i'),
            ('(ii)', 'subpart', '1/a/ii'),
            ('(b)', 'part', '1/b'),
            ('(i)', 'subpart', '1/b/i'),
            ('2', 'root', '2'),
        ]

        for raw_label, kind, expected_path in cases:
            legacy_label, legacy_root, legacy_part = resolver._resolve_page_label(
                raw_label, kind, legacy_root, legacy_part,
            )
            resolved = resolver._resolve_rule_identifier(
                raw_label, context, rules, 'question', '', kind,
            )

            self.assertTrue(resolved, raw_label)
            self.assertEqual(resolved['label'], legacy_label, raw_label)
            self.assertEqual(resolved['root_label'], legacy_root, raw_label)
            self.assertEqual(resolved['source_key'], expected_path, raw_label)
            self.assertEqual(
                resolved['hierarchy_level'],
                resolver._label_hierarchy_level(legacy_label),
                raw_label,
            )

    def test_rule_parser_handles_complete_and_combined_labels(self):
        rules = self.env['aps.exam.paper.question.identifier'].search(
            [('active', '=', True)], order='sequence, id',
        )
        resolver = self.env['aps.exam.paper.import']
        for raw_label in ('6(a)(i)', '6a(i)'):
            context = resolver._empty_identifier_context()
            resolved = resolver._resolve_rule_identifier(
                raw_label, context, rules, 'question', '', 'subpart',
            )
            legacy = resolver._resolve_page_label(raw_label, 'subpart', False, False)

            self.assertTrue(resolved, raw_label)
            self.assertEqual(resolved['label'], legacy[0], raw_label)
            self.assertEqual(resolved['root_label'], legacy[1], raw_label)
            self.assertEqual(resolved['source_key'], '6/a/i', raw_label)

        context = resolver._empty_identifier_context()
        resolver._resolve_rule_identifier('6', context, rules, 'question', '', 'root')
        resolved = resolver._resolve_rule_identifier(
            '(a) (i)', context, rules, 'question', '', 'part',
        )
        legacy = resolver._resolve_page_label('(a) (i)', 'part', 'Q6', False)
        self.assertEqual(resolved['label'], legacy[0])
        self.assertEqual(resolved['source_key'], '6/a/i')

    def test_rule_parser_handles_bare_roman_subpart_in_compact_label(self):
        rules = self.env['aps.exam.paper.question.identifier'].search(
            [('active', '=', True)], order='sequence, id',
        )
        resolved = self.env['aps.exam.paper.import']._resolve_rule_identifier(
            '1hi', self.env['aps.exam.paper.import']._empty_identifier_context(),
            rules, 'question', '', 'subpart',
        )

        self.assertTrue(resolved)
        self.assertEqual(resolved['label'], 'Q1h.i')
        self.assertEqual(resolved['root_label'], 'Q1')
        self.assertEqual(resolved['hierarchy_level'], 3)
        self.assertEqual(resolved['source_key'], '1/h/i')

    def test_disabled_component_rule_does_not_match(self):
        model = self.env['aps.exam.paper.question.identifier']
        rules = model.search([('active', '=', True)])
        rules.filtered(lambda rule: rule.hierarchy_level == '1').write({'active': False})
        active_rules = model.search([('active', '=', True)])
        resolved = self.env['aps.exam.paper.import']._resolve_rule_identifier(
            '1', self.env['aps.exam.paper.import']._empty_identifier_context(),
            active_rules, 'question', '', 'root',
        )
        self.assertFalse(resolved)

    def test_detection_persists_paths_and_joins_document_streams(self):
        resource = self.env['aps.resources'].create({'name': 'Rule path integration paper'})

        def attachment(name, mimetype):
            return self.env['ir.attachment'].create({
                'name': name,
                'type': 'binary',
                'datas': 'aGVsbG8=',
                'mimetype': mimetype,
                'res_model': 'aps.resources',
                'res_id': resource.id,
            })

        job = self.env['aps.exam.paper.import'].create({
            'name': 'Rule path integration paper',
            'resource_id': resource.id,
            'question_attachment_id': attachment('path-que.pdf', 'application/pdf').id,
            'mark_scheme_attachment_id': attachment('path-rms.pdf', 'application/pdf').id,
        })
        page_model = self.env['aps.exam.paper.page']
        for document_type in ('question', 'mark_scheme'):
            page_model.create({
                'import_id': job.id,
                'document_type': document_type,
                'page_number': 1,
                'render_dpi': 150,
                'attachment_id': attachment('%s-page.png' % document_type, 'image/png').id,
                'ai_state': 'complete',
                'ai_response': {'detections': [
                    {'raw_label': '1', 'label_kind': 'root'},
                    {'raw_label': '(a)', 'label_kind': 'part'},
                    {'raw_label': '(i)', 'label_kind': 'subpart'},
                ]},
            })

        with patch.object(type(job), '_resolve_page_label', side_effect=AssertionError):
            first = job._build_sections_from_page_analysis()
            section_ids_before_rerun = set(job.section_ids.ids)
            second = job._build_sections_from_page_analysis()

        self.assertEqual(first['added'], 3)
        self.assertEqual(second['added'], 0)
        self.assertEqual(set(job.section_ids.ids), section_ids_before_rerun)
        sections = {section.source_key: section for section in job.section_ids}
        self.assertEqual(set(sections), {'1', '1/a', '1/a/i'})
        self.assertTrue(all(section.root_key == 'Q1' for section in sections.values()))
        self.assertEqual(
            {key: section.display_label for key, section in sections.items()},
            {'1': 'Q1', '1/a': 'Q1a', '1/a/i': 'Q1a.i'},
        )
        self.assertEqual(sections['1/a/i'].answer_pages, '1')
        self.assertFalse(job._find_parent_section(sections['1']))
        self.assertEqual(job._find_parent_section(sections['1/a']), sections['1'])
        self.assertEqual(job._find_parent_section(sections['1/a/i']), sections['1/a'])

    def test_resource_build_renames_linked_legacy_child_without_duplicate(self):
        parent_resource = self.env['aps.resources'].create({'name': 'Exam resource'})
        job = self.env['aps.exam.paper.import'].create({
            'name': 'Legacy label paper',
            'resource_id': parent_resource.id,
            'question_attachment_id': self.env['ir.attachment'].create({
                'name': 'legacy-que.pdf', 'type': 'binary', 'datas': 'aGVsbG8=',
                'mimetype': 'application/pdf', 'res_model': 'aps.resources',
                'res_id': parent_resource.id,
            }).id,
            'mark_scheme_attachment_id': self.env['ir.attachment'].create({
                'name': 'legacy-rms.pdf', 'type': 'binary', 'datas': 'aGVsbG8=',
                'mimetype': 'application/pdf', 'res_model': 'aps.resources',
                'res_id': parent_resource.id,
            }).id,
        })
        root = self.env['aps.resources'].create({
            'name': 'Q1',
            'parent_ids': [(4, parent_resource.id)],
            'primary_parent_id': parent_resource.id,
        })
        legacy_child = self.env['aps.resources'].create({
            'name': '(a)',
            'parent_ids': [(4, root.id)],
            'primary_parent_id': root.id,
        })
        self.env['aps.exam.paper.section'].create([
            {
                'import_id': job.id, 'sequence': 1, 'source_key': '1',
                'display_label': 'Q1', 'root_key': 'Q1', 'hierarchy_level': 1,
            },
            {
                'import_id': job.id, 'sequence': 2, 'source_key': '1/a',
                'display_label': 'Q1a', 'root_key': 'Q1', 'hierarchy_level': 2,
                'resource_id': legacy_child.id, 'resource_key': str(legacy_child.id),
                'maximum_mark': 2,
                'question_regions': [{'detection_label': '(a)'}],
            },
        ])

        with patch.object(type(job), '_build_section_image_html', return_value=''):
            job.action_build_resources()

        self.assertEqual(legacy_child.name, 'Q1a')
        self.assertEqual(len(root.child_ids), 1)
        self.assertEqual(root.child_ids, legacy_child)
        self.assertIn('<h1>Q1a</h1>', root.question)