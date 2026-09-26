from odoo import fields, models


class APSStudentEntrySource(models.Model):
    _name = 'aps.student.entry.source'
    _description = 'Student Entry Source'
    _order = 'name'

    name = fields.Char(string='Name', required=True)