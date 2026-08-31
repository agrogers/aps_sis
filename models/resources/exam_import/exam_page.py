"""Rendered exam paper page model."""
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


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
