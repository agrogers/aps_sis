"""PDF page rendering for exam paper imports."""
import base64
import logging

from odoo import _, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class APSExamPaperImportRender(models.Model):
    _inherit = 'aps.exam.paper.import'

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
