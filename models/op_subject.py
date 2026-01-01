from odoo import fields, models


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