"""Detected exam paper section model."""
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


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
    maximum_mark = fields.Float(string='Out Of', digits=(16, 1))
    question_summary = fields.Char(string='Question Summary')
    include_resource = fields.Boolean(
        string='Inc. Resource', default=True,
        help='When enabled, create or update an LMS resource for this detected section.',
    )
    include_parent_question = fields.Boolean(
        string='Inc. Parent Question Content', default=False,
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
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Resource Updated'),
                'message': _('The resource images were updated for %s.') % self.display_label,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_section_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Imported Section'),
            'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'current',
        }

    def action_open_region_editor(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_exam_section_region_editor',
            'name': _('Review %s') % self.display_label,
            'target': 'current',
            'params': {'section_id': self.id},
        }

    def get_region_editor_data(self):
        self.ensure_one()
        pages = self.import_id.page_ids.filtered(
            lambda page: page.document_type in ('question', 'mark_scheme')
        )
        return {
            'id': self.id,
            'label': self.display_label,
            'import_name': self.import_id.name,
            'regions': {
                'question': self._editor_regions('question', pages),
                'mark_scheme': self._editor_regions('mark_scheme', pages),
            },
        }

    def _editor_regions(self, document_type, pages):
        field_name = 'question_regions' if document_type == 'question' else 'answer_regions'
        result = []
        for index, region in enumerate(getattr(self, field_name) or []):
            region = dict(region)
            page_number = region.get('page_number')
            page = pages.filtered(
                lambda item: item.document_type == document_type
                and item.page_number == page_number
            )[:1]
            if not page:
                continue
            result.append({
                'index': index,
                'document_type': document_type,
                'label': region.get('detection_label') or self.display_label,
                'page_number': page.page_number,
                'width': page.width,
                'height': page.height,
                'image_url': '/web/content/%s?download=false' % page.attachment_id.id,
                'region': region,
            })
        return result

    def save_region_editor_region(self, document_type, index, bounds):
        self.ensure_one()
        if document_type not in ('question', 'mark_scheme'):
            raise ValidationError(_('Invalid exam document type.'))
        field_name = 'question_regions' if document_type == 'question' else 'answer_regions'
        regions = [dict(region) for region in (getattr(self, field_name) or [])]
        try:
            index = int(index)
            values = {key: int(round(float(bounds[key]))) for key in ('x1', 'y1', 'x2', 'y2')}
        except (KeyError, TypeError, ValueError):
            raise ValidationError(_('Region bounds must contain numeric x1, y1, x2 and y2 values.'))
        if index < 0 or index >= len(regions):
            raise ValidationError(_('The selected region no longer exists.'))
        region = regions[index]
        page = self.import_id.page_ids.filtered(
            lambda item: item.document_type == document_type
            and item.page_number == region.get('page_number')
        )[:1]
        if not page or not page.width or not page.height:
            raise ValidationError(_('The rendered page for this region is unavailable.'))
        if not (0 <= values['x1'] < values['x2'] <= page.width and
                0 <= values['y1'] < values['y2'] <= page.height):
            raise ValidationError(_('Region bounds must fit inside the rendered page.'))
        region.update(values)
        region['coordinate_system'] = 'pixels'
        region['manual'] = True
        regions[index] = region
        self.write({field_name: regions})
        return True

    def action_ocr_section(self):
        self.ensure_one()
        if not self.resource_id:
            raise UserError(_('Build a resource for this section before running OCR.'))
        run = self.import_id._create_ocr_run(self, force=True)
        return self.import_id._build_ocr_run_notification(run)
