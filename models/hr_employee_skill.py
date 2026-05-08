from odoo import fields, models


class HrEmployeeSkill(models.Model):
    _inherit = 'hr.employee.skill'

    assessed_skill_level_id = fields.Many2one(
        'hr.skill.level',
        string='Assessed Level',
        domain="[('skill_type_id', '=', skill_type_id)]",
        ondelete='restrict',
        help='Official skill level determined by external assessment, separate from the self-reported proficiency level.',
    )
