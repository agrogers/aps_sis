from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
    class_current_year_ids = fields.One2many(
        'aps.class',
        'subject_id',
        string='Current Year Classes',
        domain="[('academic_year_id.is_current', '=', True)]",
    )
    class_other_year_ids = fields.One2many(
        'aps.class',
        'subject_id',
        string='Other Year Classes',
        domain="[('academic_year_id.is_current', '!=', True)]",
    )
    show_add_classes = fields.Boolean(string='Add Classes', default=False)
    classes_to_create = fields.Integer(string='Number of Classes', default=1)

    def action_create_current_year_classes(self):
        current_year = self.env['aps.academic.year'].search([('is_current', '=', True)], limit=1)
        if not current_year:
            raise UserError(_(
                "No current academic year is set. "
                "Please mark an academic year as current before adding classes."
            ))
        count = max(1, self.classes_to_create or 1)
        if count == 1:
            vals_list = [{'subject_id': self.id, 'academic_year_id': current_year.id}]
        else:
            vals_list = [
                {'subject_id': self.id, 'academic_year_id': current_year.id, 'identifier': str(i)}
                for i in range(1, count + 1)
            ]
        new_classes = self.env['aps.class'].create(vals_list)
        new_classes._compute_code_name()
        self.write({'show_add_classes': False, 'classes_to_create': 1})

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id and self.category_id.icon and not self.icon:
            self.icon = self.category_id.icon

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Subject name must be unique!'),
    ]

    def copy_data(self, default=None):
        default = dict(default or {})
        default.setdefault('name', f"{self.name} (copy)")
        return super().copy_data(default)
