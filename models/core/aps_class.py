from odoo import fields, models, api


class APSClass(models.Model):
    _name = 'aps.class'
    _description = 'Class'
    _order = 'name'

    identifier = fields.Char(
        string='Identifier',
        size=10,
        required=False,
        help='Short code for this class section, e.g. A, B, 1, 2',
    )
    subject_id = fields.Many2one(
        'aps.subject',
        string='Subject',
        ondelete='restrict',
    )
    code = fields.Char(
        string='Code',
        compute='_compute_code_name',
        store=True,
        readonly=False,
        help='Defaults to subject code + identifier',
    )
    name = fields.Char(
        string='Name',
        compute='_compute_code_name',
        store=True,
        readonly=False,
        required=True,
        help='Defaults to subject name + identifier',
    )
    academic_year_id = fields.Many2one(
        'aps.academic.year',
        string='Academic Year',
        ondelete='set null',
        default=lambda self: self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        ),
    )
    teacher_ids = fields.Many2many(
        'res.partner',
        relation='aps_class_teacher_rel',
        column1='class_id',
        column2='partner_id',
        string='Teachers',
    )
    assistant_teacher_ids = fields.Many2many(
        'res.partner',
        relation='aps_class_assistant_teacher_rel',
        column1='class_id',
        column2='partner_id',
        string='Assistant Teachers',
    )
    active = fields.Boolean(default=True, string='Active')
    enrollment_ids = fields.One2many('aps.student.class', 'home_class_id', string='Enrolled Students')

    @api.depends('subject_id', 'subject_id.code', 'subject_id.name', 'identifier')
    def _compute_code_name(self):
        for rec in self:
            if rec.subject_id:
                rec.code = f"{rec.subject_id.code or ''}{rec.identifier if rec.identifier else ''}".strip()
                rec.name = f"{rec.subject_id.name} {rec.identifier if rec.identifier else ''}".strip()
            else:
                rec.code = False
                rec.name = False

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.code or rec.name or ''
