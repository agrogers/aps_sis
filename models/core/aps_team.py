from odoo import api, fields, models


class APSTeam(models.Model):
    _name = 'aps.team'
    _description = 'Team'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    color = fields.Char(string='Color', default='#6c757d')
    icon = fields.Image(string='Icon', max_width=128, max_height=128)
    tag_ids = fields.Many2many(
        'res.partner.category',
        relation='aps_team_partner_category_rel',
        column1='team_id',
        column2='category_id',
        string='Tags',
    )
    captain_student_ids = fields.Many2many(
        'res.partner',
        relation='aps_team_captain_student_rel',
        column1='team_id',
        column2='partner_id',
        string='Student Captains',
        domain="[('is_student', '=', True)]",
    )
    captain_staff_ids = fields.Many2many(
        'res.partner',
        relation='aps_team_captain_staff_rel',
        column1='team_id',
        column2='partner_id',
        string='Staff Captains',
        domain="[('is_teacher', '=', True)]",
    )
    active = fields.Boolean(string='Active', default=True)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.name or ''