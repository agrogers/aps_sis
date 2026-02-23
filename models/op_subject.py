from odoo import fields, models


class APSSubjectCategory(models.Model):
    _name = 'aps.subject.category'
    _description = 'Subject Category'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', help='Short code for the category')
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index')
    active = fields.Boolean(default=True, string='Active')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Category name must be unique!'),
    ]


class OpSubject(models.Model):
    _inherit = 'op.subject'

    # teachers_ids = fields.Many2many(
    #     'op.faculty',
    #     relation='op_subject_teachers_rel',
    #     string='Teachers',
    #     help='Faculty members teaching this subject'
    # )

    # assistant_teachers_ids = fields.Many2many(
    #     'op.faculty',
    #     relation='op_subject_assistant_teachers_rel',
    #     string='Assistant Teachers',
    #     help='Assistant faculty members for this subject'
    # )

    faculty_ids = fields.Many2many(
        'op.faculty',
        relation='op_faculty_op_subject_rel',
        column1='op_subject_id',
        column2='op_faculty_id',
        string='Faculty Members',
        help='Faculty members linked to this subject'
    )
    icon = fields.Image(
        string="Icon",
        max_width=64,
        max_height=64,
        help="Subject icon (e.g. for visual identification in lists)"
    )
    category_id = fields.Many2one(
        'aps.subject.category',
        string='Subject Category',
        help='Category this subject belongs to'
    )