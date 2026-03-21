import base64
import logging
import os

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ApsAvatarCategory(models.Model):
    _name = 'aps.avatar.category'
    _description = 'Avatar Category'
    _order = 'name'

    name = fields.Char(string='Category', required=True)
    avatar_count = fields.Integer(string='Avatars', compute='_compute_avatar_count')

    def _compute_avatar_count(self):
        counts = self.env['aps.avatar'].read_group(
            [('category_id', 'in', self.ids)],
            ['category_id'],
            ['category_id'],
        )
        count_map = {r['category_id'][0]: r['category_id_count'] for r in counts}
        for rec in self:
            rec.avatar_count = count_map.get(rec.id, 0)


class ApsAvatar(models.Model):
    _name = 'aps.avatar'
    _description = 'Avatar'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    image = fields.Image(string='Avatar Image', max_width=512, max_height=512)
    category_id = fields.Many2one('aps.avatar.category', string='Category', ondelete='restrict')

    # Track which students are using this avatar.
    # Modelled as a list to accommodate potential future multi-user scenarios,
    # but currently constrained to a single student per avatar.
    student_ids = fields.One2many(
        'op.student',
        'avatar_id',
        string='Used By',
        readonly=True,
    )
    student_count = fields.Integer(string='Used By (Count)', compute='_compute_student_count')

    @api.depends('student_ids')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)

    @api.constrains('student_ids')
    def _check_single_student(self):
        for rec in self:
            if len(rec.student_ids) > 1:
                raise ValidationError(
                    "An avatar can only be assigned to one student at a time."
                )

    @api.model
    def bulk_create_from_files(self, files, category_id):
        """Create avatar records from a list of {name, data} dicts.

        :param files: list of dicts with 'name' (filename str) and 'data' (base64 str)
        :param category_id: int or False
        :return: dict with created avatar ids
        """
        vals_list = []
        for f in files:
            fname = f.get('name', '')
            name = os.path.splitext(fname)[0] if fname else 'Avatar'
            vals_list.append({
                'name': name,
                'image': f.get('data', ''),
                'category_id': category_id or False,
            })
        created = self.create(vals_list)
        return {'ids': created.ids, 'count': len(created)}
