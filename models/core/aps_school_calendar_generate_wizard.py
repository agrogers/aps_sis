import datetime

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ApsSchoolCalendarGenerateWizard(models.TransientModel):
    _name = 'aps.school.calendar.generate.wizard'
    _description = 'Generate School Calendar'

    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    skip_existing = fields.Boolean(
        string='Skip Existing Dates',
        default=True,
        help='Skip dates that already have an entry for All Levels. '
             'Uncheck to raise an error on duplicates instead.',
    )

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError('Start date must be before end date.')

    def action_generate(self):
        self.ensure_one()
        Calendar = self.env['aps.school.calendar']

        # Build a set of existing (date, level_id) pairs for fast lookup
        existing = set(
            Calendar.search([
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
                ('applies_to_level_id', '=', False),
            ]).mapped('date')
        )

        # Fetch all repeating entries from the previous year that fall within
        # the equivalent date range one year earlier.
        prev_start = self.date_start - relativedelta(years=1)
        prev_end = self.date_end - relativedelta(years=1)
        prev_entries = Calendar.search([
            ('date', '>=', prev_start),
            ('date', '<=', prev_end),
            ('repeating', '=', True),
            ('applies_to_level_id', '=', False),
        ])
        # Key: (month, day) → entry
        repeating_map = {
            (e.date.month, e.date.day): e for e in prev_entries
        }

        to_create = []
        created = skipped = 0
        current = self.date_start

        while current <= self.date_end:
            if current in existing:
                skipped += 1
                current += datetime.timedelta(days=1)
                continue

            vals = {
                'date': current,
                'applies_to_level_id': False,
            }

            if current.weekday() >= 5:
                # Saturday (5) or Sunday (6)
                vals['date_type'] = 'weekend'
                vals['description'] = current.strftime('%A')
                vals['repeating'] = False
            else:
                # Check for a repeating entry from the previous year on the same calendar date
                prev = repeating_map.get((current.month, current.day))
                if prev:
                    vals['date_type'] = prev.date_type
                    vals['description'] = prev.description or ''
                    vals['notes'] = prev.notes or ''
                    vals['repeating'] = True  # carry the repeating flag forward
                else:
                    # Normal school day
                    vals['date_type'] = 'school_day'

            to_create.append(vals)
            created += 1
            current += datetime.timedelta(days=1)

        if to_create:
            Calendar.create(to_create)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Calendar Generated',
                'message': f'{created} entr{"y" if created == 1 else "ies"} created'
                           + (f', {skipped} skipped (already existed).' if skipped else '.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
