from odoo import fields, models, api


class APSSubjectCategory(models.Model):
    _name = 'aps.subject.category'
    _description = 'Subject Category'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', help='Short code for the category')
    description = fields.Text(string='Description')
    color_rgb = fields.Char(string='Color')
    icon = fields.Image(string='Icon', max_width=128, max_height=128)
    active = fields.Boolean(default=True, string='Active')
    tag_ids = fields.Many2many(
        'aps.subject.category.tag',
        relation='aps_subject_category_tag_rel',
        column1='category_id',
        column2='tag_id',
        string='Tags',
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Category name must be unique!'),
    ]

    def write(self, vals):
        result = super().write(vals)
        if 'tag_ids' in vals:
            self._recompute_students_home_class()
        return result

    def _recompute_students_home_class(self):
        """Recompute home_class_id for all students enrolled in classes under these categories."""
        subjects = self.env['aps.subject'].search([('category_id', 'in', self.ids)])
        if not subjects:
            return
        classes = self.env['aps.class'].search([('subject_id', 'in', subjects.ids)])
        if not classes:
            return
        enrollments = self.env['aps.student.class'].search([
            ('home_class_id', 'in', classes.ids),
            ('state', '=', 'enrolled'),
        ])
        enrollments.mapped('student_id')._recompute_home_class()
