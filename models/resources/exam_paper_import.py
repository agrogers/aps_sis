import json
import logging
import base64
import mimetypes
import re
from io import BytesIO
from html import escape
from typing import Any

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class APSExamPaperImport(models.Model):
    _name = 'aps.exam.paper.import'
    _description = 'IGCSE Exam Paper Import'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(required=True, tracking=True)
    resource_id = fields.Many2one(
        'aps.resources', string='Exam Paper Resource', required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    question_attachment_id = fields.Many2one(
        'ir.attachment', string='Question Paper PDF', required=True,
        ondelete='restrict', readonly=True,
    )
    mark_scheme_attachment_id = fields.Many2one(
        'ir.attachment', string='Mark Scheme PDF', required=True,
        ondelete='restrict', readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('uploaded', 'Rendered'),
        ('analysing', 'Analysing'),
        ('review', 'Review Required'),
        ('building', 'Building Resources'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    progress = fields.Integer(default=0, tracking=True)
    error_message = fields.Text(readonly=True)
    parser_version = fields.Char(default='1.0', readonly=True)
    ai_model_id = fields.Many2one(
        'aps.ai.model', string='Vision Analysis Model',
        domain="[('enabled', '=', True), ('provider_id.enabled', '=', True), ('supports_vision', '=', True)]",
        help='Vision-capable model used to detect question regions. It must return JSON only.',
    )
    single_page_ai_model_id = fields.Many2one(
        'aps.ai.model', string='Individual Page Vision Model',
        domain="[('enabled', '=', True), ('provider_id.enabled', '=', True), ('supports_vision', '=', True)]",
        help='Optional vision-capable model used when analysing an individual page. Defaults to the main vision model.',
    )
    ocr_ai_model_id = fields.Many2one(
        'aps.ai.model', string='OCR Vision Model',
        domain="[('enabled', '=', True), ('provider_id.enabled', '=', True), ('supports_vision', '=', True)]",
        help='Optional vision-capable model used to convert imported question and mark-scheme images to text.',
    )
    ai_prompt_version = fields.Char(default='1.0', readonly=True)
    render_dpi = fields.Integer(default=150, required=True)
    page_ids = fields.One2many('aps.exam.paper.page', 'import_id', string='Rendered Pages')
    page_count = fields.Integer(compute='_compute_counts')
    section_ids = fields.One2many('aps.exam.paper.section', 'import_id', string='Detected Sections')
    section_count = fields.Integer(compute='_compute_counts')
    warning_count = fields.Integer(compute='_compute_counts')
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)

    _CROP_LEFT = 75
    _CROP_TOP = 85
    _CROP_RIGHT = 75
    _CROP_BOTTOM = 100
    _RENDER_HEIGHT_PIXELS = 1500
    _LABEL_Y_TOLERANCE = 0.025
    _CONTINUATION_TOP_LIMIT = 0.20

    _sql_constraints = [
        ('resource_import_unique', 'unique(resource_id, question_attachment_id, mark_scheme_attachment_id)',
         'This pair of PDFs has already been imported for the resource.'),
    ]

    @api.depends('section_ids', 'section_ids.review_warning')
    def _compute_counts(self):
        for record in self:
            record.section_count = len(record.section_ids)
            record.warning_count = len(record.section_ids.filtered('review_warning'))
            record.page_count = len(record.page_ids)

    def action_render_pages(self):
        self.ensure_one()
        if not 72 <= self.render_dpi <= 300:
            raise ValidationError(_('Render DPI must be between 72 and 300.'))
        try:
            self.write({'progress': 20, 'error_message': False})
            self._render_pdf_pages(self.question_attachment_id, 'question')
            self._render_pdf_pages(self.mark_scheme_attachment_id, 'mark_scheme')
            self.write({'state': 'uploaded', 'progress': 40})
        except Exception as exc:
            _logger.exception('IGCSE page rendering failed for %s', self.display_name)
            self.write({'state': 'failed', 'error_message': str(exc)})
            raise UserError(_('Page rendering failed: %s') % exc) from exc
        return self._open_form()

    def _render_pdf_pages(self, pdf_attachment, document_type):
        try:
            import fitz
        except ImportError as exc:
            raise UserError(_('Page rendering requires the pymupdf package in the Odoo environment.')) from exc
        content = self._attachment_bytes(pdf_attachment)
        if not content:
            raise ValidationError(_('The %s PDF attachment is empty.') % document_type.replace('_', ' '))
        document = fitz.open(stream=content, filetype='pdf')
        page_model = self.env['aps.exam.paper.page']
        existing_pages = self.page_ids.filtered(lambda item: item.document_type == document_type)
        if existing_pages:
            existing_pages.unlink()
        for page_number, page in enumerate(document, 1):
            zoom = self._RENDER_HEIGHT_PIXELS / page.rect.height if page.rect.height else 1.0
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image_data = pixmap.tobytes('png')
            attachment = self.env['ir.attachment'].create({
                'name': '%s-page-%03d.png' % (document_type, page_number),
                'type': 'binary', 'datas': base64.b64encode(image_data),
                'mimetype': 'image/png', 'res_model': self._name, 'res_id': self.id,
                'description': 'Rendered %s page %s at %s DPI' % (document_type, page_number, self.render_dpi),
            })
            page_model.create({
                'import_id': self.id, 'document_type': document_type,
                'page_number': page_number, 'render_dpi': self.render_dpi,
                'width': pixmap.width, 'height': pixmap.height,
                'attachment_id': attachment.id,
            })
        document.close()

    @api.model
    def create_from_resource(self, resource):
        """Create an import job from attachments linked to an existing resource.

        Filenames are deliberately used only for selecting the two source files;
        stable section keys are used later for idempotent resource creation.
        """
        resource.ensure_one()
        if not resource.exists():
            raise UserError(_('The exam-paper resource no longer exists.'))
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', resource._name),
            ('res_id', '=', resource.id),
            ('type', '=', 'binary'),
        ])
        question = attachments.filtered(lambda a: 'que' in (a.name or '').casefold())
        mark_scheme = attachments.filtered(lambda a: 'rms' in (a.name or '').casefold())
        if len(question) != 1 or len(mark_scheme) != 1:
            raise UserError(_(
                'Exactly one question-paper attachment containing "que" and one '
                'mark-scheme attachment containing "rms" are required. Found %s and %s.'
            ) % (len(question), len(mark_scheme)))
        if question.mimetype not in ('application/pdf', 'application/octet-stream'):
            raise ValidationError(_('The question-paper attachment must be a PDF.'))
        if mark_scheme.mimetype not in ('application/pdf', 'application/octet-stream'):
            raise ValidationError(_('The mark-scheme attachment must be a PDF.'))
        existing = self.search([
            ('resource_id', '=', resource.id),
            ('question_attachment_id', '=', question.id),
            ('mark_scheme_attachment_id', '=', mark_scheme.id),
            ('state', '!=', 'cancelled'),
        ], limit=1)
        if existing:
            return existing
        return self.create({
            'name': resource.name or _('IGCSE Exam Paper'),
            'resource_id': resource.id,
            'question_attachment_id': question.id,
            'mark_scheme_attachment_id': mark_scheme.id,
            'state': 'uploaded',
        })

    def action_analyse_pages_with_ai(self):
        """Queue analysis of all rendered pages and show the shared progress dialog."""
        self.ensure_one()
        run = self._create_page_analysis_run()
        return self._build_analysis_run_notification(run)

    def action_detect_sections(self):
        """Build detected sections from the stored page-analysis responses."""
        self.ensure_one()
        summary = self._build_sections_from_page_analysis()
        self.write({'state': 'review', 'progress': 60})
        return self._notification(
            _('Sections Detected'),
            _('%s section(s) added, %s updated, %s already existed.') % (
                summary['added'], summary['updated'], summary['already_existed'],
            ),
            'success',
        )

    def action_ocr_resources(self):
        self.ensure_one()
        sections = self.section_ids.filtered('resource_id')
        if not sections:
            raise UserError(_('No linked sections are available for OCR. Build resources first.'))
        run = self._create_ocr_run(sections)
        return self._build_ocr_run_notification(run)

    def _create_ocr_run(self, sections):
        model = self.ocr_ai_model_id or self.single_page_ai_model_id or self.ai_model_id
        if not model or not model.enabled or not model.provider_id.enabled or not model.supports_vision:
            raise UserError(_('Select an enabled vision-capable OCR model first.'))
        run = self.env['aps.exam.paper.import.run'].sudo().create({
            'import_id': self.id, 'ocr_section_ids': [(6, 0, sections.ids)],
            'run_type': 'ocr', 'ai_model_id': model.id,
            'requested_by_id': self.env.user.id, 'state': 'queued',
            'status_message': _('Queued OCR...'),
        })
        run._queue_background_processing()
        return run

    def _build_ocr_run_notification(self, run):
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_ai_run_progress',
            'params': {
                'runId': run.id,
                'runModel': 'aps.exam.paper.import.run',
                'title': _('OCR Resources'),
            },
        }

    def _create_page_analysis_run(self, page=None, model=None):
        model = model or self.ai_model_id
        if not model or not model.enabled or not model.provider_id.enabled or not model.supports_vision:
            raise UserError(_('Select an enabled vision-capable AI model first.'))
        pages = self.page_ids.filtered(
            lambda item: item.attachment_id
        ) if not page else page
        if not pages:
            raise UserError(_('No rendered question-paper pages are available.'))
        pages.write({'ai_state': 'pending', 'error_message': False})
        run = self.env['aps.exam.paper.import.run'].sudo().create({
            'import_id': self.id,
            'page_ids': [(6, 0, pages.ids)],
            'ai_model_id': model.id,
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
                'run_id': run.id, 'run_model': 'aps.exam.paper.import.run',
                'title': _('Exam Paper Page Analysis'),
            },
        }

    def _ocr_section(self, section, model=None):
        section.ensure_one()
        model = model or self.ocr_ai_model_id or self.single_page_ai_model_id or self.ai_model_id
        if not model or not model.enabled or not model.provider_id.enabled or not model.supports_vision:
            raise UserError(_('Select an enabled vision-capable OCR model first.'))
        resource = self._ocr_resource_for_section(section)
        question_images = self._section_images_from_resource_html(resource, section, 'question')
        answer_images = self._section_images_from_resource_html(resource, section, 'answer')
        section.write({'ocr_state': 'processing', 'ocr_error': False})
        try:
            question_markdown = self._ocr_images(model, question_images, 'question')
            answer_markdown = self._ocr_images(model, answer_images, 'mark scheme')
            question_html = self._ocr_markdown_to_html(model, question_markdown)
            answer_html = self._ocr_markdown_to_html(model, answer_markdown)
            section.write({
                'question_html': question_html or False,
                'answer_html': answer_html or False,
                'ocr_state': 'complete',
                'ocr_model_id': model.id,
                'ocr_error': False,
            })
            self._insert_section_ocr_text(section)
        except Exception as exc:
            section.write({'ocr_state': 'failed', 'ocr_error': str(exc)})
            raise

    def _ocr_images(self, model, images, document_label):
        if not images:
            return ''
        content = [{
            'type': 'text',
            'text': (
                'Convert these ordered %s images into accurate Markdown. The text is primarily OCR: preserve '
                'all visible words, labels, numbers, mathematical notation, marks, alternatives, and meaningful '
                'bold or italic emphasis. Do not invent or silently omit content. If a diagram, graph, circuit, '
                'map, apparatus setup, image, or other meaningful visual appears, add a concise description in '
                'the appropriate location, including labels, relationships, trends, and values that are clearly '
                'visible. Do not describe decorative elements or answer lines. '
                'For a question, describe visuals only when they are relevant to understanding or answering it. '
                'For a mark scheme, rewrite the source layout so it reads naturally as prose: convert borderless '
                'table rows and columns into paragraphs, bullets, numbered points, or bold criterion labels, '
                'making the relationship between each criterion and its marks clear. Preserve alternative answers '
                'and conditions. Do not use Markdown tables unless the source is an actual table that students '
                'must complete or interpret. Return Markdown only, with no preface or commentary.'
            ) % document_label,
        }]
        for attachment in images:
            image_bytes = self._attachment_bytes(attachment)
            if not image_bytes:
                continue
            content.append({
                'type': 'image_url',
                'image_url': {'url': 'data:image/png;base64,%s' % base64.b64encode(
                    image_bytes,).decode('ascii')},
            })
        result = model._execute_logged_router_call({
            'model': model.model_key,
            'messages': [
                {'role': 'system', 'content': 'You are an accurate examination-paper transcription assistant.'},
                {'role': 'user', 'content': content},
            ],
            'temperature': 0,
            'max_completion_tokens': min(model.max_completion_tokens or 2400, 6000),
        }, request_type='ocr', related_record=self)
        return model._extract_message_content(result['response_json'])

    @staticmethod
    def _ocr_markdown_to_html(model, markdown_text):
        """Convert OCR Markdown without introducing resource heading levels."""
        normalized_lines = []
        for line in (markdown_text or '').splitlines():
            heading = re.match(r'^\s*(#{1,6})\s+(.+?)\s*#*\s*$', line)
            if heading:
                text = heading.group(2).strip()
                if len(heading.group(1)) == 1:
                    normalized_lines.append('<p><u><strong>%s</strong></u></p>' % escape(text))
                else:
                    normalized_lines.append('**%s**' % escape(text))
                continue
            normalized_lines.append(line)
        html = model._markdown_to_html('\n'.join(normalized_lines))
        return html

    def _ocr_resource_for_section(self, section):
        resource = self.resource_id.child_ids.filtered(
            lambda item: item.name == (section.root_key or section.display_label)
        )[:1]
        resource = resource or section.resource_id
        if not resource:
            raise UserError(_('No resource is linked to section %s.') % section.display_label)
        return resource

    def _section_images_from_resource_html(self, resource, section, document_type):
        """Return only image attachments inside this section's H1 block."""
        field_name = 'question' if document_type == 'question' else 'answer'
        html = getattr(resource, field_name) or ''
        heading = escape(section.display_label or '')
        block_match = re.search(
            r'<h1>%s</h1>(.*?)(?=<h1>|$)' % re.escape(heading), html, flags=re.S | re.I,
        )
        if not block_match:
            return self.env['ir.attachment']
        attachment_ids = []
        for match in re.finditer(
            r'(?:/web/(?:image|content)/)(\d+)', block_match.group(1), flags=re.I,
        ):
            attachment_id = int(match.group(1))
            if attachment_id not in attachment_ids:
                attachment_ids.append(attachment_id)
        return self.env['ir.attachment'].browse(attachment_ids).exists()

    def _insert_section_ocr_text(self, section):
        resource = self._ocr_resource_for_section(section)
        for field_name, text_field, document_type in (
            ('question', 'question_html', 'question'),
            ('answer', 'answer_html', 'mark_scheme'),
        ):
            html = getattr(resource, field_name) or ''
            marker = 'data-aps-exam-import-section="%s" data-aps-exam-import-document="%s"' % (
                section.id, document_type,
            )
            text_html = getattr(section, text_field) or ''
            summary = 'Question Text' if document_type == 'question' else 'Answer Text'
            block = '<p></p><details class="aps-exam-import-section-ocr aps-exam-import-section-ocr-%s-%s"><summary>%s</summary>%s</details><p></p>' % (
                section.id, document_type, summary, text_html,
            )
            pattern = r'<details[^>]*class=["\'][^"\']*aps-exam-import-section-ocr-%s-%s[^"\']*["\'][^>]*>.*?</details>' % (
                section.id, document_type,
            )
            if re.search(pattern, html, flags=re.S):
                html = re.sub(pattern, block, html, flags=re.S)
            elif marker in html:
                close = html.find('</div>', html.find(marker))
                if close >= 0:
                    close += len('</div>')
                    html = html[:close] + block + html[close:]
            else:
                heading = escape(section.display_label or '')
                section_pattern = r'(<h1>%s</h1>.*?)(?=<h1>|$)' % re.escape(heading)
                if re.search(section_pattern, html, flags=re.S | re.I):
                    html = re.sub(
                        section_pattern,
                        lambda match: match.group(1) + block,
                        html, count=1, flags=re.S | re.I,
                    )
            resource.write({field_name: html})

    def action_open_detected_sections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Detected Sections'),
            'res_model': 'aps.exam.paper.section',
            'view_mode': 'list,form',
            'domain': [('import_id', '=', self.id)],
        }

    def action_open_rendered_pages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rendered Pages'),
            'res_model': 'aps.exam.paper.page',
            'view_mode': 'list,form',
            'domain': [('import_id', '=', self.id)],
        }

    def _build_sections_from_page_analysis(self):
        """Resolve raw labels detected on question pages into sections."""
        self.ensure_one()
        question_detections = self._collect_page_detections('question')
        if not question_detections:
            raise UserError(_('No completed question-paper page analyses are available.'))

        resolved = {}
        for item in question_detections:
            page = item['page']
            detection = item['detection']
            key = self._normalise_key(item['label'])
            section = resolved.setdefault(key, {
                'import_id': self.id,
                'sequence': len(resolved) + 1,
                'source_key': key,
                'display_label': item['label'],
                'root_key': item['root_label'],
                'hierarchy_level': self._label_hierarchy_level(item['label']),
                'maximum_mark': False,
                'question_summary': '',
                'include_resource': True,
                'include_parent_question': False,
                'question_pages': [],
                'question_regions': [],
                'answer_pages': [],
                'answer_regions': [],
                'review_warning': False,
                'match_confidence': 0.0,
            })
            section['question_pages'].append(page.page_number)
            section['question_regions'].extend(self._regions_with_page_data(
                detection.get('regions') or [], page, item['label'], len(section['question_regions']),
                item.get('analysis') or {},
            ))
            if detection.get('include_parent_question') is not None:
                section['include_parent_question'] = detection['include_parent_question']
            if detection.get('question_summary'):
                section['question_summary'] = detection['question_summary']
            if detection.get('visible_mark') is not None and section['maximum_mark'] is False:
                section['maximum_mark'] = detection['visible_mark']
            confidence = detection.get('confidence')
            if confidence is not None:
                section['match_confidence'] = max(section['match_confidence'], confidence)
            section['review_warning'] |= bool(
                detection.get('continues_from_previous_page')
                or detection.get('continues_on_next_page')
                or not detection.get('regions')
                or (confidence is not None and confidence < 0.8)
            )

        for item in self._collect_page_detections('mark_scheme'):
            section = resolved.get(self._normalise_key(item['label']))
            if not section:
                continue
            page = item['page']
            detection = item['detection']
            section['answer_pages'].append(page.page_number)
            section['answer_regions'].extend(self._regions_with_page_data(
                detection.get('regions') or [], page, item['label'], len(section['answer_regions']),
                item.get('analysis') or {},
            ))
            # The mark scheme is authoritative when it reports a mark.
            if detection.get('visible_mark') is not None:
                section['maximum_mark'] = detection['visible_mark']
            section['review_warning'] |= not bool(detection.get('regions'))

        if not resolved:
            raise UserError(_('The AI did not detect any question labels.'))
        section_model = self.env['aps.exam.paper.section']
        existing_sections = {
            section.source_key: section
            for section in self.section_ids
        }
        detected_values = []
        added_count = 0
        updated_count = 0
        already_existed_count = 0
        for section in resolved.values():
            values = dict(
                section,
                question_pages=','.join(str(p) for p in sorted(set(section['question_pages']))),
                question_regions=section['question_regions'],
                answer_pages=','.join(str(p) for p in sorted(set(section['answer_pages']))),
                answer_regions=section['answer_regions'],
                review_warning=section['review_warning'] or section['maximum_mark'] is False,
            )
            existing = existing_sections.get(section['source_key'])
            if existing:
                update_values = {
                    key: value for key, value in values.items()
                    if key not in {
                        'import_id', 'sequence', 'source_key', 'display_label',
                        'hierarchy_level', 'include_resource', 'include_parent_question',
                    }
                }
                if any(existing[key] != value for key, value in update_values.items()):
                    existing.write(update_values)
                    updated_count += 1
                else:
                    already_existed_count += 1
            else:
                detected_values.append(values)
        if detected_values:
            section_model.create(detected_values)
            added_count = len(detected_values)
        return {
            'added': added_count,
            'updated': updated_count,
            'already_existed': already_existed_count,
        }

    @staticmethod
    def _regions_with_page_data(regions, page, label, start_index, analysis):
        result: list[dict[str, Any]] = []
        for index, region in enumerate(regions, start_index):
            original: dict[str, Any] = dict(region)
            region: dict[str, Any] = APSExamPaperImport._scale_region_to_page(original, page, analysis)
            region.update({
                'document_type': page.document_type,
                'page_number': page.page_number,
                'detection_label': label,
                'detection_order': index,
                'ai_coordinates': original,
                'ai_image_width': analysis.get('image_width'),
                'ai_image_height': analysis.get('image_height'),
                'ai_coordinate_system': analysis.get('coordinate_system', 'pixels'),
            })
            result.append(region)
        return result

    @staticmethod
    def _scale_region_to_page(region, page, analysis) -> dict[str, Any]:
        returned_width = float(analysis.get('image_width') or page.width or 1)
        returned_height = float(analysis.get('image_height') or page.height or 1)
        coordinate_system = (analysis.get('coordinate_system') or 'pixels').casefold()
        if coordinate_system in ('pixels', 'pixel'):
            return {
                key: round(float(region.get(key, 0) or 0))
                for key in ('x1', 'y1', 'x2', 'y2')
            }
        scaled = {}
        for axis, dimension, page_dimension in (
            ('x', returned_width, page.width), ('y', returned_height, page.height),
        ):
            for suffix in ('1', '2'):
                key = '%s%s' % (axis, suffix)
                try:
                    value = float(region.get(key, 0) or 0)
                except (TypeError, ValueError):
                    value = 0.0
                if coordinate_system in ('normalized', 'normalized_0_1', '0..1'):
                    value *= dimension
                elif coordinate_system in ('normalized_0_1000', '0..1000'):
                    value *= dimension / 1000
                scaled[key] = round(value * page_dimension / dimension)
        return scaled

    @classmethod
    def _resolve_page_label(cls, raw_label, kind, root_label, part_label):
        # Labels may be printed in several equivalent forms: ``6``, ``(a)``,
        # ``(i)``, ``6(a)(i)``, ``6a(i)``, or ``(a) (i)``. Complete labels
        # provide their own context; contextual labels such as ``(i)`` and
        # ``(a) (i)`` use the preceding root and part tracked across the
        # document, which may have been detected on an earlier page.
        value = (raw_label or '').strip()
        if not value:
            return False, root_label, part_label
        roman_labels = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
        explicit = re.fullmatch(
            r'(?:Q)?(\d+)\s*(?:\(([A-Za-z])\)|([A-Za-z]))?\s*'
            r'(?:\(([ivxIVX]+)\)|\.([ivxIVX]+))?', value,
        )
        if explicit:
            number, explicit_part, plain_part, explicit_subpart, plain_subpart = explicit.groups()
            root_label = 'Q%s' % number
            part_label = (explicit_part or plain_part or '').casefold() or False
            subpart = (explicit_subpart or plain_subpart or '').casefold() or False
            if subpart and subpart not in roman_labels:
                return False, root_label, part_label
            label = '%s%s' % (root_label, part_label or '')
            return '%s.%s' % (label, subpart) if subpart and part_label else label, root_label, part_label

        part_match = re.match(
            r'^\s*\(([A-Za-z])\)\s*(?:\(([ivxIVX]+)\))?', value,
        )
        subpart_match = re.match(r'^\s*\(([ivxIVX]+)\)', value)
        compact = re.sub(r'[^A-Za-z0-9]', '', value).casefold()
        if compact.startswith('q') and compact[1:].isdigit():
            compact = compact[1:]
        if compact.isdigit():
            root_label, part_label = 'Q%s' % compact, False
            return root_label, root_label, part_label
        if not root_label:
            return False, root_label, part_label
        if subpart_match:
            subpart = subpart_match.group(1).casefold()
            if part_label and subpart in {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}:
                return '%s%s.%s' % (root_label, part_label, subpart), root_label, part_label
        if part_match and kind in ('part', 'subpart', 'continuation'):
            candidate_part = part_match.group(1).casefold()
            if candidate_part in roman_labels:
                return False, root_label, part_label
            part_label = candidate_part
            subpart = part_match.group(2)
            if subpart and subpart.casefold() in roman_labels:
                return '%s%s.%s' % (root_label, part_label, subpart.casefold()), root_label, part_label
            return '%s%s' % (root_label, part_label), root_label, part_label
        return False, root_label, part_label

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
            '"coordinate_system": "pixels", "detections": [{"raw_label": string, '
            '"question_summary": string, '
            '"label_kind": "root"|"part"|"subpart"|"continuation", "regions": [{"x1": number, '
            '"y1": number, "x2": number, "y2": number}], "visible_mark": number|null, '
            '"is_answer_space_number": boolean, '
            '"mark_confidence": number, "continues_from_previous_page": boolean, '
            '"continues_on_next_page": boolean, "contains_diagram": boolean, "confidence": number}]}. '
            'Coordinates must be integer pixel coordinates relative to the declared image_width and image_height. Include only actual '
            'answer-bearing question parts; exclude headers, footers, general instructions, and blank '
            'answer spaces. Do not detect standalone numbers printed beside answer lines or boxes; set '
            'is_answer_space_number=true for those markers. A bare number starts a root question only when '
            'it begins actual question text. On later pages, resolve (a), (b), '
            '(i), and (ii) as raw labels only. The application will resolve them against the most likely '
            'preceding root/part in a second pass. Read marks printed at the end of question text, commonly as (2), but '
            'do not confuse them with numbering. '
            'Return raw labels only; the application resolves continuation labels across pages. '
            'Never return a detection for a label that is not visibly present on this page. '
            'When uncertain, include the detection with a lower confidence rather than guessing.'
        )

    def action_validate(self):
        self.ensure_one()
        errors = []
        seen = set()
        sections = self.section_ids.filtered('include_resource')
        for section in sections:
            if section.source_key in seen:
                errors.append(_('Duplicate section: %s') % section.display_label)
            seen.add(section.source_key)
            if not section.question_regions:
                errors.append(_('%s has no question-page region.') % section.display_label)
            if not section.answer_regions:
                errors.append(_('%s has no mark-scheme region.') % section.display_label)
            if section.maximum_mark in (False, None):
                errors.append(_('%s has no maximum mark.') % section.display_label)
        if errors:
            raise ValidationError('\n'.join(errors))
        return self._notification(_('Validation passed'), _('The detected sections are ready to build resources.'), 'success')

    def _section_regions(self, section, document_type):
        field_name = 'question_regions' if document_type == 'question' else 'answer_regions'
        regions = [dict(region) for region in (getattr(section, field_name) or [])]
        if document_type == 'question' and section.include_parent_question:
            parent = self._find_parent_section(section)
            if parent:
                regions = self._section_regions(parent, document_type) + regions
        return regions

    def _find_parent_section(self, section):
        """Find the nearest earlier, lower-level question section in the same root."""
        if not section.root_key or not section.hierarchy_level:
            return self.env['aps.exam.paper.section']
        root_key = self._normalise_key(section.root_key)
        candidates = self.section_ids.filtered(
            lambda candidate: candidate.sequence < section.sequence
            and self._normalise_key(candidate.root_key or candidate.source_key) == root_key
            and candidate.hierarchy_level < section.hierarchy_level
        ).sorted(key=lambda candidate: candidate.sequence, reverse=True)
        return candidates[:1]

    def _append_image_update_log(self, section, message):
        section.write({
            'image_update_log': '%s[%s] %s\n' % (
                section.image_update_log or '', fields.Datetime.now(), message,
            ),
        })

    def _page_label_positions(self, document_type):
        positions = {}
        for item in self._collect_page_detections(document_type):
            regions = item['detection'].get('regions') or []
            if not regions:
                continue
            page = item['page']
            scaled_regions = [
                self._scale_region_to_page(region, page, item.get('analysis') or {})
                for region in regions
            ]
            y_value = min(
                float(region.get('y1', 0) or 0) / page.height
                for region in scaled_regions
            )
            positions.setdefault(item['page'].page_number, []).append({
                'label': item['label'], 'y': y_value,
            })
        for values in positions.values():
            values.sort(key=lambda value: value['y'])
        return positions

    @staticmethod
    def _region_y_as_fraction(region, page):
        try:
            y_value = float(region.get('y1', 0))
        except (TypeError, ValueError):
            return 0.0
        coordinate_system = (region.get('ai_coordinate_system') or '').casefold()
        if coordinate_system in ('pixels', 'pixel'):
            return y_value / page.height if page.height else 0.0
        return APSExamPaperImport._coordinate_as_fraction(y_value, page.height)

    @staticmethod
    def _coordinate_as_fraction(value, dimension):
        """Convert AI coordinates from 0..1, 0..1000, or rendered pixels."""
        if value <= 1:
            return value
        if value <= 1000:
            return value / 1000
        return value / dimension if dimension else 0.0

    @staticmethod
    def _coordinate_scale(region):
        values = []
        for key in ('x1', 'y1', 'x2', 'y2'):
            try:
                values.append(float(region.get(key, 0) or 0))
            except (TypeError, ValueError):
                continue
        if not values or max(values) <= 1:
            return 'normalized 0..1'
        if max(values) <= 1000:
            return 'normalized 0..1000'
        return 'rendered pixels'

    def _crop_bounds(self, region, page, label_positions):
        start_y = max(0.0, min(1.0, self._region_y_as_fraction(region, page)))
        next_y = None
        for candidate in label_positions.get(page.page_number, []):
            if candidate['y'] > start_y + self._LABEL_Y_TOLERANCE:
                next_y = candidate['y']
                break
        left = max(0, min(page.width, self._CROP_LEFT))
        top = max(0, min(page.height, max(self._CROP_TOP, round(start_y * page.height) - 10)))
        right = max(left + 1, min(page.width, page.width - self._CROP_RIGHT))
        bottom = page.height if next_y is None else round(next_y * page.height)
        bottom_limit = max(top + 1, page.height - self._CROP_BOTTOM)
        bottom = bottom_limit if next_y is None else round(next_y * page.height)
        bottom = max(top + 1, min(bottom_limit, bottom))
        return left, top, right, bottom

    def _crop_section_images(self, section, document_type, log=False):
        label_positions = self._page_label_positions(document_type)
        images = []
        seen = set()
        regions = self._section_regions(section, document_type)
        if log:
            self._append_image_update_log(section, '%s: found %s region(s), label positions on page(s): %s.' % (
                document_type, len(regions), ', '.join(str(page) for page in sorted(label_positions)) or 'none',
            ))
        for index, region in enumerate(regions, 1):
            page_number = region.get('page_number')
            if not page_number:
                pages = [value for value in (section.question_pages if document_type == 'question' else section.answer_pages or '').split(',') if value]
                page_number = int(pages[index - 1]) if index <= len(pages) else False
            try:
                page_number = int(page_number) if page_number else False
            except (TypeError, ValueError):
                page_number = False
            page = self.page_ids.filtered(
                lambda item: item.document_type == document_type and item.page_number == page_number
            )[:1]
            if not page or not page.width or not page.height:
                if log:
                    self._append_image_update_log(section, '%s region %s: no rendered image/page found for page %s.' % (
                        document_type, index, page_number or 'unknown',
                    ))
                continue
            bounds = self._crop_bounds(region, page, label_positions)
            if log:
                self._append_image_update_log(section, '%s region %s: raw coordinates=%s (%s), page %s image %sx%s, crop x=%s..%s y=%s..%s.' % (
                    document_type, index, region, self._coordinate_scale(region), page_number,
                    page.width, page.height, *bounds,
                ))
            key = (page.id, bounds)
            if key in seen:
                if log:
                    self._append_image_update_log(section, '%s region %s: duplicate crop skipped.' % (document_type, index))
                continue
            seen.add(key)
            images.append((page, bounds))
        return images

    def _remove_section_images(self, resource, section):
        marker = 'aps_exam_import_section:%s' % section.id
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.resources'), ('res_id', '=', resource.id),
            ('description', 'ilike', marker),
        ])
        attachments.unlink()
        pattern = r'<div[^>]*data-aps-exam-import-section=["\']%s["\'][^>]*>.*?</div>' % section.id
        return re.sub(pattern, '', resource.question or '', flags=re.S), re.sub(pattern, '', resource.answer or '', flags=re.S)

    def _replace_section_images(self, resource, section, document_type, html, log=False):
        marker_pattern = r'<div[^>]*data-aps-exam-import-section=["\']%s["\'][^>]*>.*?</div>' % section.id
        if re.search(marker_pattern, html or '', flags=re.S):
            if log:
                self._append_image_update_log(section, '%s: existing generated block found; replacing it.' % document_type)
            return re.sub(marker_pattern, self._build_section_image_html(resource, section, document_type, log=log), html, flags=re.S)
        heading = '<h1>%s</h1>' % escape(section.display_label)
        image_html = self._build_section_image_html(resource, section, document_type, log=log)
        if log:
            self._append_image_update_log(section, '%s: heading %s.' % (
                document_type, 'found; inserting generated HTML' if heading in (html or '') else 'not found; generated HTML was not inserted',
            ))
        return (html or '').replace(heading, heading + image_html, 1)

    def _build_section_image_html(self, resource, section, document_type, log=False):
        blocks = []
        for index, (page, bounds) in enumerate(self._crop_section_images(section, document_type, log=log), 1):
            image = page.attachment_id
            image_bytes = self._attachment_bytes(image)
            if not image_bytes:
                if log:
                    self._append_image_update_log(section, '%s image on page %s: source attachment %s has no bytes.' % (
                        document_type, page.page_number, image.id,
                    ))
                continue
            try:
                from PIL import Image
                with Image.open(BytesIO(image_bytes)) as source:
                    crop = source.crop(bounds)
                    output = BytesIO()
                    crop.save(output, format='PNG', optimize=True)
                    crop_bytes = output.getvalue()
            except ImportError as exc:
                raise UserError(_('Image insertion requires the Pillow package in the Odoo environment.')) from exc
            attachment = self.env['ir.attachment'].create({
                'name': 'exam-import-%s-%s-%s.png' % (section.source_key, document_type, index),
                'type': 'binary', 'datas': base64.b64encode(crop_bytes),
                'mimetype': 'image/png', 'res_model': 'aps.resources', 'res_id': resource.id,
                'description': 'aps_exam_import_section:%s document:%s page:%s' % (
                    section.id, document_type, page.page_number,
                ),
            })
            if log:
                self._append_image_update_log(section, '%s image on page %s: created crop attachment %s (%s bytes).' % (
                    document_type, page.page_number, attachment.id, len(crop_bytes),
                ))
            blocks.append(
                '<p><img src="/web/image/%s" class="img-fluid" style="width: 100%%;" alt="%s %s page %s"></img></p>' % (
                    attachment.id, escape(section.display_label), document_type, page.page_number,
                )
            )
        if not blocks:
            if log:
                self._append_image_update_log(section, '%s: no image HTML was generated.' % document_type)
            return ''
        return '<div data-aps-exam-import-section="%s" data-aps-exam-import-document="%s">%s</div>' % (
            section.id, document_type, ''.join(blocks),
        )

    def _refresh_section_images(self, section):
        section.ensure_one()
        section.write({'image_update_log': '[%s] Refresh started for %s.\n' % (
            fields.Datetime.now(), section.display_label,
        )})
        if not section.resource_id:
            self._append_image_update_log(section, 'Stopped: section has no linked resource. Build Resources first.')
            raise UserError(_('Build the resources before inserting section images.'))
        resource = section.import_id.resource_id.child_ids.filtered(
            lambda item: item.name == (section.root_key or section.display_label)
        )[:1]
        if not resource:
            resource = section.resource_id
        self._append_image_update_log(section, 'Target resource is %s (%s); section resource is %s.' % (
            resource.display_name if resource else 'not found',
            resource.id if resource else 'unknown',
            section.resource_id.id,
        ))
        if not resource:
            self._append_image_update_log(section, 'Stopped: no second-level root resource was found.')
            raise UserError(_('The second-level resource for this section was not found.'))
        question, answer = self._remove_section_images(resource, section)
        self._append_image_update_log(section, 'Removed previous generated image blocks. Existing text was retained.')
        question = self._replace_section_images(resource, section, 'question', question, log=True)
        answer = self._replace_section_images(resource, section, 'mark_scheme', answer, log=True)
        resource.write({'question': question, 'answer': answer})
        self._append_image_update_log(section, 'Resource %s updated: question HTML=%s characters, answer HTML=%s characters.' % (
            resource.id, len(question), len(answer),
        ))
        self._append_image_update_log(section, 'Refresh completed.')

    def _append_section_content(self, root, section, headings, answers):
        question_html = self._build_section_image_html(root, section, 'question')
        answer_html = self._build_section_image_html(root, section, 'mark_scheme')
        headings.append('<h1>%s</h1>%s' % (escape(section.display_label), question_html))
        answers.append('<h1>%s</h1>%s' % (escape(section.display_label), answer_html))

    def action_build_resources(self):
        self.ensure_one()
        self.write({'state': 'building', 'progress': 70})
        roots = {}
        created_resource_count = 0
        reused_resource_count = 0
        included_sections = self.section_ids.filtered('include_resource').sorted(
            key=lambda s: (s.sequence, s.source_key)
        )
        for section in included_sections:
            root_key = section.root_key or section.source_key
            root = roots.get(root_key)
            if not root:
                existing_child_ids = set(self.resource_id.child_ids.ids)
                root = self._find_or_create_resource(root_key, self.resource_id)
                if root.id in existing_child_ids:
                    reused_resource_count += 1
                else:
                    created_resource_count += 1
                roots[root_key] = root

        sections_by_root = {}
        for section in included_sections:
            sections_by_root.setdefault(section.root_key or section.source_key, []).append(section)

        for root_key, sections in sections_by_root.items():
            root = roots[root_key]
            headings = []
            answers = []
            total_marks = 0.0
            root_pages = set()
            root_regions = []
            for section in sections:
                self._remove_section_images(root, section)
            for section in sections:
                # The root-number detection (for example Q1) identifies the
                # second-level resource. It is not a child of itself. Only
                # mark-bearing descendants such as Q1a or Q1b.i become
                # third-level resources.
                if self._normalise_key(section.display_label) == self._normalise_key(root.name):
                    root_pages.update(filter(None, (section.question_pages or '').split(',')))
                    root_regions.extend(section.question_regions or [])
                    continue
                existing_child_ids = set(root.child_ids.ids)
                child = self._find_or_create_resource(section.display_label, root)
                if child.id in existing_child_ids:
                    reused_resource_count += 1
                else:
                    created_resource_count += 1
                question_regions = self._section_regions(section, 'question')
                question_pages = set(filter(None, (section.question_pages or '').split(',')))
                question_pages.update(
                    str(region['page_number'])
                    for region in question_regions
                    if region.get('page_number')
                )
                root_pages.update(question_pages)
                total_marks += section.maximum_mark or 0.0
                root_regions.extend(question_regions)
                self._append_section_content(root, section, headings, answers)
                child.write({
                    'has_question': 'use_parent',
                    'has_answer': 'use_parent',
                    'marks': section.maximum_mark,
                    'description': section.question_summary or False,
                })
                section.resource_id = child.id
                section.write({'resource_key': str(child.id)})

            root.write({
                'has_child_resources': 'yes',
                'has_question': 'yes',
                'has_answer': 'yes',
                'question': ''.join(headings),
                'answer': ''.join(answers),
                'marks': total_marks,
                'description': False,
            })
        self.write({'state': 'completed', 'progress': 100, 'completed_at': fields.Datetime.now()})
        return self._notification(
            _('Import completed'),
            _('%s resource(s) created; %s existing resource(s) reused.') % (
                created_resource_count, reused_resource_count,
            ),
            'success',
        )

    def action_retry(self):
        self.ensure_one()
        if self.state != 'failed':
            raise UserError(_('Only failed imports can be retried.'))
    def _find_or_create_resource(self, name, parent):
        child = parent.child_ids.filtered(lambda r: r.name == name)[:1]
        if child:
            return child
        resource_type = self.env['aps.resource.types'].search([
            ('name', '=', 'Question (Past Paper)'),
        ], limit=1)
        if not resource_type:
            raise UserError(_('The resource type "Question (Past Paper)" was not found.'))
        return self.env['aps.resources'].create({
            'name': name,
            'parent_ids': [(4, parent.id)],
            'primary_parent_id': parent.id,
            'subjects': [(6, 0, parent.subjects.ids)],
            'type_id': resource_type.id,
            'has_question': 'no',
            'has_answer': 'no',
            'category': 'mandatory',
        })

    def _collect_page_detections(self, document_type):
        """Return raw AI detections resolved in page order for one document."""
        result = []
        root_label = False
        part_label = False
        pages = self.page_ids.filtered(
            lambda page: page.document_type == document_type and page.ai_state == 'complete'
        ).sorted('page_number')
        for page in pages:
            detections = list(enumerate((page.ai_response or {}).get('detections', [])))
            detections.sort(key=lambda item: (
                min((float(region.get('y1', 0) or 0) for region in item[1].get('regions', [])
                     if isinstance(region, dict)), default=float('inf')),
                item[0],
            ))
            for _, detection in detections:
                raw_label = (detection.get('raw_label') or detection.get('display_label') or '').strip()
                if not raw_label:
                    continue
                if self._is_answer_space_number(detection, raw_label, page):
                    continue
                label, root_label, part_label = self._resolve_page_label(
                    raw_label, detection.get('label_kind', ''), root_label, part_label,
                )
                if label:
                    result.append({
                        'page': page, 'detection': detection,
                        'label': label, 'root_label': root_label,
                        'analysis': page.ai_response or {},
                    })
        return result

    @staticmethod
    def _is_answer_space_number(detection, raw_label, page):
        """Exclude numbered answer lines that resemble root-question labels."""
        if detection.get('is_answer_space_number') is True:
            return True
        if not re.fullmatch(r'\d+', raw_label) or detection.get('label_kind') not in ('root', ''):
            return False
        if (detection.get('question_summary') or '').strip():
            return False
        regions = [region for region in detection.get('regions') or [] if isinstance(region, dict)]
        if not regions or not page.width or not page.height:
            return False
        try:
            width = max(float(region.get('x2', 0)) - float(region.get('x1', 0)) for region in regions)
            height = max(float(region.get('y2', 0)) - float(region.get('y1', 0)) for region in regions)
        except (TypeError, ValueError):
            return False
        return width <= page.width * 0.2 and height <= page.height * 0.08

    @staticmethod
    def _normalise_key(value):
        return re.sub(r'[^a-z0-9]', '', value.casefold()).removeprefix('q')

    @staticmethod
    def _label_hierarchy_level(label):
        value = (label or '').casefold()
        if '.' in value:
            return 3
        if re.search(r'\d+[a-z](?:$|[^a-z])', value):
            return 2
        return 1

    @staticmethod
    def _attachment_bytes(attachment):
        return attachment.raw or b''

    def _open_form(self):
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name,
            'res_id': self.id, 'view_mode': 'form', 'target': 'current',
        }

    def _notification(self, title, message, msg_type='info'):
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': title, 'message': message, 'type': msg_type,
        }}


