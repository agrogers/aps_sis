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
    class_ids = fields.One2many(
        'aps.class',
        'subject_id',
        string='Classes',
    )
    icon = fields.Image(
        string='Icon',
        max_width=128,
        max_height=128,
        help='Subject icon. Defaults to the category icon if not set.',
    )
    active = fields.Boolean(default=True, string='Active')
    current_academic_year_id = fields.Many2one(
        'aps.academic.year',
        string='Current Academic Year',
        compute='_compute_current_academic_year_id',
    )
    class_current_year_ids = fields.One2many(
        'aps.class',
        'subject_id',
        string='Current Year Classes',
        compute='_compute_class_year_ids',
    )
    class_other_year_ids = fields.One2many(
        'aps.class',
        'subject_id',
        string='Other Year Classes',
        compute='_compute_class_year_ids',
    )
    class_count = fields.Integer(string='Classes', compute='_compute_class_count')
    show_add_classes = fields.Boolean(string='Add Classes', default=False)
    classes_to_create = fields.Integer(string='Number of Classes', default=1)

    def _compute_current_academic_year_id(self):
        current_year = self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        )
        for subject in self:
            subject.current_academic_year_id = current_year

    def _compute_class_year_ids(self):
        current_year = self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        )
        for subject in self:
            classes = self.env['aps.class'].search([
                ('subject_id', '=', subject.id),
            ])
            subject.class_current_year_ids = classes.filtered(
                lambda cls: cls.academic_year_id == current_year
            )
            subject.class_other_year_ids = classes.filtered(
                lambda cls: cls.academic_year_id != current_year
            )

    def _compute_class_count(self):
        for subject in self:
            subject.class_count = len(subject.class_ids)

    subject_coordinator_ids = fields.Many2many(
        'res.partner',
        relation='aps_subject_teacher_rel',
        column1='subject_id',
        column2='partner_id',
        string='Coordinators',
    )
    gcse_certificate = fields.Float(string='GCSE Certificate', default=0.0, help='The number of GCSE certificates awarded for this subject')

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

    def action_view_classes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Classes',
            'res_model': 'aps.class',
            'view_mode': 'list,form',
            'domain': [('subject_id', '=', self.id)],
            'context': {'default_subject_id': self.id},
        }

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

    @staticmethod
    def _generate_color_from_name(name):
        """Generate a deterministic HSL-based hex color from a string name."""
        import colorsys
        hash_val = sum(ord(c) for c in str(name))
        hue = hash_val % 360
        saturation = 70 + (hash_val % 20)
        lightness = 45 + ((hash_val // 360) % 15)
        rgb = colorsys.hls_to_rgb(hue / 360.0, lightness / 100.0, saturation / 100.0)
        r = int(rgb[0] * 255)
        g = int(rgb[1] * 255)
        b = int(rgb[2] * 255)
        return f'#{r:02x}{g:02x}{b:02x}'

    @api.model
    def get_subject_colors_map(self, subject_ids=None):
        """Return a dict mapping subject_id -> hex color string."""
        domain = [('id', 'in', subject_ids)] if subject_ids else []
        subjects = self.search(domain)
        color_map = {}
        for subject in subjects:
            if subject.category_id and subject.category_id.color_rgb:
                color_map[subject.id] = subject.category_id.color_rgb
            else:
                color_map[subject.id] = self._generate_color_from_name(subject.name)
        return color_map
