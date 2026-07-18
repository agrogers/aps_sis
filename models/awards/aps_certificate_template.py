import logging

from odoo import fields, models

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