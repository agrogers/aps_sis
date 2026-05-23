from odoo import fields, models


class ASCTTTermsDef(models.Model):
    _name = 'asctt.terms.def'
    _description = 'aSc Timetable Terms Definition'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    terms = fields.Char(string='Terms Pattern', help='Binary term pattern, e.g. "1" for whole year')

    # APEX link
    aps_term_id = fields.Many2one(
        'aps.academic.term',
        string='APEX Academic Term',
        ondelete='set null',
        help='Link to the corresponding APEX Academic Term record.',
    )
