from odoo import fields, models


class APSStudentEnrolmentStatus(models.Model):
    _name = 'aps.student.enrolment.status'
    _description = 'Student Enrolment Status'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True, copy=False)
    sequence = fields.Integer(default=10)
    icon = fields.Image(
        string='Icon',
        max_width=32,
        max_height=32,
        help='Upload an icon image. Images are limited to 32 x 32 pixels.',
    )
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index', default=0)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Enrolment status codes must be unique.'),
    ]