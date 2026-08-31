"""Core model for IGCSE exam paper imports: fields, shared helpers, and lifecycle.

Workflow logic lives in sibling modules that extend this model:
- exam_render.py  : PDF page rendering
- exam_analyse.py : AI vision analysis of rendered pages
- exam_detect.py  : section detection from page analyses
- exam_build.py   : resource building and section image cropping
- exam_ocr.py     : OCR of section images
- exam_section.py / exam_page.py / exam_run.py / exam_resource.py : related models
"""
import logging
import re

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
        'aps.resources', string='Exam Resource', required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    question_attachment_id = fields.Many2one(
        'ir.attachment', string='Question PDF', required=True,
        ondelete='restrict', readonly=True,
    )
    mark_scheme_attachment_id = fields.Many2one(
        'ir.attachment', string='Mark Scheme PDF', required=True,
        ondelete='restrict', readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('uploaded', 'Rendered'),
        ('analysing', 'Analysed'),
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
    analysis_scope = fields.Selection([
        ('all', 'All Pages'),
        ('pending', 'Not Yet Analysed (Pending or Failed)'),
    ], default='all', required=True, string='Analyse Pages Scope',
        help='Controls which rendered pages the "Analyse Pages" button processes.')
    render_dpi = fields.Integer(default=150, required=True)
    page_ids = fields.One2many('aps.exam.paper.page', 'import_id', string='Rendered Pages')
    page_count = fields.Integer(compute='_compute_counts')
    section_ids = fields.One2many('aps.exam.paper.section', 'import_id', string='Detected Sections')
    section_count = fields.Integer(compute='_compute_counts')
    child_resource_count = fields.Integer(compute='_compute_child_resource_count')
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

    @api.depends('section_ids', 'page_ids')
    def _compute_counts(self):
        for record in self:
            record.section_count = len(record.section_ids)
            record.page_count = len(record.page_ids)

    @api.depends('resource_id', 'resource_id.child_ids')
    def _compute_child_resource_count(self):
        for record in self:
            record.child_resource_count = len(record._get_descendant_resources())

    def _get_descendant_resources(self):
        """Return all descendants (children, grandchildren, etc.) of the exam paper resource."""
        self.ensure_one()
        descendants = self.env['aps.resources']
        frontier = self.resource_id.child_ids
        while frontier:
            descendants |= frontier
            frontier = frontier.child_ids - descendants
        return descendants

    def action_open_child_resources(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Child Resources'),
            'res_model': 'aps.resources',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self._get_descendant_resources().ids)],
        }

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
        mark_scheme = attachments.filtered(
            lambda a: any(marker in (a.name or '').casefold() for marker in ('rms', 'msc'))
        )
        if len(question) != 1 or len(mark_scheme) != 1:
            raise UserError(_(
                'Exactly one question-paper attachment containing "que" and one '
                'mark-scheme attachment containing "rms" or "msc" are required. '
                'Found %s and %s.'
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
        previous = self.search([], order='create_date desc, id desc', limit=1)
        return self.create({
            'name': resource.name or _('IGCSE Exam Paper'),
            'resource_id': resource.id,
            'question_attachment_id': question.id,
            'mark_scheme_attachment_id': mark_scheme.id,
            'state': 'uploaded',
            'ai_model_id': previous.ai_model_id.id or False,
            'single_page_ai_model_id': previous.single_page_ai_model_id.id or False,
            'ocr_ai_model_id': previous.ocr_ai_model_id.id or False,
            'analysis_scope': previous.analysis_scope or 'all',
        })

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

    def action_retry(self):
        self.ensure_one()
        if self.state != 'failed':
            raise UserError(_('Only failed imports can be retried.'))

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
