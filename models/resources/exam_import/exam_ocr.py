"""OCR of section images into question/answer text."""
import base64
import hashlib
import json
import logging
import mimetypes
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
            question_markdown, question_source = self._get_or_create_ocr_markdown(
                section, model, question_images, 'question',
            )
            answer_markdown, mark_scheme_source = self._get_or_create_ocr_markdown(
                section, model, answer_images, 'mark scheme',
            )
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
            return {
                'question': question_source,
                'mark_scheme': mark_scheme_source,
            }
        except Exception as exc:
            section.write({'ocr_state': 'failed', 'ocr_error': str(exc)})
            raise

    def _get_or_create_ocr_markdown(self, section, model, images, document_label):
        image_data = self._prepare_ocr_images(images)
        cache_key = self._build_ocr_cache_key(model, document_label, image_data)
        cache_prefix = 'question' if document_label == 'question' else 'answer'
        cache_key_field = '%s_ocr_cache_key' % cache_prefix
        cache_markdown_field = '%s_ocr_cache_markdown' % cache_prefix
        if not image_data:
            return '', 'no_images'
        cached_markdown = getattr(section, cache_markdown_field)
        if getattr(section, cache_key_field) == cache_key and cached_markdown:
            return cached_markdown, 'cache_hit'

        markdown = self._ocr_images(
            model,
            images,
            document_label,
            prepared_images=image_data,
        )
        if markdown:
            section.write({
                cache_key_field: cache_key,
                cache_markdown_field: markdown,
            })
        return markdown, 'provider_call'

    @staticmethod
    def _build_ocr_prompt(document_label):
        prompt = (
            'Convert these ordered %s images into accurate Markdown. The text is primarily OCR: preserve '
            'all visible words, labels, numbers, mathematical notation, marks, alternatives, and meaningful '
            'bold or italic emphasis. Do not invent or silently omit content. If a diagram, graph, circuit, '
            'map, apparatus setup, image, or other meaningful visual appears, add a concise description in '
            'the appropriate location, including labels, relationships, trends, and values that are clearly '
            'visible. Do not describe decorative elements or answer lines. '
            'For a question, describe visuals only when they are relevant to understanding or answering it. '
            'Return Markdown only, with no preface or commentary.'
        ) % document_label
        if document_label == 'mark scheme':
            prompt += (
                ' Rewrite the source layout as readable prose, bullets, or numbered points, not a Markdown '
                'table unless the table is itself for students to complete or interpret. For borderless or '
                'unclear tables, infer relationships from visual alignment and proximity rather than assuming '
                'rows are clearly bounded. In a layout with middle and right-hand columns, treat each note in '
                'the right-hand column as explaining the specific item immediately to its left in the middle '
                'column; keep that item, its note, and its marks or conditions together in the same bullet or '
                'paragraph. Do not attach a note to a different item because row boundaries are unclear. If '
                'the visual association is genuinely ambiguous, preserve the note separately and state that its '
                'association is unclear instead of guessing. Preserve alternative answers and conditions. '
                'Expand an acronym only when its full form is strongly supported by the subject context; write '
                'the full form followed by the original acronym in parentheses. Leave ambiguous acronyms '
                'unchanged, and do not expand mathematical symbols, identifiers, or proper names.'
            )
        return prompt

    @staticmethod
    def _build_ocr_system_prompt(document_label):
        return (
            'You are an accurate examination-paper transcription assistant.\n\n%s'
            % APSExamPaperImportOcr._build_ocr_prompt(document_label)
        )

    def _prepare_ocr_images(self, images):
        prepared_images = []
        for attachment in images:
            image_bytes = self._attachment_bytes(attachment)
            if not image_bytes:
                continue
            mime_type = attachment.mimetype or mimetypes.guess_type(attachment.name or '')[0] or 'image/png'
            prepared_images.append({
                'bytes': image_bytes,
                'mime_type': mime_type,
            })
        return prepared_images

    @staticmethod
    def _build_ocr_cache_key(model, document_label, image_data):
        request_fingerprint = {
            'document_label': document_label,
            'system_prompt': APSExamPaperImportOcr._build_ocr_system_prompt(document_label),
            'provider_id': model.provider_id.id,
            'provider_type': model.provider_id.provider_type,
            'api_base_url': model.provider_id.api_base_url or '',
            'model_id': model.id,
            'model_key': model.model_key,
            'max_completion_tokens': min(model.max_completion_tokens or 2400, 6000),
            'temperature': 0,
            'images': [
                {
                    'mime_type': image['mime_type'],
                    'sha256': hashlib.sha256(image['bytes']).hexdigest(),
                }
                for image in image_data
            ],
        }
        serialized_fingerprint = json.dumps(
            request_fingerprint,
            sort_keys=True,
            ensure_ascii=False,
            separators=(',', ':'),
        ).encode('utf-8')
        return hashlib.sha256(serialized_fingerprint).hexdigest()

    def _ocr_images(self, model, images, document_label, prepared_images=None):
        image_data = prepared_images if prepared_images is not None else self._prepare_ocr_images(images)
        if not image_data:
            return ''
        system_content = [{
            'type': 'text',
            'text': self._build_ocr_system_prompt(document_label),
        }]
        user_content = [{
            'type': 'text',
            'text': 'Transcribe the supplied %s images.' % document_label,
        }]
        for image in image_data:
            user_content.append({
                'type': 'image_url',
                'image_url': {'url': 'data:%s;base64,%s' % (
                    image['mime_type'],
                    base64.b64encode(image['bytes']).decode('ascii'),
                )},
            })
        if model.provider_id.provider_type == 'openai':
            system_content[-1]['cache_control'] = {'type': 'ephemeral'}
            user_content.append({
                'type': 'text',
                'text': 'End of source images.',
            })
            user_content[-1]['cache_control'] = {'type': 'ephemeral'}
        result = model._execute_logged_router_call({
            'model': model.model_key,
            'messages': [
                {'role': 'system', 'content': system_content},
                {'role': 'user', 'content': user_content},
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
            r'<h1\b[^>]*>\s*%s\s*</h1>(.*?)(?=<h1\b[^>]*>|$)' % re.escape(heading),
            html,
            flags=re.S | re.I,
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
