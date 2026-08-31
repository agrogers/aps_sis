"""Background AI run processor for exam paper page analysis and OCR."""
import logging
import time

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class APSExamPaperImportRun(models.Model):
    _inherit = 'aps.ai.run'
    _order = 'create_date desc, id desc'

    import_id = fields.Many2one('aps.exam.paper.import', required=True, ondelete='cascade', readonly=True)
    page_ids = fields.Many2many(
        'aps.exam.paper.page', 'aps_exam_import_run_page_rel',
        'run_id', 'page_id', string='Pages', readonly=True,
    )
    processor_key = fields.Selection(selection_add=[
        ('exam_page_analysis', 'Exam Page Analysis'),
        ('exam_ocr', 'Exam OCR'),
    ], ondelete={
        'exam_page_analysis': 'set default',
        'exam_ocr': 'set default',
    })
    run_type = fields.Selection([('analysis', 'Page Analysis'), ('ocr', 'OCR')], default='analysis', readonly=True)
    ocr_section_ids = fields.Many2many(
        'aps.exam.paper.section', 'aps_exam_import_run_section_rel',
        'run_id', 'section_id', string='OCR Sections', readonly=True,
    )

    def _get_processor_display_name(self):
        return self.import_id.display_name or _('Exam Paper')

    def _process_specialised_background(self, started_perf):
        self.ensure_one()
        if self.state not in ('queued', 'running'):
            return
        started_perf = time.perf_counter()
        self._write_progress({
            'state': 'running',
            'status_message': _('Starting page analysis...'),
            'started_at': fields.Datetime.now(),
            'finished_at': False,
            'error_message': False,
        })
        try:
            importer = self.import_id
            model = self.ai_model_id or importer.ai_model_id
            if self.run_type == 'ocr':
                self._process_ocr_run(importer, model, started_perf)
                return
            self._process_analysis_run(importer, model, started_perf)
        except Exception as exc:
            self._write_progress({
                'state': 'failed', 'status_message': _('Failed.'),
                'error_message': str(exc), 'finished_at': fields.Datetime.now(),
                'duration_ms': int((time.perf_counter() - started_perf) * 1000),
            })

    def _process_ocr_run(self, importer, model, started_perf):
        sections = self.ocr_section_ids.filtered('resource_id')
        updated = failed = 0
        for index, section in enumerate(sections, 1):
            self._write_progress({'status_message': _('OCR %s section %s of %s...') % (
                section.display_label, index, len(sections),
            )})
            try:
                importer._ocr_section(section, model=model)
                updated += 1
            except Exception:
                failed += 1
                _logger.exception('OCR failed for exam paper section %s', section.display_label)
            self._write_progress({'status_message': _('Completed OCR section %s.') % section.display_label})
        self._write_progress({
            'state': 'completed', 'status_message': _('Completed.'),
            'result_message': _('%s section(s) updated; %s failed.') % (updated, failed),
            'finished_at': fields.Datetime.now(),
            'duration_ms': int((time.perf_counter() - started_perf) * 1000),
        })

    def _process_analysis_run(self, importer, model, started_perf):
        pages = self.page_ids.sorted(key=lambda page: (page.document_type, page.page_number))
        total = len(pages)
        for index, page in enumerate(pages, 1):
            self._write_progress({
                'status_message': _('Analysing %s page %s of %s...') % (
                    dict(page._fields['document_type'].selection).get(page.document_type, page.document_type),
                    index, total,
                ),
            })
            page.write({'ai_state': 'pending', 'error_message': False})
            last_error = None
            for attempt in range(3):
                try:
                    response, log_record = importer._analyse_page_image(model, page)
                    page.write({
                        'ai_response': response,
                        'ai_state': 'complete',
                        'error_message': False,
                        'ai_call_log_id': log_record.id if log_record else False,
                    })
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    latest_log = self.env['aps.ai.call.log'].search([
                        ('related_model', '=', 'aps.exam.paper.page'),
                        ('related_res_id', '=', page.id),
                        ('request_type', '=', 'exam_paper_page_analysis'),
                    ], order='create_date desc, id desc', limit=1)
                    if latest_log:
                        page.write({'ai_call_log_id': latest_log.id})
                    if attempt < 2 and 'empty completion' in str(exc).casefold():
                        _logger.warning(
                            'Retrying empty vision completion for %s (attempt %s/3).',
                            page.display_name, attempt + 2,
                        )
                        continue
                    break
            if last_error:
                page.write({'ai_state': 'failed', 'error_message': str(last_error)})
                _logger.exception(
                    'Vision analysis failed for rendered page %s', page.display_name,
                    exc_info=(type(last_error), last_error, last_error.__traceback__),
                )
            self._write_progress({'status_message': _('Completed page %s of %s.') % (index, total)})
        importer._build_sections_from_page_analysis()
        # Move the import to "Analysed" once no pages remain to analyse.
        if not importer.page_ids.filtered(lambda item: item.ai_state != 'complete'):
            importer.write({'state': 'analysing', 'progress': 60})
        self._write_progress({
            'state': 'completed',
            'status_message': _('Completed.'),
            'result_message': _('Analysed %s rendered page(s).') % total,
            'finished_at': fields.Datetime.now(),
            'duration_ms': int((time.perf_counter() - started_perf) * 1000),
        })
