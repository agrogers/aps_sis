from odoo import fields, models, api

_HOME_CLASS_TAG_NAMES = {'Home Class', 'Pastoral Care Subject'}


class APSSubjectCategoryTag(models.Model):
    _name = 'aps.subject.category.tag'
    _description = 'Subject Category Tag'
    _order = 'name'

    name = fields.Char(string='Name', required=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tag name must be unique!'),
    ]

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals:
            # A rename could make this tag match or stop matching the home-class names
            categories = self.env['aps.subject.category'].search(
                [('tag_ids', 'in', self.ids)]
            )
            if categories:
                categories._recompute_students_home_class()
        return result
