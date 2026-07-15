import logging
import base64
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSCertificateTemplate(models.Model):
    _name = 'aps.certificate.template'
    _description = 'APS Certificate Template'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    page_format = fields.Selection(
        [('a4', 'A4'), ('a5', 'A5')],
        required=True,
        default='a4',
    )
    page_orientation = fields.Selection(
        [('portrait', 'Portrait'), ('landscape', 'Landscape')],
        required=True,
        default='portrait',
    )
    frame_image = fields.Binary(string='Certificate Background Frame', attachment=True)
    mail_template_id = fields.Many2one(
        'mail.template',
        required=True,
        ondelete='restrict',
        domain="[('model_id.model', '=', 'aps.certificate')]",
    )
    certificate_ids = fields.One2many(
        'aps.certificate',
        'certificate_template_id',
        string='Certificates',
    )

class APSCertificate(models.Model):
    _name = 'aps.certificate'
    _description = 'APS Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'certificate_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    partner_id = fields.Many2one('res.partner', required=True, tracking=True, index=True)
    subject_id = fields.Many2one('aps.subject', tracking=True)
    event = fields.Char(required=True, tracking=True)
    certificate_date = fields.Date(default=fields.Date.today, required=True, tracking=True)
    award_category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        ondelete='restrict',
        tracking=True,
    )
    award_sub_category_id = fields.Many2one(
        'aps.award.sub.category',
        string='Award Sub-Category',
        ondelete='restrict',
        tracking=True,
        domain="[('category_id', '=', award_category_id)]",
    )
    academic_week_id = fields.Many2one(
        'aps.academic.week',
        string='Academic Week',
        ondelete='restrict',
        tracking=True,
    )
    date_awarded = fields.Date(
        string='Date Awarded',
        tracking=True,
    )
    related_partner_ids = fields.Many2many(
        'res.partner',
        'aps_certificate_related_partner_rel',
        'certificate_id',
        'partner_id',
        string='Related People',
    )
    certificate_template_id = fields.Many2one(
        'aps.certificate.template',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    last_printed = fields.Datetime(string='Last Printed', readonly=True, copy=False, tracking=True)

    @api.depends('partner_id', 'event')
    def _compute_name(self):
        for record in self:
            if record.partner_id and record.event:
                record.name = f'{record.partner_id.name} - {record.event}'
            else:
                record.name = record.partner_id.name or record.event or 'Certificate'

    # Paper dimensions in mm (width x height) for each format+orientation combo.
    # Used by the PDF report template to size the background image absolutely so
    # wkhtmltopdf renders it reliably (percentage-based sizing is unreliable).
    _PAGE_DIMENSIONS_MM = {
        ('a4', 'portrait'):   ('210mm', '297mm'),
        ('a4', 'landscape'):  ('297mm', '210mm'),
        ('a5', 'portrait'):   ('148mm', '210mm'),
        ('a5', 'landscape'):  ('210mm', '148mm'),
    }

    def _get_page_dimensions_style(self):
        self.ensure_one()
        tmpl = self.certificate_template_id
        w, h = self._PAGE_DIMENSIONS_MM.get(
            (tmpl.page_format, tmpl.page_orientation or 'portrait'),
            ('210mm', '297mm'),
        )
        return f'width: {w}; height: {h};'

    def _get_certificate_frame_data_uri(self):
        self.ensure_one()
        frame_image = self.certificate_template_id.frame_image
        if not frame_image:
            return ''
        # Odoo Binary fields return base64 (bytes or str); normalise to str
        b64_str = frame_image.decode('ascii') if isinstance(frame_image, bytes) else frame_image
        raw = base64.b64decode(b64_str)
        # Handle double-encoded case: decoded result is itself base64 of image data
        try:
            raw2 = base64.b64decode(raw)
            if raw2[:8] == b'\x89PNG\r\n\x1a\n' or raw2[:2] == b'\xff\xd8':
                b64_str = raw.decode('ascii')
                raw = raw2
        except Exception:
            pass
        if raw[:8] == b'\x89PNG\r\n\x1a\n':
            mime = 'image/png'
        elif raw[:2] == b'\xff\xd8':
            mime = 'image/jpeg'
        else:
            mime = 'image/svg+xml'
        return f'data:{mime};base64,{b64_str}'

    def _render_certificate_body_html(self):
        self.ensure_one()
        template = self.certificate_template_id.mail_template_id
        if not template:
            return Markup('')
        try:
            mail_values = template._generate_template([self.id], ['body_html'])
        except Exception as err:
            _logger.exception(
                'Failed to render certificate template %s for certificate %s',
                template.id,
                self.id,
            )
            raise UserError('Failed to render certificate template.') from err
        body_html = ((mail_values or {}).get(self.id) or {}).get('body_html') or ''
        if not body_html:
            _logger.warning(
                'Certificate template %s rendered an empty body for certificate %s',
                template.id,
                self.id,
            )
        return Markup(body_html)

    def action_print_certificate(self):
        self.ensure_one()
        certificate_template = self.certificate_template_id
        self.last_printed = fields.Datetime.now()
        report_xmlid_by_layout = {
            ('a4', 'portrait'): 'aps_sis.action_report_certificate_a4',
            ('a4', 'landscape'): 'aps_sis.action_report_certificate_a4_landscape',
            ('a5', 'portrait'): 'aps_sis.action_report_certificate_a5',
            ('a5', 'landscape'): 'aps_sis.action_report_certificate_a5_landscape',
        }
        page_orientation = certificate_template.page_orientation or 'portrait'
        report_xmlid = report_xmlid_by_layout.get((certificate_template.page_format, page_orientation))
        if not report_xmlid:
            raise UserError('Certificate template page format/orientation is not configured.')
        return self.env.ref(report_xmlid).report_action(self)