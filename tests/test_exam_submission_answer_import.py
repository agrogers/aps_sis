import base64
import json
import time
from io import BytesIO
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestExamSubmissionAnswerImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        provider = cls.env['aps.ai.provider'].create({
            'name': 'Exam answer import test provider',
            'api_base_url': 'https://example.invalid',
        })
        cls.model = cls.env['aps.ai.model'].create({
            'name': 'Exam answer import vision model',
            'model_key': 'test/exam-answer-import',
            'provider_id': provider.id,
            'supports_vision': True,
        })

    def setUp(self):
        super().setUp()
        self.student = self.env['res.partner'].create({
            'name': 'Exam answer import student',
            'is_student': True,
        })
        exam_type = self.env['aps.resource.types'].create({'name': 'Exam'})
        self.parent_resource = self.env['aps.resources'].create({
            'name': 'Exam answer import paper',
            'type_id': exam_type.id,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': self.parent_resource.id,
            'student_id': self.student.id,
        })
        self.source_submission = self.env['aps.resource.submission'].create({
            'task_id': task.id,
        })
        source_image = self.env['ir.attachment'].create({
            'name': 'source-answer.png',
            'type': 'binary',
            'datas': base64.b64encode(self._png_bytes()).decode('ascii'),
            'mimetype': 'image/png',
            'res_model': 'aps.resource.submission',
            'res_id': self.source_submission.id,
        })
        self.source_submission.write({
            'answer': self._source_image_html(source_image.id),
        })

    @staticmethod
    def _png_bytes(width=100, height=80):
        from PIL import Image

        image = Image.new('RGB', (width, height), 'white')
        try:
            output = BytesIO()
            image.save(output, format='PNG')
            return output.getvalue()
        finally:
            image.close()

    @staticmethod
    def _source_image_html(image_id):
        return '<p><img src="/web/image/%s"></p>' % image_id

    def _create_import(self, with_target=True, nested_parent=False):
        image_bytes = self._png_bytes()
        pdf_attachments = self.env['ir.attachment'].create([
            {
                'name': 'exam-question.pdf',
                'type': 'binary',
                'datas': base64.b64encode(b'%PDF-1.4').decode('ascii'),
                'mimetype': 'application/pdf',
                'res_model': 'aps.resources',
                'res_id': self.parent_resource.id,
            },
            {
                'name': 'exam-mark-scheme.pdf',
                'type': 'binary',
                'datas': base64.b64encode(b'%PDF-1.4').decode('ascii'),
                'mimetype': 'application/pdf',
                'res_model': 'aps.resources',
                'res_id': self.parent_resource.id,
            },
        ])
        importer = self.env['aps.exam.paper.import'].create({
            'name': 'Exam answer import test',
            'resource_id': self.parent_resource.id,
            'question_attachment_id': pdf_attachments[0].id,
            'mark_scheme_attachment_id': pdf_attachments[1].id,
            'state': 'completed',
            'single_page_ai_model_id': self.model.id,
        })
        page_attachment = self.env['ir.attachment'].create({
            'name': 'imported-question-page.png',
            'type': 'binary',
            'datas': base64.b64encode(image_bytes).decode('ascii'),
            'mimetype': 'image/png',
        })
        self.env['aps.exam.paper.page'].create({
            'import_id': importer.id,
            'document_type': 'question',
            'page_number': 1,
            'printed_page_number': '5',
            'render_dpi': 150,
            'width': 100,
            'height': 80,
            'attachment_id': page_attachment.id,
        })
        resource_parent = self.parent_resource
        target_parent_submission = self.source_submission
        if nested_parent:
            resource_parent = self.env['aps.resources'].create({
                'name': 'Q1',
                'parent_ids': [(4, self.parent_resource.id)],
                'primary_parent_id': self.parent_resource.id,
            })
            parent_task = self.env['aps.resource.task'].create({
                'resource_id': resource_parent.id,
                'student_id': self.student.id,
            })
            target_parent_submission = self.env['aps.resource.submission'].create({
                'task_id': parent_task.id,
                'parent_submission_id': self.source_submission.id,
            })
        child_resource = self.env['aps.resources'].create({
            'name': 'Q1v',
            'parent_ids': [(4, resource_parent.id)],
            'primary_parent_id': resource_parent.id,
        })
        section = self.env['aps.exam.paper.section'].create({
            'import_id': importer.id,
            'sequence': 1,
            'source_key': '1/v',
            'display_label': 'Q1v',
            'root_key': 'Q1',
            'hierarchy_level': 2,
            'resource_id': child_resource.id,
            'question_regions': [{
                'page_number': 1,
                'detection_label': '(v)',
                'source_key': '1/v',
            }],
        })
        target = False
        if with_target:
            child_task = self.env['aps.resource.task'].create({
                'resource_id': child_resource.id,
                'student_id': self.student.id,
            })
            target = self.env['aps.resource.submission'].create({
                'task_id': child_task.id,
                'parent_submission_id': target_parent_submission.id,
                'answer': '<p>Existing answer.</p>',
                'state': 'assigned',
            })
        return importer, section, target

    def _create_run(self, importer):
        return self.env['aps.ai.run'].sudo().create({
            'submission_id': self.source_submission.id,
            'import_id': importer.id,
            'requested_by_id': self.env.uid,
            'fingerprint': self.source_submission._get_exam_answer_import_fingerprint(),
            'processor_key': 'exam_submission_answers',
            'ai_model_id': self.model.id,
            'state': 'running',
            'status_message': 'Running...',
        })

    @staticmethod
    def _mock_detection(answers=None, pages=None):
        response = {
            'coordinate_system': 'pixels',
            'image_width': 100,
            'image_height': 80,
            'pages_detected': pages if pages is not None else ['5'],
            'answers': answers if answers is not None else [{
                'printed_page_number': '5',
                'question_identifier': '(v)',
                'bbox': {'x1': 10, 'y1': 10, 'x2': 50, 'y2': 50},
            }],
        }
        return response, json.dumps(response), {
            'prompt_tokens': 100,
            'completion_tokens': 50,
            'estimated_cost': 0.001,
        }

    def _process_run(self, run, response=None):
        response = response or self._mock_detection()
        with (
            patch.object(
                type(self.source_submission),
                '_detect_exam_answer_regions',
                return_value=response,
            ),
            patch.object(
                type(run),
                '_write_progress',
                autospec=True,
                side_effect=lambda record, values: record.write(values),
            ),
            patch.object(type(run), '_commit_background_work'),
        ):
            self.source_submission._process_exam_submission_answer_import(
                run,
                time.perf_counter(),
            )

    def test_import_button_queues_run_for_embedded_answer_images(self):
        importer, _section, _target = self._create_import()
        with (
            patch.object(type(self.source_submission), '_get_current_faculty', return_value=True),
            patch.object(type(self.env['aps.ai.run']), '_queue_background_processing') as queue,
        ):
            action = self.source_submission.action_import_student_answers()

        run = self.env['aps.ai.run'].search([
            ('submission_id', '=', self.source_submission.id),
            ('import_id', '=', importer.id),
            ('processor_key', '=', 'exam_submission_answers'),
        ], limit=1)
        self.assertEqual(action['tag'], 'aps_ai_run_progress')
        self.assertEqual(run.state, 'queued')
        self.assertEqual(run.ai_model_id, self.model)
        queue.assert_called_once()

    def test_image_answer_is_matched_cropped_appended_and_submitted(self):
        importer, _section, target = self._create_import()
        run = self._create_run(importer)

        self._process_run(run)

        self.assertEqual(run.state, 'completed')
        self.assertEqual(target.state, 'submitted')
        self.assertIn('<p>Existing answer.</p>', target.answer)
        self.assertIn('/web/image/', target.answer)
        self.assertTrue(target.auto_score)
        self.assertIn('Imported', run.exam_answer_import_result_log)
        self.assertIn('vision_responses', run.response_preview)
        crop = self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.resource.submission'),
            ('res_id', '=', target.id),
            ('description', 'like', 'aps_exam_submission_answer_import:%'),
        ], limit=1)
        self.assertTrue(crop)
        self.assertEqual(crop.mimetype, 'image/png')

    def test_nested_question_submission_matches_exam_submission(self):
        importer, _section, target = self._create_import(nested_parent=True)
        run = self._create_run(importer)

        self._process_run(run)

        self.assertEqual(run.state, 'completed')
        self.assertEqual(target.state, 'submitted')
        self.assertIn('Imported', run.exam_answer_import_result_log)

    def test_missing_target_submission_is_logged_without_creating_one(self):
        importer, _section, _target = self._create_import(with_target=False)
        run = self._create_run(importer)

        self._process_run(run)

        self.assertEqual(run.state, 'completed')
        self.assertIn('Student submission was not found', run.exam_answer_import_result_log)
        self.assertEqual(
            self.env['aps.resource.submission'].search_count([
                ('task_id.resource_id', '!=', self.parent_resource.id),
                ('task_id.student_id', '=', self.student.id),
            ]),
            0,
        )

    def test_progress_status_includes_import_result_details(self):
        importer, _section, _target = self._create_import()
        run = self._create_run(importer)
        result_log = 'Image 1 - page 5 - (v): Student submission was not found'
        run.write({'exam_answer_import_result_log': result_log})

        status = self.env['aps.ai.run'].action_get_run_status(run.id)

        self.assertEqual(status['result_details'], result_log)

    def test_invalid_bounds_and_questions_without_detected_answers_are_logged(self):
        importer, target_section, target = self._create_import()
        run = self._create_run(importer)
        response = self._mock_detection(answers=[{
            'printed_page_number': '5',
            'question_identifier': '(v)',
            'bbox': {'x1': -1, 'y1': 10, 'x2': 50, 'y2': 50},
        }])

        self._process_run(run, response)

        self.assertEqual(run.state, 'completed')
        self.assertEqual(target.state, 'assigned')
        self.assertIn('Bounding rectangle is invalid', run.exam_answer_import_result_log)
        self.assertFalse(self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.resource.submission'),
            ('res_id', '=', target.id),
            ('description', 'like', 'aps_exam_submission_answer_import:%'),
        ]))

    def test_page_with_no_detected_answers_reports_unmatched_question(self):
        importer, section, target = self._create_import()
        run = self._create_run(importer)

        self._process_run(run, self._mock_detection(answers=[], pages=['5']))

        self.assertEqual(run.state, 'completed')
        self.assertEqual(target.state, 'assigned')
        self.assertIn(section.display_label, run.exam_answer_import_result_log)
        self.assertIn('No answer region was detected', run.exam_answer_import_result_log)

    def test_button_is_hidden_for_other_resource_types_and_server_guarded(self):
        worksheet_type = self.env['aps.resource.types'].create({'name': 'Worksheet'})
        worksheet = self.env['aps.resources'].create({
            'name': 'Worksheet resource',
            'type_id': worksheet_type.id,
        })
        task = self.env['aps.resource.task'].create({
            'resource_id': worksheet.id,
            'student_id': self.student.id,
        })
        submission = self.env['aps.resource.submission'].create({'task_id': task.id})

        self.assertFalse(submission.can_import_student_answers)
        with (
            patch.object(type(submission), '_get_current_faculty', return_value=True),
            self.assertRaises(UserError),
        ):
            submission.action_import_student_answers()
