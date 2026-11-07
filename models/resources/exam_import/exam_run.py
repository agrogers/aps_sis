"""Background AI run processor for exam paper page analysis and OCR."""
import logging
import time

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..chapter_tagging import (
    chapter_summary_candidates_by_resource,
    create_chapter_tagging_run,
)

_logger = logging.getLogger(__name__)


class APSExamPaperImportRun(models.Model):
    _inherit = 'aps.ai.run'
    _order = 'create_date desc, id desc'

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
    chapter_tagging_source_run_id = fields.Many2one(
        'aps.ai.run', string='Source OCR Run', readonly=True, index=True, copy=False,
        ondelete='set null',
    )
    chapter_tagging_run_ids = fields.One2many(
        'aps.ai.run', 'chapter_tagging_source_run_id', string='Chapter Tagging Runs',
    )

    def _get_processor_display_name(self):
        if self.processor_key in ('exam_page_analysis', 'exam_ocr'):
            return self.import_id.display_name or _('Exam Paper')
        return super()._get_processor_display_name()

    def _serialize_status(self):
        status = super()._serialize_status()
        if self.processor_key == 'exam_ocr' and self.state == 'completed':
            status['follow_up_runs'] = [
                {'id': run.id, 'label': run.resource_id.display_name}
                for run in self.chapter_tagging_run_ids.sorted(key=lambda item: item.id)
            ]
            status['follow_up_title'] = _('Textbook Chapter Tagging')
        return status

    def _process_specialised_background(self, started_perf):
        if self.processor_key not in ('exam_page_analysis', 'exam_ocr'):
            return super()._process_specialised_background(started_perf)
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
        activity_counts = {
            'provider_call': 0,
            'cache_hit': 0,
            'no_images': 0,
        }
        for index, section in enumerate(sections, 1):
            self._write_progress({'status_message': _('OCR %s section %s of %s...') % (
                section.display_label, index, len(sections),
            )})
            try:
                activity = importer._ocr_section(section, model=model)
                for source in activity.values():
                    activity_counts[source] += 1
                updated += 1
            except Exception:
                failed += 1
                _logger.exception('OCR failed for exam paper section %s', section.display_label)
            self._commit_background_work()
            self._write_progress({'status_message': _('Completed OCR section %s.') % section.display_label})
        tagging_runs, without_summary, ambiguous_summary, invalid_summary = (
            self._queue_chapter_tagging_runs()
        )
        self._commit_background_work()
        result_messages = [
            _('%s section(s) updated; %s failed.') % (updated, failed),
            _(
                'OCR activity: %s provider call(s) completed, %s local cache hit(s), '
                '%s document(s) skipped because no valid images were available.'
            ) % (
                activity_counts['provider_call'],
                activity_counts['cache_hit'],
                activity_counts['no_images'],
            ),
            _('Chapter tagging queued for %s resource(s).') % len(tagging_runs),
        ]
        if without_summary:
            result_messages.append(_(
                'No subject-matched textbook summary for %s resource(s): %s.'
            ) % (len(without_summary), self._format_resource_names(without_summary)))
        if ambiguous_summary:
            result_messages.append(_(
                'Multiple subject-matched textbook summaries for %s resource(s): %s.'
            ) % (len(ambiguous_summary), self._format_resource_names(ambiguous_summary)))
        if invalid_summary:
            invalid_details = [
                '%s (%s)' % item for item in invalid_summary[:8]
            ]
            if len(invalid_summary) > len(invalid_details):
                invalid_details.append(_('and %s more') % (len(invalid_summary) - len(invalid_details)))
            result_messages.append(_(
                'Could not queue chapter tagging for %s resource(s): %s.'
            ) % (
                len(invalid_summary),
                ', '.join(invalid_details),
            ))
        self._write_progress({
            'state': 'completed', 'status_message': _('Completed.'),
            'result_message': '\n'.join(result_messages),
            'finished_at': fields.Datetime.now(),
            'duration_ms': int((time.perf_counter() - started_perf) * 1000),
        })

    def _queue_chapter_tagging_runs(self):
        self.ensure_one()
        request_env = self.with_user(self.requested_by_id).env
        resource_ids = self.ocr_section_ids.filtered('resource_id').mapped('resource_id').ids
        resources = request_env['aps.resources'].browse(resource_ids).exists()
        candidates_by_resource = chapter_summary_candidates_by_resource(request_env, resources)
        run_ids = []
        without_summary = request_env['aps.resources']
        ambiguous_summary = request_env['aps.resources']
        invalid_summary = []
        for resource in resources:
            summaries = candidates_by_resource[resource.id]
            if not summaries:
                without_summary |= resource
                _logger.warning(
                    'Skipping chapter tagging for %s: no subject-matched textbook summary.',
                    resource.display_name,
                )
                continue
            if len(summaries) > 1:
                ambiguous_summary |= resource
                _logger.warning(
                    'Skipping chapter tagging for %s: %s subject-matched textbook summaries.',
                    resource.display_name,
                    len(summaries),
                )
                continue
            try:
                run = create_chapter_tagging_run(
                    resource,
                    summaries,
                    self.requested_by_id.id,
                    source_run=self,
                )
            except UserError as exc:
                invalid_summary.append((resource.display_name, str(exc)))
                _logger.warning(
                    'Skipping chapter tagging for %s: %s',
                    resource.display_name,
                    exc,
                )
                continue
            run_ids.append(run.id)
        runs = self.env['aps.ai.run'].sudo().browse(run_ids)
        return runs, without_summary, ambiguous_summary, invalid_summary

    @staticmethod
    def _format_resource_names(resources):
        names = resources.mapped('display_name')
        shown_names = names[:8]
        if len(names) > len(shown_names):
            shown_names.append(_('and %s more') % (len(names) - len(shown_names)))
        return ', '.join(shown_names)

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
                        'printed_page_number': importer._normalise_page_metadata(
                            response.get('printed_page_number'),
                        ),
                        'barcode_value': importer._normalise_page_metadata(response.get('barcode_value')),
                        'exclusion_regions': importer._merge_page_exclusion_regions(page, response),
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
            self._commit_background_work()
            self._write_progress({'status_message': _('Completed page %s of %s.') % (index, total)})
        importer._build_sections_from_page_analysis()
        # Move the import to "Analysed" once no pages remain to analyse.
        if not importer.page_ids.filtered(lambda item: item.ai_state != 'complete'):
            importer.write({'state': 'analysing', 'progress': 60})
        self._commit_background_work()
        self._write_progress({
            'state': 'completed',
            'status_message': _('Completed.'),
            'result_message': _('Analysed %s rendered page(s).') % total,
            'finished_at': fields.Datetime.now(),
            'duration_ms': int((time.perf_counter() - started_perf) * 1000),
        })
