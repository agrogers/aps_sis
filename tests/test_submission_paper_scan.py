import base64
import io
import json
from html import unescape
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestSubmissionPaperScan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['aps.ai.provider'].create({
            'name': 'Paper scan test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.model = cls.env['aps.ai.model'].create({
            'name': 'Paper scan vision model',
            'model_key': 'test/paper-scan-model',
            'provider_id': cls.provider.id,
            'supports_vision': True,
        })

    @staticmethod
    def _image_bytes():
        from PIL import Image
        image_buffer = io.BytesIO()
        Image.new('L', (100, 120), 255).save(image_buffer, format='PNG')
        return image_buffer.getvalue()

    @staticmethod
    def _router_result(response):
        return {
            'response_json': {
                'choices': [{
                    'message': {'content': json.dumps(response)},
                }],
                'usage': {},
            },
        }

    def _create_root_submission(self):
        student = self.env['res.partner'].create({
            'name': 'Paper Scan Student',
            'is_student': True,
        })
        root = self.env['aps.resources'].create({
            'name': 'Practice Paper',
            'ai_model_ids': [(6, 0, [self.model.id])],
        })
        question = self.env['aps.resources'].create({
            'name': 'Q3 (b). (i)',
            'parent_ids': [(4, root.id)],
        })
        missing_question = self.env['aps.resources'].create({
            'name': 'Q4',
            'parent_ids': [(4, root.id)],
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': root.id,
            'student_id': student.id,
        })
        submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'submission_label': 'Mock exam',
        })
        for page in ('page-1.png', 'page-2.png'):
            self.env['ir.attachment'].create({
                'name': page,
                'type': 'binary',
                'datas': base64.b64encode(self._image_bytes()),
                'mimetype': 'image/png',
                'res_model': 'aps.resource.submission',
                'res_id': submission.id,
            })
        return submission, question, missing_question

    def test_submit_processes_page_crops_and_continuations(self):
        submission, question, missing_question = self._create_root_submission()
        with patch.object(type(self.env['aps.ai.run']), '_queue_background_processing'):
            submission.write({'state': 'submitted'})
        run = submission.paper_scan_run_id
        self.assertEqual(run.processor_key, 'submission_paper_scan')

        responses = [
            {'answers': [{
                'question_code': 'Q3b.i',
                'x1': 10, 'y1': 15, 'x2': 60, 'y2': 75,
                'continuation': False,
            }]},
            {'answers': [{
                'question_code': 'Q3b.i cont',
                'x1': 20, 'y1': 30, 'x2': 80, 'y2': 100,
                'continuation': True,
            }]},
        ]
        with (
            patch.object(
                type(self.model),
                '_execute_logged_router_call',
                autospec=True,
                side_effect=[
                    self._router_result(response)
                    for response in responses
                ],
            ),
            patch.object(type(run), '_commit_background_work', autospec=True),
        ):
            run._process_background()

        answer_submission = self.env['aps.resource.submission'].search([
            ('task_id.resource_id', '=', question.id),
            ('task_id.student_id', '=', submission.student_id.id),
            ('submission_label', '=', submission.submission_label),
        ], limit=1)
        self.assertTrue(answer_submission)
        self.assertEqual(answer_submission.state, 'submitted')
        self.assertEqual(answer_submission.answer.count('<img'), 2)
        crops = self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.resource.submission'),
            ('res_id', '=', answer_submission.id),
            ('description', 'like', 'aps_submission_paper_scan:%'),
        ])
        self.assertEqual(len(crops), 2)
        from PIL import Image
        for crop in crops:
            with Image.open(io.BytesIO(crop.raw)) as image:
                self.assertEqual(image.format, 'WEBP')
                self.assertEqual(image.mode, 'RGB')
        missing_submission = self.env['aps.resource.submission'].search([
            ('task_id.resource_id', '=', missing_question.id),
            ('task_id.student_id', '=', submission.student_id.id),
            ('submission_label', '=', submission.submission_label),
        ], limit=1)
        self.assertTrue(missing_submission)
        self.assertEqual(missing_submission.state, 'assigned')
        self.assertEqual(submission.paper_scan_state, 'succeeded')
        activity = submission.activity_ids.filtered(
            lambda item: '1/2 answers added' in (item.summary or '')
        )
        self.assertTrue(activity)
        self.assertIn('Root paper submission:', activity.note)
        self.assertIn(missing_submission._get_submission_url(), unescape(activity.note))

    def test_code_normalization_accepts_spacing_brackets_and_continuation_suffix(self):
        normalize = type(self.env['aps.resource.submission'])._normalise_paper_question_code
        self.assertEqual(normalize('Q 3 (b). (i)'), '3bi')
        self.assertEqual(normalize('Q4'), '4')
        self.assertEqual(normalize('Q3b.i cont'), '3bi')
        self.assertEqual(normalize('Q3b.i cont.'), '3bi')
        self.assertFalse(normalize('Q3b.i extra'))
