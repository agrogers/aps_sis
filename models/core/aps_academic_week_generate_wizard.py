from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ApsAcademicWeekGenerateWizard(models.TransientModel):
    _name = 'aps.academic.week.generate.wizard'
    _description = 'Generate Academic Weeks'

    academic_term_id = fields.Many2one(
        'aps.academic.term',
        string='Academic Term',
        help='Weeks will be assigned to this term. Leave blank to auto-detect from dates.',
    )
    date_start = fields.Date(
        string='First Week Start Date',
        required=True,
    )
    num_weeks = fields.Integer(
        string='Number of Weeks',
        required=True,
        default=10,
    )
    week_number_start = fields.Integer(
        string='Starting Week Number',
        required=True,
        default=1,
        help='The week number assigned to the first generated week.',
    )
    cycle_codes = fields.Char(
        string='Cycle Codes',
        help='Comma-separated cycle codes, e.g. "A,B" or "1,2". '
             'Cycles through from the first code. Leave blank to skip.',
    )

    @api.onchange('academic_term_id')
    def _onchange_academic_term_id(self):
        if self.academic_term_id and not self.date_start:
            self.date_start = self.academic_term_id.start_date

    @api.constrains('num_weeks')
    def _check_num_weeks(self):
        for rec in self:
            if rec.num_weeks < 1:
                raise ValidationError('Number of weeks must be at least 1.')

    def action_generate(self):
        self.ensure_one()
        codes = [c.strip() for c in (self.cycle_codes or '').split(',') if c.strip()]
        AcademicWeek = self.env['aps.academic.week']

        for i in range(self.num_weeks):
            week_start = self.date_start + timedelta(weeks=i)
            week_stop = week_start + timedelta(days=6)
            week_num = self.week_number_start + i
            cycle = codes[i % len(codes)] if codes else ''

            # Determine term: explicit override > auto-detect from dates
            term = self.academic_term_id
            if not term:
                term = self.env['aps.academic.term'].search([
                    ('start_date', '<=', week_start),
                    ('end_date', '>=', week_stop),
                ], limit=1)

            AcademicWeek.create({
                'name': f'Week {week_num}',
                'short_name': f'W{week_num}',
                'week_number': week_num,
                'week_cycle': cycle,
                'sequence': week_num * 10,
                'date_start': week_start,
                'date_stop': week_stop,
                'academic_term_id': term.id if term else False,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Academic Weeks',
            'res_model': 'aps.academic.week',
            'view_mode': 'list,form',
            'target': 'current',
        }
