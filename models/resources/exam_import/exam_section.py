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

    _REBUILD_FIELDS = frozenset({
        'sequence', 'display_label', 'root_key', 'hierarchy_level',
        'maximum_mark', 'question_summary', 'include_resource',
        'include_parent_question', 'question_pages', 'question_regions',
        'answer_pages', 'answer_regions', 'match_confidence', 'review_notes',
    })

    def write(self, vals):
        rebuild_required = bool(self._REBUILD_FIELDS.intersection(vals))
        imports = self.mapped('import_id') if rebuild_required else self.env['aps.exam.paper.import']
        if rebuild_required:
            vals = dict(vals)
            vals.update({
                'ocr_state': 'pending',
                'question_html': False,
                'answer_html': False,
                'ocr_model_id': False,
                'ocr_error': False,
            })
        result = super().write(vals)
        if rebuild_required:
            completed_imports = imports.filtered(lambda item: item.state == 'completed')
            completed_imports.write({
                'state': 'analysing',
                'progress': 60,
                'completed_at': False,
            })
        return result

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
        navigation = self._editor_navigation()
        return {
            'id': self.id,
            'label': self.display_label,
            'import_name': self.import_id.name,
            'navigation': navigation,
            'regions': {
                'question': self._editor_regions('question', pages),
                'mark_scheme': self._editor_regions('mark_scheme', pages),
            },
            'pages': {
                'question': self._editor_pages('question', pages),
                'mark_scheme': self._editor_pages('mark_scheme', pages),
            },
        }

    def _editor_navigation(self):
        """Return the adjacent sections in the same import review order."""
        sections = self.import_id.section_ids.sorted(
            key=lambda section: (section.sequence, section.source_key, section.id)
        )
        position = next(
            (index for index, section in enumerate(sections) if section.id == self.id),
            None,
        )

        def section_data(section):
            return {
                'id': section.id,
                'label': section.display_label,
            } if section else False

        return {
            'previous': section_data(sections[position - 1] if position else False),
            'next': section_data(sections[position + 1] if position is not None and position + 1 < len(sections) else False),
            'position': position + 1 if position is not None else False,
            'count': len(sections),
        }

    def _editor_pages(self, document_type, pages):
        """Return rendered pages that can receive a manually added region."""
        return [
            {
                'id': page.id,
                'document_type': document_type,
                'page_number': page.page_number,
                'width': page.width,
                'height': page.height,
                'image_url': '/web/content/%s?download=false' % page.attachment_id.id,
                'default_region': self._default_editor_region(page),
            }
            for page in pages.filtered(lambda item: item.document_type == document_type).sorted(
                key=lambda item: item.page_number
            )
            if page.width and page.height and page.attachment_id
        ]

    def _default_editor_region(self, page):
        """Return the standard crop as pixel bounds for a rendered page."""
        left_inset = min(self.import_id._CROP_LEFT, max(0, (page.width - 1) // 2))
        right_inset = min(self.import_id._CROP_RIGHT, max(0, page.width - left_inset - 1))
        top_inset = min(self.import_id._CROP_TOP, max(0, (page.height - 1) // 2))
        bottom_inset = min(self.import_id._CROP_BOTTOM, max(0, page.height - top_inset - 1))
        return {
            'x1': left_inset,
            'y1': top_inset,
            'x2': page.width - right_inset,
            'y2': page.height - bottom_inset,
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
                'page_id': page.id,
                'label': region.get('detection_label') or self.display_label,
                'page_number': page.page_number,
                'width': page.width,
                'height': page.height,
                'image_url': '/web/content/%s?download=false' % page.attachment_id.id,
                'region': region,
            })
        return result

    def save_region_editor_region(self, document_type, index, bounds):
        """Compatibility wrapper for saving one existing region."""
        self.ensure_one()
        try:
            index = int(index)
        except (TypeError, ValueError):
            raise ValidationError(_('The selected region is invalid.'))
        self.save_region_editor_changes([{
            'document_type': document_type,
            'index': index,
            'bounds': bounds,
        }], [])
        return True

    def save_region_editor_changes(self, edits=None, additions=None):
        """Persist existing region edits and newly added page regions atomically."""
        self.ensure_one()
        edits = edits or []
        additions = additions or []
        region_values = {
            'question': [dict(region) for region in (self.question_regions or [])],
            'mark_scheme': [dict(region) for region in (self.answer_regions or [])],
        }

        for edit in edits:
            document_type = edit.get('document_type')
            if document_type not in region_values:
                raise ValidationError(_('Invalid exam document type.'))
            try:
                index = int(edit.get('index'))
            except (TypeError, ValueError):
                raise ValidationError(_('The selected region is invalid.'))
            regions = region_values[document_type]
            if index < 0 or index >= len(regions):
                raise ValidationError(_('The selected region no longer exists.'))
            region = regions[index]
            page = self._editor_page(document_type, region.get('page_number'))
            values = self._validated_editor_bounds(edit.get('bounds'), page)
            region.update(values)
            region['coordinate_system'] = 'pixels'
            region['manual'] = True
            regions[index] = region

        for addition in additions:
            document_type = addition.get('document_type')
            if document_type not in region_values:
                raise ValidationError(_('Invalid exam document type.'))
            page = self._editor_page(document_type, addition.get('page_number'))
            values = self._validated_editor_bounds(addition.get('bounds'), page)
            regions = region_values[document_type]
            regions.append({
                **values,
                'document_type': document_type,
                'page_number': page.page_number,
                'detection_label': self.display_label,
                'detection_order': len(regions),
                'coordinate_system': 'pixels',
                'manual': True,
                'manual_added': True,
            })

        self.write({
            'question_regions': region_values['question'],
            'answer_regions': region_values['mark_scheme'],
            'question_pages': self._region_page_string(region_values['question']),
            'answer_pages': self._region_page_string(region_values['mark_scheme']),
        })
        return True

    def _editor_page(self, document_type, page_number):
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            page_number = False
        page = self.import_id.page_ids.filtered(
            lambda item: item.document_type == document_type
            and item.page_number == page_number
        )[:1]
        if not page or not page.width or not page.height or not page.attachment_id:
            raise ValidationError(_('The rendered page for this region is unavailable.'))
        return page

    @staticmethod
    def _validated_editor_bounds(bounds, page):
        try:
            values = {
                key: int(round(float(bounds[key])))
                for key in ('x1', 'y1', 'x2', 'y2')
            }
        except (KeyError, TypeError, ValueError):
            raise ValidationError(_('Region bounds must contain numeric x1, y1, x2 and y2 values.'))
        if not (0 <= values['x1'] < values['x2'] <= page.width and
                0 <= values['y1'] < values['y2'] <= page.height):
            raise ValidationError(_('Region bounds must fit inside the rendered page.'))
        return values

    @staticmethod
    def _region_page_string(regions):
        pages = set()
        for region in regions:
            try:
                if region.get('page_number') not in (None, False, ''):
                    pages.add(int(region['page_number']))
            except (AttributeError, TypeError, ValueError):
                continue
        return ','.join(str(page) for page in sorted(pages))

    def delete_region_editor_page(self, page_id):
        self.ensure_one()
        try:
            page_id = int(page_id)
        except (TypeError, ValueError):
            raise ValidationError(_('The selected rendered page is unavailable.'))
        page = self.import_id.page_ids.filtered(lambda item: item.id == page_id)[:1]
        if not page:
            raise ValidationError(_('The selected rendered page is unavailable.'))
        page.unlink()
        return True

    def action_ocr_section(self):
        self.ensure_one()
        if not self.resource_id:
            raise UserError(_('Build a resource for this section before running OCR.'))
        run = self.import_id._create_ocr_run(self, force=True)
        return self.import_id._build_ocr_run_notification(run)
