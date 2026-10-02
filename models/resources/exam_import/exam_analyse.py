"""AI vision analysis of rendered exam paper pages."""
import base64
import logging
import mimetypes
from typing import Any

from odoo import _, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class APSExamPaperImportAnalyse(models.Model):
    _inherit = 'aps.exam.paper.import'

    def action_analyse_pages_with_ai(self):
        """Queue analysis of all rendered pages and show the shared progress dialog."""
        self.ensure_one()
        run = self._create_page_analysis_run()
        if not run:
            # Nothing to analyse: the state was already updated, so re-open
            # the form to refresh the status bar and buttons.
            return self._open_form()
        return self._build_analysis_run_notification(run)

    def _create_page_analysis_run(self, page=None, model=None):
        model = model or self.ai_model_id
        if not model or not model.enabled or not model.provider_id.enabled or not model.supports_vision:
            raise UserError(_('Select an enabled vision-capable AI model first.'))
        if page:
            pages = page
        else:
            pages = self.page_ids.filtered(lambda item: item.attachment_id)
            if self.analysis_scope == 'pending':
                pages = pages.filtered(lambda item: item.ai_state != 'complete')
        if not pages:
            if self.analysis_scope == 'pending' and not page:
                # Nothing left to analyse: mark the import as analysed.
                self.write({'state': 'analysing', 'progress': 60})
                return None
            raise UserError(_('No rendered question-paper pages are available.'))
        pages.write({'ai_state': 'pending', 'error_message': False})
        run = self.env['aps.ai.run'].sudo().create({
            'import_id': self.id,
            'page_ids': [(6, 0, pages.ids)],
            'processor_key': 'exam_page_analysis', 'ai_model_id': model.id,
            'requested_by_id': self.env.user.id,
            'state': 'queued',
            'status_message': _('Queued page analysis...'),
        })
        run._queue_background_processing()
        return run

    def _build_analysis_run_notification(self, run):
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('Page Analysis Started'),
                'message': _('Page analysis is running in the background.'),
                'run_id': run.id, 'run_model': 'aps.ai.run',
                'title': _('Exam Paper Page Analysis'),
            },
        }

    @staticmethod
    def _image_data_uri(attachment):
        image_data = attachment.raw
        if not image_data:
            return False
        mime_type = attachment.mimetype or mimetypes.guess_type(attachment.name or '')[0] or 'image/png'
        return 'data:%s;base64,%s' % (mime_type, base64.b64encode(image_data).decode('ascii'))

    def _analyse_page_image(self, model, page_record):
        page_image = page_record.attachment_id
        image_uri = self._image_data_uri(page_image)
        if not image_uri:
            raise UserError(_('Rendered page %s is empty.') % page_image.name)
        content: list[dict[str, Any]] = [
            {'type': 'text', 'text': (
                'Analyse only page %s of the %s. Return only labels visibly printed on this page. '
                'The current image is exactly %sx%s pixels. Return all region coordinates as pixel '
                'coordinates relative to this exact image size. Include image_width=%s, image_height=%s, '
                'and coordinate_system="pixels" in the JSON response.'
                % (page_record.page_number, page_record.document_type, page_record.width, page_record.height,
                   page_record.width, page_record.height)
            )},
        ]
        content.append({'type': 'image_url', 'image_url': {'url': image_uri}})
        payload = {
            'model': model.model_key,
            'messages': [
                {'role': 'system', 'content': self._vision_system_prompt()},
                {'role': 'user', 'content': content},
            ],
            'temperature': 0,
            'max_completion_tokens': min(model.max_completion_tokens or 1200, 2400),
            'response_format': {'type': 'json_object'},
        }
        result = model._execute_logged_router_call(
            payload,
            request_type='exam_paper_page_analysis',
            related_record=page_record,
        )
        log_record = result.get('log_record')
        if log_record:
            page_record.write({'ai_call_log_id': log_record.id})
        response_json = model._parse_router_response_json(
            model._extract_message_content(result['response_json'])
        )
        if isinstance(response_json, list):
            if len(response_json) == 1 and isinstance(response_json[0], dict) and 'detections' in response_json[0]:
                response_json = response_json[0]
            elif all(isinstance(item, dict) for item in response_json):
                response_json = {'detections': response_json}
        if not isinstance(response_json, dict) or not isinstance(response_json.get('detections'), list):
            raise ValidationError(_('Vision analysis for %s did not return the required detections JSON.') % page_image.name)
        return response_json, result.get('log_record')

    def _merge_page_exclusion_regions(self, page, response):
        """Replace AI zones from this analysis while retaining manual zones."""
        manual_regions = [
            dict(region)
            for region in (page.exclusion_regions or [])
            if isinstance(region, dict) and region.get('source') == 'manual'
        ]
        ai_regions = []
        for index, region in enumerate(response.get('exclusion_zones') or []):
            if not isinstance(region, dict):
                continue
            try:
                bounds = self._scale_region_to_page(region, page, response)
            except (TypeError, ValueError):
                continue
            if not (
                0 <= bounds['x1'] < bounds['x2'] <= page.width
                and 0 <= bounds['y1'] < bounds['y2'] <= page.height
            ):
                continue
            ai_regions.append({
                **bounds,
                'id': 'ai-%s' % (index + 1),
                'source': 'ai',
                'coordinate_system': 'pixels',
                'confidence': region.get('confidence'),
            })
        return manual_regions + ai_regions

    @staticmethod
    def _vision_system_prompt():
        return (
            'You analyse exactly one isolated page of an IGCSE examination paper. Detect question and sub-question '
            'labels and their visual regions. Treat labels as layout markers, including a bare root '
            'number such as "1", a part such as "(b)", or a subpart such as "(i)" at the start of '
            'a line or sentence. Do not require the label to be followed by question text on the same '
            'line. Do not transcribe OCR and do not invent question text. Provide a concise '
            'question_summary of no more than 20 words describing what the student is asked to do; '
            'do not provide an answer. Report the label exactly as '
            'printed on the current page in raw_label; return it exactly as visible. '
            'Return only JSON with this shape: {"image_width": number, "image_height": number, '
            '"coordinate_system": "pixels", "exclusion_zones": [{"x1": number, '
            '"y1": number, "x2": number, "y2": number, "confidence": number}], '
            '"detections": [{"raw_label": string, '
            '"question_summary": string, '
            '"label_kind": "root"|"part"|"subpart"|"continuation", "regions": [{"x1": number, '
            '"y1": number, "x2": number, "y2": number}], "visible_mark": number|null, '
            '"is_answer_space_number": boolean, '
            '"mark_confidence": number, "continues_from_previous_page": boolean, '
            '"continues_on_next_page": boolean, "contains_diagram": boolean, "confidence": number}]}. '
            'Coordinates must be integer pixel coordinates relative to the declared image_width and image_height. Each region must '
            'tightly bound only the printed question identifier itself, such as "Q1", "(a)", or "(i)". Include parentheses '
            'and punctuation that are part of the identifier, but exclude surrounding whitespace, question text, marks, the rest '
            'of the line, and the full question section. Keep the box close to the outer edges of the identifier glyphs, with '
            'no intentional padding. The question_summary is separate and must not affect region size. Include visible '
            'question and mark-scheme section labels, including identifiers printed inside tables. Do not treat column '
            'headings such as "Question Number", "Answer", "Additional Guidance", or "Mark" as identifiers; return '
            'their header band as an exclusion zone when it separates sections. Exclude running page '
            'headers and footers, general instructions, and blank answer spaces. Do not detect standalone numbers printed beside answer lines or boxes; set '
            'exclusion_zones for structural header bands within the question flow that should not be included in a section, '
            'such as a mark-scheme table heading between answers and the next question identifier. Detect these on both '
            'question-paper and mark-scheme pages. The top edge of each zone ends the preceding section; the next '
            'question identifier starts the following section. Do not use exclusion_zones for running page headers, '
            'footers, or general instructions. Return an empty list when no such zones are present. '
            'is_answer_space_number=true for those markers. A bare number starts a root question only when '
            'it begins actual question text. On later pages, resolve (a), (b), '
            '(i), and (ii) as raw labels only. The application will resolve them against the most likely '
            'preceding root/part in a second pass. Read marks printed at the end of question text, commonly as (2), but '
            'do not confuse them with numbering. '
            'Return raw labels only; the application resolves continuation labels across pages. '
            'Never return a detection for a label that is not visibly present on this page. '
            'When uncertain, include the detection with a lower confidence rather than guessing.'
        )
