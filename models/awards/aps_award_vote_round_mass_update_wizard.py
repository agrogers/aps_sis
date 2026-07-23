from odoo import models, fields, api, _
from odoo.exceptions import UserError


class APSAwardVoteRoundMassUpdateWizard(models.TransientModel):
    _name = 'aps.award.vote.round.mass.update.wizard'
    _description = 'Mass Update Vote Rounds Wizard'

    vote_round_ids = fields.Many2many(
        'aps.award.vote.round',
        'aps_vote_round_mass_update_rel',
        'wizard_id',
        'vote_round_id',
        string='Vote Rounds',
        required=True,
        default=lambda self: self._default_vote_round_ids(),
    )

    # Update options
    update_name = fields.Boolean(string='Name')
    name_value = fields.Char(string='Value')

    update_description = fields.Boolean(string='Description')
    description_value = fields.Text(string='Value')

    update_short_description = fields.Boolean(string='Short Description')
    short_description_value = fields.Text(string='Value')

    update_color = fields.Boolean(string='Color')
    color_value = fields.Char(string='Value', default='#5c1ea8')

    update_datetime_start = fields.Boolean(string='Start Date')
    datetime_start_value = fields.Datetime(string='Value')

    update_datetime_end = fields.Boolean(string='End Date')
    datetime_end_value = fields.Datetime(string='Value')

    update_status = fields.Boolean(string='Status')
    status_value = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('finalised', 'Finalised'),
    ], string='Value')

    update_recurring_days = fields.Boolean(string='Recurring Days')
    recurring_days_value = fields.Integer(string='Value', default=0)

    update_award_category_id = fields.Boolean(string='Award Category')
    award_category_id_value = fields.Many2one(
        'aps.award.category',
        string='Value',
    )

    update_award_sub_category_id = fields.Boolean(string='Award Sub-Category')
    award_sub_category_id_value = fields.Many2one(
        'aps.award.sub.category',
        string='Value',
        domain="[('category_id', '=', award_category_id_value)]",
    )

    update_academic_week_id = fields.Boolean(string='Academic Week')
    academic_week_id_value = fields.Many2one(
        'aps.academic.week',
        string='Value',
    )

    update_tag_ids = fields.Boolean(string='Tags')
    tag_ids_value = fields.Many2many(
        'aps.award.tag',
        'aps_vote_round_mass_update_tag_rel',
        'wizard_id',
        'tag_id',
        string='Value',
    )

    update_voting_set_ids = fields.Boolean(string='Voting Sets')
    voting_set_ids_value = fields.Many2many(
        'aps.award.voting.set',
        'aps_vote_round_mass_update_votingset_rel',
        'wizard_id',
        'voting_set_id',
        string='Value',
    )

    update_round_manager_ids = fields.Boolean(string='Round Managers')
    round_manager_ids_value = fields.Many2many(
        'res.partner',
        'aps_vote_round_mass_update_manager_rel',
        'wizard_id',
        'partner_id',
        string='Value',
    )

    @api.model
    def _default_vote_round_ids(self):
        return self.env.context.get('active_ids', [])

    def action_update(self):
        self.ensure_one()

        if not self.vote_round_ids:
            raise UserError(_("No vote rounds selected."))

        updates = {}

        if self.update_name:
            updates['name'] = self.name_value
        if self.update_description:
            updates['description'] = self.description_value
        if self.update_short_description:
            updates['short_description'] = self.short_description_value
        if self.update_color:
            updates['color'] = self.color_value
        if self.update_datetime_start:
            updates['datetime_start'] = self.datetime_start_value
        if self.update_datetime_end:
            updates['datetime_end'] = self.datetime_end_value
        if self.update_status:
            updates['status'] = self.status_value
        if self.update_recurring_days:
            updates['recurring_days'] = self.recurring_days_value
        if self.update_award_category_id:
            updates['award_category_id'] = self.award_category_id_value.id
        if self.update_award_sub_category_id:
            updates['award_sub_category_id'] = self.award_sub_category_id_value.id
        if self.update_academic_week_id:
            updates['academic_week_id'] = self.academic_week_id_value.id
        if self.update_tag_ids:
            updates['tag_ids'] = [(6, 0, self.tag_ids_value.ids)]
        if self.update_voting_set_ids:
            updates['voting_set_ids'] = [(6, 0, self.voting_set_ids_value.ids)]
        if self.update_round_manager_ids:
            updates['round_manager_ids'] = [(6, 0, self.round_manager_ids_value.ids)]

        if not updates:
            raise UserError(_("No updates selected. Please enable at least one update option."))

        self.vote_round_ids.write(updates)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Successfully updated %d vote round(s).') % len(self.vote_round_ids),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }