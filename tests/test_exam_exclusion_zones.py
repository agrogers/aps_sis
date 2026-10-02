from odoo.tests.common import TransactionCase


class TestExamExclusionZones(TransactionCase):
    def setUp(self):
        super().setUp()
        self.resource = self.env['aps.resources'].create({'name': 'Exclusion-zone exam'})

    def _attachment(self, name, content=b'%PDF-1.4'):
        return self.env['ir.attachment'].create({
            'name': name,
            'type': 'binary',
            'datas': content.hex(),
            'mimetype': 'application/pdf',
            'res_model': 'aps.resources',
            'res_id': self.resource.id,
        })

    def _import(self, name):
        return self.env['aps.exam.paper.import'].create({
            'name': name,
            'resource_id': self.resource.id,
            'question_attachment_id': self._attachment('%s-que.pdf' % name).id,
            'mark_scheme_attachment_id': self._attachment('%s-rms.pdf' % name).id,
        })

    def test_automatic_crop_ends_at_exclusion_zone(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 1, 'width': 1000, 'height': 1500,
        })
        exclusion_regions = [{
            'x1': 50, 'y1': 600, 'x2': 950, 'y2': 700,
            'coordinate_system': 'pixels',
        }]

        bounds = importer._crop_bounds(
            {'y1': 0.1}, page, {}, exclusion_regions=exclusion_regions,
        )

        self.assertEqual(bounds, (75, 150, 925, 600))

    def test_manual_crop_ends_at_exclusion_zone(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 1, 'width': 1000, 'height': 1500,
        })
        exclusion_regions = [{
            'x1': 50, 'y1': 600, 'x2': 950, 'y2': 700,
            'coordinate_system': 'pixels',
        }]

        bounds = importer._crop_bounds(
            {'manual': True, 'x1': 75, 'y1': 100, 'x2': 925, 'y2': 900},
            page, {}, exclusion_regions=exclusion_regions,
        )

        self.assertEqual(bounds, (75, 100, 925, 600))

    def test_automatic_crop_uses_first_identifier_or_exclusion_boundary(self):
        importer = self.env['aps.exam.paper.import']
        page = self.env['aps.exam.paper.page'].new({
            'page_number': 1, 'width': 1000, 'height': 1500,
        })
        region = {'y1': 0.1, 'source_key': 'Q1', 'detection_label': 'Q1'}
        label_positions = {1: [{
            'y': 0.3, 'normalised_label': 'q2', 'source_key': 'Q2',
        }]}
        later_zone = [{
            'x1': 50, 'y1': 600, 'x2': 950, 'y2': 700,
            'coordinate_system': 'pixels',
        }]
        earlier_zone = [{
            'x1': 50, 'y1': 300, 'x2': 950, 'y2': 400,
            'coordinate_system': 'pixels',
        }]

        identifier_bounds = importer._crop_bounds(
            region, page, label_positions, 6, exclusion_regions=later_zone,
        )
        exclusion_bounds = importer._crop_bounds(
            region, page, label_positions, 6, exclusion_regions=earlier_zone,
        )

        self.assertEqual(identifier_bounds[3], 444)
        self.assertEqual(exclusion_bounds[3], 294)

    def test_ai_analysis_refreshes_zones_and_preserves_manual_edits(self):
        importer = self._import('ai-zone')
        manual_region = {
            'id': 'manual-1', 'source': 'manual', 'coordinate_system': 'pixels',
            'x1': 40, 'y1': 1200, 'x2': 960, 'y2': 1300,
        }
        page = self.env['aps.exam.paper.page'].new({
            'document_type': 'mark_scheme', 'page_number': 1,
            'width': 1000, 'height': 1500,
            'exclusion_regions': [manual_region],
        })
        first_response = {
            'image_width': 1000, 'image_height': 1500, 'coordinate_system': 'pixels',
            'exclusion_zones': [{
                'x1': 30, 'y1': 300, 'x2': 970, 'y2': 400, 'confidence': 0.9,
            }],
        }

        page.exclusion_regions = importer._merge_page_exclusion_regions(page, first_response)
        refreshed = importer._merge_page_exclusion_regions(page, {
            **first_response,
            'exclusion_zones': [{
                'x1': 25, 'y1': 500, 'x2': 975, 'y2': 600, 'confidence': 0.8,
            }],
        })

        self.assertEqual(refreshed[0], manual_region)
        self.assertEqual(refreshed[1]['source'], 'ai')
        self.assertEqual(refreshed[1]['y1'], 500)
        self.assertIn('"exclusion_zones"', importer._vision_system_prompt())

    def test_section_editor_shows_and_saves_page_exclusion_zones(self):
        importer = self._import('editor-zone')
        page = self.env['aps.exam.paper.page'].create({
            'import_id': importer.id, 'document_type': 'question', 'page_number': 1,
            'render_dpi': 150, 'width': 1000, 'height': 1500,
            'attachment_id': self._attachment('editor-zone-page.png').id,
            'exclusion_regions': [{
                'id': 'ai-1', 'source': 'ai', 'coordinate_system': 'pixels',
                'x1': 20, 'y1': 500, 'x2': 980, 'y2': 600, 'confidence': 0.9,
            }],
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': importer.id, 'sequence': 1, 'source_key': 'zone-editor',
            'display_label': 'Q1',
            'question_regions': [{
                'page_number': 1, 'x1': 75, 'y1': 85, 'x2': 925, 'y2': 1400,
            }],
        })

        data = section.get_region_editor_data()
        self.assertEqual(data['regions']['question'][0]['page_id'], page.id)
        self.assertEqual(
            data['regions']['question'][0]['exclusion_regions'], page.exclusion_regions,
        )
        section.save_region_editor_exclusion_zones(page.id, [
            {'id': 'ai-1', 'x1': 20, 'y1': 510, 'x2': 980, 'y2': 610},
            {'id': 'manual-1', 'x1': 25, 'y1': 800, 'x2': 975, 'y2': 900},
        ])

        self.assertEqual(page.exclusion_regions[0]['source'], 'manual')
        self.assertEqual(page.exclusion_regions[0]['y1'], 510)
        self.assertEqual(page.exclusion_regions[1]['source'], 'manual')