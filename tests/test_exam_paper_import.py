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

    def test_numbered_blocks_normalize_nested_labels(self):
        blocks = self.env['aps.exam.paper.import']._numbered_blocks(
            'Q1a\nQuestion A\n\nQ1b.i\nQuestion B\n'
        )
        self.assertIn('1a', blocks)
        self.assertIn('1bi', blocks)

    def test_mark_extraction(self):
        importer = self.env['aps.exam.paper.import']
        self.assertEqual(importer._extract_mark('Answer [3]'), 3.0)
        self.assertFalse(importer._extract_mark('No mark'))

    def test_resource_creation_is_idempotent(self):
        importer = self.env['aps.exam.paper.import']
        parent = self.resource
        first = importer._find_or_create_resource('Q1', parent)
        second = importer._find_or_create_resource('Q1', parent)
        self.assertEqual(first, second)

    def test_vision_prompt_requires_no_ocr_output(self):
        prompt = self.env['aps.exam.paper.import']._vision_system_prompt()
        self.assertIn('Do not transcribe OCR', prompt)
        self.assertIn('normalized_label', prompt)
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

    def test_render_dpi_is_configurable(self):
        job = self.env['aps.exam.paper.import'].new({
            'name': 'Paper', 'resource_id': self.resource.id,
            'render_dpi': 200,
        })
        self.assertEqual(job.render_dpi, 200)