class APSExamPaperSection(models.Model):
    _name = 'aps.exam.paper.section'
    _description = 'IGCSE Exam Paper Section'
    _order = 'sequence, id'

    import_id = fields.Many2one('aps.exam.paper.import', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    source_key = fields.Char(required=True, index=True)
    display_label = fields.Char(required=True)
    root_key = fields.Char()
    hierarchy_level = fields.Integer(
        string='Hierarchy Level', default=1, index=True,
        help='Question nesting level: 1=root, 2=part, 3=subpart. Editable during review.',
    )
    resource_id = fields.Many2one('aps.resources', readonly=True, ondelete='set null')
    resource_key = fields.Char(readonly=True)
    maximum_mark = fields.Float(string='Maximum Mark', digits=(16, 1))
    question_summary = fields.Char(string='Question Summary')
    include_resource = fields.Boolean(
        string='Include Resource', default=True,
        help='When enabled, create or update an LMS resource for this detected section.',
    )
    include_parent_question = fields.Boolean(
        string='Include Parent Question Content', default=False,
        help='Include the parent/root question region and content when building this section resource.',
    )
    question_html = fields.Html(string='Question HTML')
    answer_html = fields.Html(string='Answer HTML')
    question_pages = fields.Char()
    question_regions = fields.Json(string='Question Regions')
    answer_pages = fields.Char()
    answer_regions = fields.Json(string='Answer Regions')
    match_confidence = fields.Float(string='Match Confidence')
    ocr_confidence = fields.Float(string='OCR Confidence')
    review_warning = fields.Boolean(string='Review Required')
    review_notes = fields.Text()
    image_update_log = fields.Text(string='Image Update Log', readonly=True)
    ocr_state = fields.Selection([
        ('pending', 'Pending'), ('processing', 'Processing'),
        ('complete', 'Complete'), ('failed', 'Failed'),
    ], default='pending', string='OCR Status', readonly=True)
    ocr_model_id = fields.Many2one('aps.ai.model', string='OCR Model', readonly=True)
    ocr_error = fields.Text(string='OCR Error', readonly=True)

    _sql_constraints = [
        ('import_source_key_unique', 'unique(import_id, source_key)', 'Each detected section must have a unique source key.'),
    ]

    def action_update_resource_images(self):
        self.ensure_one()
        self.import_id._refresh_section_images(self)
        return {
            'type': 'ir.actions.act_window', 'name': _('Imported Section'),
            'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'current',
        }

    def action_ocr_section(self):
        self.ensure_one()
        if not self.resource_id:
            raise UserError(_('Build a resource for this section before running OCR.'))
        run = self.import_id._create_ocr_run(self)
        return self.import_id._build_ocr_run_notification(run)


class APSExamPaperPage(models.Model):
    _name = 'aps.exam.paper.page'
    _description = 'Rendered Exam Paper Page'
    _order = 'document_type, page_number'

    import_id = fields.Many2one('aps.exam.paper.import', required=True, ondelete='cascade', index=True)
    document_type = fields.Selection([
        ('question', 'Question Paper'), ('mark_scheme', 'Mark Scheme'),
    ], required=True, index=True)
    page_number = fields.Integer(required=True)
    render_dpi = fields.Integer(required=True)
    width = fields.Integer(readonly=True)
    height = fields.Integer(readonly=True)
    attachment_id = fields.Many2one('ir.attachment', required=True, ondelete='cascade', readonly=True)
    ai_response = fields.Json(readonly=True)
    ai_call_log_id = fields.Many2one('aps.ai.call.log', string='AI Call Log', readonly=True, ondelete='set null')
    ai_state = fields.Selection([
        ('pending', 'Pending'), ('complete', 'Complete'), ('failed', 'Failed'),
    ], default='pending', required=True)
    error_message = fields.Text(readonly=True)

    _sql_constraints = [
        ('page_render_unique', 'unique(import_id, document_type, page_number, render_dpi)',
         'A page can only be rendered once at the same DPI for an import.'),
    ]

    def action_view_page(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=false' % self.attachment_id.id,
            'target': 'new',
        }

    def action_view_analysis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Page Analysis'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_delete(self):
        self.ensure_one()
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

    def unlink(self):
        attachments = self.mapped('attachment_id')
        result = super().unlink()
        attachments.unlink()
        return result

    def action_analyse_page_with_ai(self):
        self.ensure_one()
        run = self.import_id._create_page_analysis_run(
            self, model=self.import_id.single_page_ai_model_id or self.import_id.ai_model_id,
        )
        return self.import_id._build_analysis_run_notification(run)


class APSExamPaperImportRun(models.Model):
    _name = 'aps.exam.paper.import.run'
    _description = 'Exam Paper Page Analysis Run'
    _inherit = ['aps.ai.run.mixin']
    _order = 'create_date desc, id desc'

    import_id = fields.Many2one('aps.exam.paper.import', required=True, ondelete='cascade', readonly=True)
    page_ids = fields.Many2many(
        'aps.exam.paper.page', 'aps_exam_import_run_page_rel',
        'run_id', 'page_id', string='Pages', readonly=True,
    )
    ai_model_id = fields.Many2one('aps.ai.model', readonly=True)
    run_type = fields.Selection([('analysis', 'Page Analysis'), ('ocr', 'OCR')], default='analysis', readonly=True)
    ocr_section_ids = fields.Many2many(
        'aps.exam.paper.section', 'aps_exam_import_run_section_rel',
        'run_id', 'section_id', string='OCR Sections', readonly=True,
    )

    def _process_background(self):
        self.ensure_one()
        if self.state not in ('queued', 'running'):
            return
        started_perf = __import__('time').perf_counter()
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
                sections = self.ocr_section_ids.filtered('resource_id')
                updated = failed = 0
                for index, section in enumerate(sections, 1):
                    self._write_progress({'status_message': _('OCR %s section %s of %s...') % (
                        section.display_label, index, len(sections),
                    )})
                    try:
                        importer._ocr_section(section, model=model)
                        updated += 1
                    except Exception as exc:
                        failed += 1
                        _logger.exception('OCR failed for exam paper section %s', section.display_label)
                    self._write_progress({'status_message': _('Completed OCR section %s.') % section.display_label})
                self._write_progress({
                    'state': 'completed', 'status_message': _('Completed.'),
                    'result_message': _('%s section(s) updated; %s failed.') % (updated, failed),
                    'finished_at': fields.Datetime.now(),
                    'duration_ms': int((__import__('time').perf_counter() - started_perf) * 1000),
                })
                return
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
            self._write_progress({
                'state': 'completed',
                'status_message': _('Completed.'),
                'result_message': _('Analysed %s rendered page(s).') % total,
                'finished_at': fields.Datetime.now(),
                'duration_ms': int((__import__('time').perf_counter() - started_perf) * 1000),
            })
        except Exception as exc:
            self._write_progress({
                'state': 'failed', 'status_message': _('Failed.'),
                'error_message': str(exc), 'finished_at': fields.Datetime.now(),
                'duration_ms': int((__import__('time').perf_counter() - started_perf) * 1000),
            })


class APSResourceExamPaperImport(models.Model):
    _inherit = 'aps.resources'

    exam_import_ids = fields.One2many('aps.exam.paper.import', 'resource_id', string='Exam Imports')
    exam_import_count = fields.Integer(compute='_compute_exam_import_count', store=True)
    detected_section_count = fields.Integer(compute='_compute_exam_import_count', store=True)
    rendered_page_count = fields.Integer(compute='_compute_exam_import_count', store=True)

    @api.depends('exam_import_ids')
    def _compute_exam_import_count(self):
        for resource in self:
            resource.exam_import_count = len(resource.exam_import_ids)
            resource.detected_section_count = sum(resource.exam_import_ids.mapped('section_count'))
            resource.rendered_page_count = sum(resource.exam_import_ids.mapped('page_count'))

    def action_open_exam_imports(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Exam Paper Imports'),
            'res_model': 'aps.exam.paper.import', 'view_mode': 'list,form',
            'domain': [('resource_id', '=', self.id)],
            'context': {'default_resource_id': self.id},
        }

    def action_open_detected_sections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Detected Sections'),
            'res_model': 'aps.exam.paper.section', 'view_mode': 'list,form',
            'domain': [('import_id.resource_id', '=', self.id)],
        }

    def action_open_rendered_pages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Rendered Pages'),
            'res_model': 'aps.exam.paper.page', 'view_mode': 'list,form',
            'domain': [('import_id.resource_id', '=', self.id)],
        }

    def action_start_exam_paper_import(self):
        self.ensure_one()
        job = self.env['aps.exam.paper.import'].create_from_resource(self)
        return job._open_form()
