from odoo import api, fields, models


class APSTeam(models.Model):
    _name = 'aps.team'
    _description = 'Team'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color')
    icon = fields.Image(string='Icon', max_width=128, max_height=128)
    captain_student_ids = fields.Many2many(
        'res.partner',
        relation='aps_team_captain_student_rel',
        column1='team_id',
        column2='partner_id',
        string='Student Captains',
        domain="[('aps_student_ids', '!=', False)]",
    )
    captain_staff_ids = fields.Many2many(
        'res.partner',
        relation='aps_team_captain_staff_rel',
        column1='team_id',
        column2='partner_id',
        string='Staff Captains',
        domain="[('aps_teacher_ids', '!=', False)]",
    )
    active = fields.Boolean(string='Active', default=True)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.name or ''