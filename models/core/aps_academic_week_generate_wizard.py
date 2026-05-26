from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_PARAM_TERM = 'aps_sis.week_wizard_academic_term_id'
_PARAM_DATE_START = 'aps_sis.week_wizard_date_start'
_PARAM_NUM_WEEKS = 'aps_sis.week_wizard_num_weeks'
_PARAM_WEEK_START = 'aps_sis.week_wizard_week_number_start'
_PARAM_CYCLE_CODES = 'aps_sis.week_wizard_cycle_codes'


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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        get = self.env['ir.config_parameter'].sudo().get_param

        term_id_str = get(_PARAM_TERM)
        if term_id_str:
            try:
                term_id = int(term_id_str)
                if self.env['aps.academic.term'].browse(term_id).exists():
                    res['academic_term_id'] = term_id
            except (ValueError, TypeError):
                pass

        date_str = get(_PARAM_DATE_START)
        if date_str:
            res['date_start'] = date_str

        num_weeks_str = get(_PARAM_NUM_WEEKS)
        if num_weeks_str:
            try:
                res['num_weeks'] = int(num_weeks_str)
            except (ValueError, TypeError):
                pass

        week_start_str = get(_PARAM_WEEK_START)
        if week_start_str:
            try:
                res['week_number_start'] = int(week_start_str)
            except (ValueError, TypeError):
                pass

        cycle_codes = get(_PARAM_CYCLE_CODES)
        if cycle_codes is not None:
            res['cycle_codes'] = cycle_codes

        return res

    @api.onchange('academic_term_id')
    def _onchange_academic_term_id(self):
        if self.academic_term_id and not self.date_start:
            self.date_start = self.academic_term_id.start_date

    @api.constrains('num_weeks')
    def _check_num_weeks(self):
        for rec in self:
            if rec.num_weeks < 1:
                raise ValidationError('Number of weeks must be at least 1.')

    def _save_last_used(self):
        """Persist the current wizard values so they become defaults next time."""
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param(_PARAM_TERM, str(self.academic_term_id.id) if self.academic_term_id else '')
        set_param(_PARAM_DATE_START, str(self.date_start) if self.date_start else '')
        set_param(_PARAM_NUM_WEEKS, str(self.num_weeks))
        set_param(_PARAM_WEEK_START, str(self.week_number_start))
        set_param(_PARAM_CYCLE_CODES, self.cycle_codes or '')

    def action_generate(self):
        self.ensure_one()
        self._save_last_used()
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

            vals = {
                'name': f'Week {week_num}',
                'short_name': f'W{week_num}',
                'week_number': week_num,
                'week_cycle': cycle,
                'sequence': week_num * 10,
                'date_start': week_start,
                'date_stop': week_stop,
                'academic_term_id': term.id if term else False,
            }

            # Update existing week for this start date rather than creating a duplicate
            existing = AcademicWeek.search([('date_start', '=', week_start)], limit=1)
            if existing:
                existing.write(vals)
            else:
                AcademicWeek.create(vals)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Academic Weeks',
            'res_model': 'aps.academic.week',
            'view_mode': 'list,form',
            'target': 'current',
        }
