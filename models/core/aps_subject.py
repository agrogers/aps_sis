from odoo import fields, models, api


class APSSubject(models.Model):
    _name = 'aps.subject'
    _description = 'Subject'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', help='Short code for the subject')
    category_id = fields.Many2one(
        'aps.subject.category',
        string='Category',
        ondelete='set null',
    )
    level_id = fields.Many2one(
        'aps.level',
        string='Level',
        ondelete='set null',
        help='Academic level this subject belongs to (e.g. Year 1, Year 2)',
    )
    icon = fields.Image(
        string='Icon',
        max_width=128,
        max_height=128,
        help='Subject icon. Defaults to the category icon if not set.',
    )
    active = fields.Boolean(default=True, string='Active')

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id and self.category_id.icon and not self.icon:
            self.icon = self.category_id.icon

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Subject name must be unique!'),
    ]
