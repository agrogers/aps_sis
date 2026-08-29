import hashlib
import io
import json
import logging
import re
import base64
import mimetypes
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
        ('uploaded', 'Uploaded'),
        ('analysing', 'Analysing'),
        ('review', 'Review Required'),
        ('building', 'Building Resources'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    progress = fields.Integer(default=0, tracking=True)
    error_message = fields.Text(readonly=True)
    question_text = fields.Text(readonly=True)
    mark_scheme_text = fields.Text(readonly=True)
    parser_version = fields.Char(default='1.0', readonly=True)
    ai_model_id = fields.Many2one(
        'aps.ai.model', string='Vision Analysis Model',
        domain="[('enabled', '=', True), ('provider_id.enabled', '=', True), ('supports_vision', '=', True)]",
        help='Vision-capable model used to detect question regions. It must return JSON only.',
    )
    ai_prompt_version = fields.Char(default='1.0', readonly=True)
    render_dpi = fields.Integer(default=150, required=True)
    page_ids = fields.One2many('aps.exam.paper.page', 'import_id', string='Rendered Pages')
    page_count = fields.Integer(compute='_compute_counts')
    question_sha256 = fields.Char(readonly=True)
    mark_scheme_sha256 = fields.Char(readonly=True)
    section_ids = fields.One2many('aps.exam.paper.section', 'import_id', string='Detected Sections')
    section_count = fields.Integer(compute='_compute_counts')
    warning_count = fields.Integer(compute='_compute_counts')
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)

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
        if self.state not in ('uploaded', 'review', 'failed'):
            raise UserError(_('Pages cannot be rendered in the current state.'))
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
        for page_number, page in enumerate(document, 1):
            existing = page_model.search([
                ('import_id', '=', self.id), ('document_type', '=', document_type),
                ('page_number', '=', page_number), ('render_dpi', '=', self.render_dpi),
            ], limit=1)
            if existing:
                continue
            pixmap = page.get_pixmap(dpi=self.render_dpi, alpha=False)
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

    def action_analyse(self):
        self.ensure_one()
        if self.state not in ('uploaded', 'failed', 'review'):
            raise UserError(_('This import cannot be analysed in its current state.'))
        try:
            self.write({
                'state': 'analysing',
                'progress': 10,
                'error_message': False,
                'started_at': fields.Datetime.now(),
            })
            question_bytes = self._attachment_bytes(self.question_attachment_id)
            answer_bytes = self._attachment_bytes(self.mark_scheme_attachment_id)
            question_text = self._extract_pdf_text(question_bytes)
            answer_text = self._extract_pdf_text(answer_bytes)
            self.write({
                'question_text': question_text,
                'mark_scheme_text': answer_text,
                'question_sha256': hashlib.sha256(question_bytes).hexdigest(),
                'mark_scheme_sha256': hashlib.sha256(answer_bytes).hexdigest(),
                'progress': 35,
            })
            self._build_detected_sections(question_text, answer_text)
            self.write({'state': 'review', 'progress': 60})
        except Exception as exc:
            _logger.exception('IGCSE import analysis failed for %s', self.display_name)
            self.write({'state': 'failed', 'error_message': str(exc)})
            raise UserError(_('Analysis failed: %s') % exc) from exc
        return self._open_form()

    def action_analyse_pages_with_ai(self):
        """Analyse already-rendered pages through the selected vision model.

        Rendering is intentionally delegated to a separate adapter. This method
        accepts page images as attachments linked to the source PDF attachment,
        allowing a later renderer/queue worker to populate them independently.
        """
        self.ensure_one()
        model = self.ai_model_id
        if not model or not model.enabled or not model.provider_id.enabled:
            raise UserError(_('Select an enabled vision-capable AI model first.'))
        if not model.supports_vision:
            raise UserError(_('The selected AI model is not marked as vision-capable.'))
        page_images = self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.exam.paper.import'),
            ('res_id', '=', self.id),
            ('mimetype', 'in', ['image/png', 'image/jpeg']),
        ])
        if not page_images:
            raise UserError(_('No rendered page images are attached to this import yet.'))
        for page_image in page_images.sorted('name'):
            page_record = self.env['aps.exam.paper.page'].search([
                ('import_id', '=', self.id), ('attachment_id', '=', page_image.id),
            ], limit=1)
            try:
                response, log_record = self._analyse_page_image(
                    model, page_record, self._page_analysis_context(page_record)
                )
                page_record.write({
                    'ai_response': response,
                    'ai_state': 'complete',
                    'error_message': False,
                    'ai_call_log_id': log_record.id if log_record else False,
                })
            except Exception as exc:
                page_record.write({'ai_state': 'failed', 'error_message': str(exc)})
                _logger.exception('Vision analysis failed for rendered page %s', page_image.name)
        self._build_sections_from_page_analysis()
        self.write({'state': 'review', 'progress': 60})
        return self._open_form()

    def _build_sections_from_page_analysis(self):
        """Resolve raw labels detected on question pages into sections."""
        self.ensure_one()
        pages = self.page_ids.filtered(
            lambda page: page.document_type == 'question' and page.ai_state == 'complete'
        ).sorted('page_number')
        if not pages:
            raise UserError(_('No completed question-paper page analyses are available.'))

        resolved = {}
        root_label = False
        part_label = False
        sequence = 0
        for page in pages:
            for detection in (page.ai_response or {}).get('detections', []):
                raw_label = (detection.get('raw_label') or detection.get('display_label') or '').strip()
                if not raw_label:
                    continue
                full_label, root_label, part_label = self._resolve_page_label(
                    raw_label, detection.get('label_kind', ''), root_label, part_label,
                )
                if not full_label:
                    continue
                key = self._normalise_key(full_label)
                section = resolved.get(key)
                if not section:
                    sequence += 1
                    section = resolved[key] = {
                        'import_id': self.id,
                        'sequence': sequence,
                        'source_key': key,
                        'display_label': full_label,
                        'root_key': root_label,
                        'maximum_mark': False,
                        'question_summary': '',
                        'question_pages': [],
                        'question_regions': [],
                        'review_warning': False,
                        'match_confidence': 0.0,
                    }
                section['question_pages'].append(page.page_number)
                section['question_regions'].extend(detection.get('regions') or [])
                if detection.get('question_summary'):
                    section['question_summary'] = detection['question_summary']
                if detection.get('visible_mark') is not None:
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

        if not resolved:
            raise UserError(_('The AI did not detect any question labels.'))
        self.section_ids.unlink()
        self.env['aps.exam.paper.section'].create([
            dict(
                section,
                question_pages=','.join(str(p) for p in sorted(set(section['question_pages']))),
                question_regions=section['question_regions'],
            )
            for section in resolved.values()
        ])

    @classmethod
    def _resolve_page_label(cls, raw_label, kind, root_label, part_label):
        compact = re.sub(r'[^A-Za-z0-9]', '', raw_label)
        if not compact:
            return False, root_label, part_label
        if compact.casefold().startswith('q') and compact[1:].isdigit():
            compact = compact[1:]
        if compact.isdigit():
            root_label, part_label = 'Q%s' % compact, False
            return root_label, root_label, part_label
        if kind in ('part', 'subpart', 'continuation') or raw_label.startswith('('):
            if not root_label:
                return False, root_label, part_label
            if compact.casefold() in {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}:
                if not part_label:
                    return False, root_label, part_label
                return '%s%s.%s' % (root_label, part_label, compact.casefold()), root_label, part_label
            if len(compact) == 1 and compact.isalpha():
                part_label = compact.casefold()
                return '%s%s' % (root_label, part_label), root_label, part_label
        complete = re.match(r'^(?:Q)?(\d+)([A-Za-z])?(?:([ivx]+))?$', compact, re.I)
        if complete:
            root_label = 'Q%s' % complete.group(1)
            part_label = complete.group(2).casefold() if complete.group(2) else False
            suffix = '.%s' % complete.group(3).casefold() if complete.group(3) else ''
            return '%s%s%s' % (root_label, part_label or '', suffix), root_label, part_label
        return False, root_label, part_label

    def _page_analysis_context(self, page_record):
        previous_pages = self.page_ids.filtered(
            lambda page: page.document_type == page_record.document_type
            and page.page_number < page_record.page_number
        ).sorted('page_number')[-3:]
        labels = []
        for previous in previous_pages:
            for detection in (previous.ai_response or {}).get('detections', []):
                if detection.get('display_label'):
                    labels.append(
                        'page %s: %s' % (previous.page_number, detection['display_label'])
                    )
        if not labels:
            return 'No analysed preceding pages are available.'
        return 'Recent detected labels on preceding pages: %s' % ', '.join(labels)

    def _previous_page_for_analysis(self, page_record):
        return self.page_ids.filtered(
            lambda page: page.document_type == page_record.document_type
            and page.page_number == page_record.page_number - 1
        )[:1]

    @staticmethod
    def _image_data_uri(attachment):
        image_data = attachment.raw
        if not image_data:
            return False
        mime_type = attachment.mimetype or mimetypes.guess_type(attachment.name or '')[0] or 'image/png'
        return 'data:%s;base64,%s' % (mime_type, base64.b64encode(image_data).decode('ascii'))

    def _analyse_page_image(self, model, page_record, page_context=None):
        page_image = page_record.attachment_id
        image_uri = self._image_data_uri(page_image)
        if not image_uri:
            raise UserError(_('Rendered page %s is empty.') % page_image.name)
        previous_page = self._previous_page_for_analysis(page_record)
        previous_uri = self._image_data_uri(previous_page.attachment_id) if previous_page else False
        content: list[dict[str, Any]] = [
            {'type': 'text', 'text': (
                'Analyse only the current page %s of the %s. The previous page image, if supplied, '
                'is context only and must not produce detections. %s'
                % (page_record.page_number, page_record.document_type, page_context or '')
            )},
        ]
        if previous_uri:
            content.extend([
                {'type': 'text', 'text': 'Previous page (context only):'},
                {'type': 'image_url', 'image_url': {'url': previous_uri}},
                {'type': 'text', 'text': 'Current page to detect:'},
            ])
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
        response_json = model._parse_router_response_json(
            model._extract_message_content(result['response_json'])
        )
        if not isinstance(response_json, dict) or not isinstance(response_json.get('detections'), list):
            raise ValidationError(_('Vision analysis for %s did not return the required detections JSON.') % page_image.name)
        return response_json, result.get('log_record')

    @staticmethod
    def _vision_system_prompt():
        return (
            'You analyse one page of an IGCSE examination paper. Pages are sequential and a question '
            'may start with a bare number such as 1 on one page, then continue with labels such as '
            '(a), (i), and (ii) on later pages. Detect question and sub-question '
            'labels and their visual regions. Treat labels as layout markers, including a bare root '
            'number such as "1", a part such as "(b)", or a subpart such as "(i)" at the start of '
            'a line or sentence. Do not require the label to be followed by question text on the same '
            'line. Do not transcribe OCR and do not invent question text. Provide a concise '
            'question_summary of no more than 20 words describing what the student is asked to do; '
            'do not provide an answer. Report the label exactly as '
            'printed on the current page in raw_label; do not combine it with previous-page context. '
            'Return only JSON with this shape: {"detections": [{"raw_label": string, '
            '"question_summary": string, '
            '"label_kind": "root"|"part"|"subpart"|"continuation", "regions": [{"x1": number, '
            '"y1": number, "x2": number, "y2": number}], "visible_mark": number|null, '
            '"mark_confidence": number, "continues_from_previous_page": boolean, '
            '"continues_on_next_page": boolean, "contains_diagram": boolean, "confidence": number}]}. '
            'Coordinates must be normalized from 0 to 1 relative to the image. Include only actual '
            'answer-bearing question parts; exclude headers, footers, general instructions, and blank '
            'answer spaces. A bare number starts a root question. On later pages, resolve (a), (b), '
            '(i), and (ii) as raw labels only. The application will resolve them against the most likely '
            'preceding root/part in a second pass. Read marks printed at the end of question text, commonly as (2), but '
            'do not confuse them with numbering. '
            'Use the previous-page image only to resolve the parent root/part of a current-page label. '
            'Never return a detection for a label that appears only on the previous page. '
            'When uncertain, include the detection with a lower confidence rather than guessing.'
        )

    def action_validate(self):
        self.ensure_one()
        errors = []
        seen = set()
        for section in self.section_ids:
            if section.source_key in seen:
                errors.append(_('Duplicate section: %s') % section.display_label)
            seen.add(section.source_key)
            if not section.question_text:
                errors.append(_('%s has no question text.') % section.display_label)
            if not section.mark_scheme_text:
                errors.append(_('%s has no matching mark-scheme text.') % section.display_label)
            if section.maximum_mark is False:
                errors.append(_('%s has no maximum mark.') % section.display_label)
        if errors:
            raise ValidationError('\n'.join(errors))
        return self._notification(_('Validation passed'), _('The detected sections are ready to build resources.'), 'success')

    def action_build_resources(self):
        self.ensure_one()
        self.action_validate()
        self.write({'state': 'building', 'progress': 70})
        roots = {}
        for section in self.section_ids.sorted(key=lambda s: (s.sequence, s.source_key)):
            root_key = section.root_key or section.source_key
            root = roots.get(root_key)
            if not root:
                root = self._find_or_create_resource(root_key, self.resource_id)
                roots[root_key] = root
            child = self._find_or_create_resource(section.display_label, root)
            child.write({
                'question': section.question_html or '<p>%s</p>' % escape(section.question_ocr or section.question_text or ''),
                'answer': section.answer_html or '<p>%s</p>' % escape(section.answer_ocr or section.mark_scheme_text or ''),
                'has_question': 'yes',
                'has_answer': 'yes',
                'marks': section.maximum_mark,
                'description': _('Imported from %s') % self.name,
            })
            section.resource_id = child.id
            section.write({'resource_key': child.id and str(child.id)})
        self.write({'state': 'completed', 'progress': 100, 'completed_at': fields.Datetime.now()})
        return self._notification(_('Import completed'), _('Resources were created without duplicating existing children.'), 'success')

    def action_retry(self):
        self.ensure_one()
        if self.state != 'failed':
            raise UserError(_('Only failed imports can be retried.'))
        return self.action_analyse()

    def _find_or_create_resource(self, name, parent):
        child = parent.child_ids.filtered(lambda r: r.name == name)[:1]
        if child:
            return child
        return self.env['aps.resources'].create({
            'name': name,
            'parent_ids': [(4, parent.id)],
            'primary_parent_id': parent.id,
            'subjects': [(6, 0, parent.subjects.ids)],
            'type_id': parent.type_id.id,
            'has_question': 'no',
            'has_answer': 'no',
            'category': 'mandatory',
        })

    def _build_detected_sections(self, question_text, answer_text):
        self.section_ids.unlink()
        question_matches = list(re.finditer(
            r'(?im)^\s*((?:q\s*)?\d+(?:\s*[.(]?[a-zivx]+[.)]?)+)\s*(?:\[(\d+(?:\.\d+)?)\])?',
            question_text or '',
        ))
        answer_by_key = self._numbered_blocks(answer_text)
        vals = []
        for sequence, match in enumerate(question_matches, 1):
            label = re.sub(r'\s+', '', match.group(1))
            root_match = re.match(r'^(Q?\d+)', label, re.I)
            if not root_match:
                continue
            start = match.start()
            end = question_matches[sequence].start() if sequence < len(question_matches) else len(question_text)
            question_block = question_text[start:end].strip()
            key = self._normalise_key(label)
            answer_block = answer_by_key.get(key, '')
            mark = float(match.group(2)) if match.group(2) else self._extract_mark(answer_block)
            vals.append({
                'import_id': self.id, 'sequence': sequence,
                'source_key': key, 'display_label': label,
                'root_key': root_match.group(0).upper(), 'maximum_mark': mark,
                'question_text': question_block, 'mark_scheme_text': answer_block,
                'review_warning': not bool(answer_block) or mark is False,
                'match_confidence': 1.0 if answer_block else 0.0,
            })
        if not vals and question_text.strip():
            vals.append({
                'import_id': self.id, 'sequence': 1, 'source_key': 'paper',
                'display_label': 'Paper', 'root_key': 'Paper',
                'question_text': question_text, 'mark_scheme_text': answer_text,
                'review_warning': True,
            })
        self.env['aps.exam.paper.section'].create(vals)

    def _collect_page_detections(self, document_type):
        """Return raw AI detections resolved in page order for one document."""
        result = []
        root_label = False
        part_label = False
        pages = self.page_ids.filtered(
            lambda page: page.document_type == document_type and page.ai_state == 'complete'
        ).sorted('page_number')
        for page in pages:
            for detection in (page.ai_response or {}).get('detections', []):
                raw_label = (detection.get('raw_label') or detection.get('display_label') or '').strip()
                if not raw_label:
                    continue
                label, root_label, part_label = self._resolve_page_label(
                    raw_label, detection.get('label_kind', ''), root_label, part_label,
                )
                if label:
                    result.append({
                        'page': page, 'detection': detection,
                        'label': label, 'root_label': root_label,
                    })
        return result

    @staticmethod
    def _numbered_blocks(text):
        matches = list(re.finditer(
            r'(?im)^\s*((?:q\s*)?\d+(?:\s*[.(]?[a-zivx]+[.)]?)+)', text or ''
        ))
        return {
            APSExamPaperImport._normalise_key(m.group(1)): (
                text[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
            )
            for i, m in enumerate(matches)
        }

    @staticmethod
    def _normalise_key(value):
        return re.sub(r'[^a-z0-9]', '', value.casefold()).removeprefix('q')

    @staticmethod
    def _extract_mark(text):
        marks = re.findall(r'\[(\d+(?:\.\d+)?)\]', text or '')
        return float(marks[-1]) if marks else False

    @staticmethod
    def _attachment_bytes(attachment):
        return attachment.raw or b''

    @staticmethod
    def _extract_pdf_text(content):
        if not content:
            raise ValidationError(_('The PDF attachment is empty.'))
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise UserError(_('PDF extraction requires the pypdf package in the Odoo environment.')) from exc
        reader = PdfReader(io.BytesIO(content))
        return '\n\n'.join(page.extract_text() or '' for page in reader.pages).strip()

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
    resource_id = fields.Many2one('aps.resources', readonly=True, ondelete='set null')
    resource_key = fields.Char(readonly=True)
    maximum_mark = fields.Float(string='Maximum Mark', digits=(16, 1))
    question_text = fields.Text(string='Question Text')
    question_summary = fields.Char(string='Question Summary')
    mark_scheme_text = fields.Text(string='Mark Scheme Text')
    question_html = fields.Html(string='Question HTML')
    answer_html = fields.Html(string='Answer HTML')
    question_ocr = fields.Text(string='Question OCR')
    answer_ocr = fields.Text(string='Answer OCR')
    question_pages = fields.Char()
    question_regions = fields.Json(string='Question Regions')
    answer_pages = fields.Char()
    answer_regions = fields.Json(string='Answer Regions')
    match_confidence = fields.Float(string='Match Confidence')
    ocr_confidence = fields.Float(string='OCR Confidence')
    review_warning = fields.Boolean(string='Review Required')
    review_notes = fields.Text()

    _sql_constraints = [
        ('import_source_key_unique', 'unique(import_id, source_key)', 'Each detected section must have a unique source key.'),
    ]


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

    def action_analyse_page_with_ai(self):
        self.ensure_one()
        importer = self.import_id
        model = importer.ai_model_id
        if not model:
            raise UserError(_('Select a vision-capable AI model on the import job first.'))
        self.write({'ai_state': 'pending', 'error_message': False})
        try:
            response, log_record = importer._analyse_page_image(
                model, self, importer._page_analysis_context(self)
            )
            self.write({
                'ai_response': response,
                'ai_state': 'complete',
                'ai_call_log_id': log_record.id if log_record else False,
            })
        except Exception as exc:
            self.write({'ai_state': 'failed', 'error_message': str(exc)})
            raise UserError(_('Page analysis failed: %s') % exc) from exc
        return self.action_view_analysis()


class APSResourceExamPaperImport(models.Model):
    _inherit = 'aps.resources'

    exam_import_ids = fields.One2many('aps.exam.paper.import', 'resource_id', string='Exam Imports')
    exam_import_count = fields.Integer(compute='_compute_exam_import_count')

    @api.depends('exam_import_ids')
    def _compute_exam_import_count(self):
        for resource in self:
            resource.exam_import_count = len(resource.exam_import_ids)

    def action_start_exam_paper_import(self):
        self.ensure_one()
        job = self.env['aps.exam.paper.import'].create_from_resource(self)
        return job._open_form()
