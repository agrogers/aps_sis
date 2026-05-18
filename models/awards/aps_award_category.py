from odoo import fields, models


class APSAwardCategory(models.Model):
    _name = 'aps.award.category'
    _description = 'Award Category'
    _order = 'name'

    name = fields.Char(required=True)
    description = fields.Text(string='Description')
    short_description = fields.Text(string='Short Description')
    image = fields.Image(string='Image')
    level_ids = fields.Many2many(
        'aps.level',
        string='Levels',
    )
    term_ids = fields.Many2many(
        'aps.academic.term',
        string='Terms',
    )
    subject_category_ids = fields.Many2many(
        'aps.subject.category',
        string='Subject Categories',
    )
    certificate_template_id = fields.Many2one(
        'aps.certificate.template',
        string='Default Certificate Template',
        ondelete='set null',
    )
    voting_restrictions = fields.Selection(
        selection=[
            ('none', 'None'),
            ('number', 'Number'),
            ('year_level', 'Year Level'),
        ],
        string='Voting Restrictions',
        default='none',
        required=True,
    )
    voting_active = fields.Boolean(string='Voting Active', default=False)
    adhoc_vote = fields.Boolean(string='Allow Ad Hoc Voting', default=False)
    open_date = fields.Date(string='Open Date', help='Used to track award history. Votes cast since this date are counted in the voting form.')
    sub_category_ids = fields.One2many(
        'aps.award.sub.category',
        'category_id',
        string='Sub-Categories',
    )

