from odoo import fields, models


class APSStudentLeavingReason(models.Model):
    _name = 'aps.student.leaving.reason'
    _description = 'Student Leaving Reason'
    _order = 'name'

    name = fields.Char(string='Name', required=True)