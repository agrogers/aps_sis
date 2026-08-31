"""aps.resources extensions for exam paper imports."""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class APSResourceExamPaperImport(models.Model):
    _inherit = 'aps.resources'

    exam_import_ids = fields.One2many('aps.exam.paper.import', 'resource_id', string='Exam Imports')
    is_pearson_past_paper = fields.Boolean(
        string='Pearson Past Paper',
        compute='_compute_is_pearson_past_paper',
        store=True,
    )
    exam_import_count = fields.Integer(compute='_compute_exam_import_count', store=True)
    detected_section_count = fields.Integer(compute='_compute_exam_import_count', store=True)
    rendered_page_count = fields.Integer(compute='_compute_exam_import_count', store=True)

    @api.depends('type_id', 'type_id.name')
    def _compute_is_pearson_past_paper(self):
        for resource in self:
            resource.is_pearson_past_paper = resource.type_id.name == 'Past Paper (Pearson)'

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
