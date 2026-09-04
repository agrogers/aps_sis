"""OCR of section images into question/answer text."""
import base64
import logging
import re
from html import escape

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSExamPaperImportOcr(models.Model):
    _inherit = 'aps.exam.paper.import'

    def action_ocr_resources(self):
        self.ensure_one()
        sections = self.section_ids.filtered('resource_id')
        if self.analysis_scope == 'all':
            # A full OCR request is an explicit re-run. Reset every linked
            # section before queuing the run so the status reflects that work
            # is pending again, including sections previously marked complete.
            sections.write({'ocr_state': 'pending', 'ocr_error': False})
        elif self.analysis_scope == 'pending':
            sections = sections.filtered(lambda section: section.ocr_state != 'complete')
        if not sections:
            if self.analysis_scope == 'pending':
                raise UserError(_('All linked sections have already been processed by OCR.'))
            raise UserError(_('No linked sections are available for OCR. Build resources first.'))
        run = self._create_ocr_run(sections)
        return self._build_ocr_run_notification(run)

    def _create_ocr_run(self, sections, force=False):
        sections = sections.filtered('resource_id')
        if self.analysis_scope == 'pending' and not force:
            sections = sections.filtered(lambda section: section.ocr_state != 'complete')
        if not sections:
            raise UserError(_('No sections require OCR.'))
        model = self.ocr_ai_model_id or self.single_page_ai_model_id or self.ai_model_id
        if not model or not model.enabled or not model.provider_id.enabled or not model.supports_vision:
            raise UserError(_('Select an enabled vision-capable OCR model first.'))
        run = self.env['aps.ai.run'].sudo().create({
            'import_id': self.id, 'ocr_section_ids': [(6, 0, sections.ids)],
            'processor_key': 'exam_ocr', 'run_type': 'ocr', 'ai_model_id': model.id,
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
                'runModel': 'aps.ai.run',
                'title': _('OCR Resources'),
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
