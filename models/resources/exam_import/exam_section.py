"""Detected exam paper section model."""
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

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
            'type': 'ir.actions.act_window', 'name': _('Imported Section'),
            'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'current',
        }

    def action_ocr_section(self):
        self.ensure_one()
        if not self.resource_id:
            raise UserError(_('Build a resource for this section before running OCR.'))
        run = self.import_id._create_ocr_run(self, force=True)
        return self.import_id._build_ocr_run_notification(run)
