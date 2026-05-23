from odoo import fields, models


class ASCTTTeacher(models.Model):
    _name = 'asctt.teacher'
    _description = 'aSc Timetable Teacher'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    firstname = fields.Char(string='First Name')
    lastname = fields.Char(string='Last Name')
    gender = fields.Selection(
        [('M', 'Male'), ('F', 'Female'), ('', 'Not Specified')],
        string='Gender',
        default='',
    )
    color = fields.Char(string='Colour', size=20, help='Hex colour code, e.g. #9999FF')
    email = fields.Char(string='Email')
    mobile = fields.Char(string='Mobile')

    # APEX link
    aps_teacher_id = fields.Many2one(
        'aps.teacher',
        string='APEX Teacher',
        ondelete='set null',
        help='Link to the corresponding APEX Teacher record.',
    )
