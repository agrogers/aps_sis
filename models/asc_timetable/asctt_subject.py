from odoo import fields, models


class ASCTTSubject(models.Model):
    _name = 'asctt.subject'
    _description = 'aSc Timetable Subject'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)

    # APEX link
    aps_subject_category_id = fields.Many2one(
        'aps.subject.category',
        string='APEX Subject Category',
        ondelete='set null',
        help='Link to the corresponding APEX Subject Category record.',
    )
