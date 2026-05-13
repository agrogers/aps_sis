from odoo import api, fields, models


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
    mail_template_id = fields.Many2one(
        'mail.template',
        required=True,
        ondelete='restrict',
        domain="[('model_id.model', '=', 'aps.student.certificate')]",
    )
    certificate_ids = fields.One2many(
        'aps.student.certificate',
        'certificate_template_id',
        string='Certificates',
    )


class APSStudentCertificate(models.Model):
    _name = 'aps.student.certificate'
    _description = 'APS Student Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(compute='_compute_name', store=True)
    partner_id = fields.Many2one('res.partner', required=True, tracking=True)
    subject_id = fields.Many2one('op.subject', tracking=True)
    event = fields.Char(required=True, tracking=True)
    certificate_date = fields.Date(default=fields.Date.today, required=True, tracking=True)
    certificate_template_id = fields.Many2one(
        'aps.certificate.template',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    date_printed = fields.Datetime(readonly=True, copy=False, tracking=True)
    print_history_ids = fields.One2many(
        'aps.student.certificate.print.history',
        'certificate_id',
        string='Print History',
        readonly=True,
    )
    print_count = fields.Integer(compute='_compute_print_count', string='Print Count')

    @api.depends('partner_id', 'event')
    def _compute_name(self):
        for record in self:
            if record.partner_id and record.event:
                record.name = f'{record.partner_id.name} - {record.event}'
            else:
                record.name = record.partner_id.name or record.event or 'Certificate'

    @api.depends('print_history_ids')
    def _compute_print_count(self):
        for record in self:
            record.print_count = len(record.print_history_ids)

    def _render_certificate_body_html(self):
        self.ensure_one()
        template = self.certificate_template_id.mail_template_id
        if not template:
            return ''
        rendered_html = template._render_field('body_html', [self.id], compute_lang=True)
        return rendered_html.get(self.id) or ''

    def action_print_certificate(self):
        self.ensure_one()
        self.date_printed = fields.Datetime.now()
        self.env['aps.student.certificate.print.history'].create({
            'certificate_id': self.id,
            'printed_by': self.env.user.id,
            'printed_on': self.date_printed,
            'mail_template_id': self.certificate_template_id.mail_template_id.id,
        })
        report_xmlid = (
            'aps_sis.action_report_student_certificate_a5'
            if self.certificate_template_id.page_format == 'a5'
            else 'aps_sis.action_report_student_certificate_a4'
        )
        return self.env.ref(report_xmlid).report_action(self)


class APSStudentCertificatePrintHistory(models.Model):
    _name = 'aps.student.certificate.print.history'
    _description = 'APS Student Certificate Print History'
    _order = 'printed_on desc, id desc'

    certificate_id = fields.Many2one(
        'aps.student.certificate',
        required=True,
        ondelete='cascade',
    )
    printed_by = fields.Many2one('res.users', required=True, ondelete='restrict')
    printed_on = fields.Datetime(required=True, default=fields.Datetime.now)
    mail_template_id = fields.Many2one(
        'mail.template',
        ondelete='set null',
        domain="[('model_id.model', '=', 'aps.student.certificate')]",
    )
