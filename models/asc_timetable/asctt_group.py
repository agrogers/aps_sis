from odoo import fields, models


class ASCTTGroup(models.Model):
    _name = 'asctt.group'
    _description = 'aSc Timetable Group'
    _order = 'class_id, name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    class_id = fields.Many2one(
        'asctt.class',
        string='Class',
        ondelete='cascade',
        required=True,
    )
    entire_class = fields.Boolean(string='Entire Class', default=False)
    division_tag = fields.Integer(string='Division Tag')
    student_count = fields.Integer(string='Student Count')
