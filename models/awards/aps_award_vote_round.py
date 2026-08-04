from datetime import timedelta
from odoo import api, fields, models


class APSAwardVoteRound(models.Model):
    _name = 'aps.award.vote.round'
    _description = 'Award Vote Round'
    _order = 'datetime_start desc, id desc'
    _inherit = [
        'aps.award.vote.round.mixin.voters',
        'aps.award.vote.round.mixin.candidates',
        'aps.award.vote.round.mixin.rules',
    ]

    # ── Core fields ──────────────────────────────────────────────────────────

    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    short_description = fields.Text(string='Short Description')
    image = fields.Image(string='Image')
    color = fields.Char(string='Color', default='#5c1ea8')

    datetime_start = fields.Datetime(string='Start', required=True)
    datetime_end = fields.Datetime(string='End', required=True)
    status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('open', 'Open'),
            ('closed', 'Closed'),
            ('finalised', 'Finalised'),
        ],
        string='Status',
        default='draft',
        required=True,
    )

    recurring_days = fields.Integer(
        string='Recur Every (days)',
        default=0,
        help='If set to a positive number, a new round will automatically be scheduled this many days after the current round ends. Set to 0 to disable auto-rescheduling.',
    )

    award_category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        ondelete='restrict',
    )
    award_sub_category_id = fields.Many2one(
        'aps.award.sub.category',
        string='Award Sub-Category',
        ondelete='restrict',
        domain="[('category_id', '=', award_category_id)]",
    )
    academic_week_id = fields.Many2one(
        'aps.academic.week',
        string='Academic Week',
        ondelete='restrict',
    )
    tag_ids = fields.Many2many(
        'aps.award.tag',
        relation='aps_award_vote_round_tag_rel',
        column1='round_id',
        column2='tag_id',
        string='Tags',
    )
    voting_set_ids = fields.Many2many(
        'aps.award.voting.set',
        'aps_vote_round_voting_set_rel',
        'round_id',
        'voting_set_id',
        string='Voting Sets',
    )

    # Computed vote statistics
    votes_cast = fields.Integer(
        string='Votes Cast',
        compute='_compute_vote_stats',
        store=True,
    )
    active_voter_count = fields.Integer(
        string='Active Voter Count',
        compute='_compute_vote_stats',
        store=True,
    )
    total_voter_count = fields.Integer(
        string='Total Voter Count',
        compute='_compute_total_voter_count',
        store=True,
    )

    result_summary = fields.Json(string='Result Summary')

    # Round managers
    round_manager_ids = fields.Many2many(
        'res.partner',
        'aps_award_vote_round_manager_rel',
        'round_id',
        'partner_id',
        string='Round Managers',
    )

    # Related votes
    vote_ids = fields.One2many(
        'aps.award.vote',
        'vote_round_id',
        string='Votes',
    )

    display_name = fields.Char(compute='_compute_display_name', store=True)

    # Reschedule tracking
    child_reschedule_id = fields.Many2one(
        'aps.award.vote.round',
        string='Rescheduled To',
        ondelete='set null',
        help='When this round has been rescheduled, points to the next round that was created. Empty if the round has not been rescheduled.',
    )

    # ── Onchange handlers ────────────────────────────────────────────────────

    @api.onchange('award_category_id')
    def _onchange_award_category_id(self):
        for rec in self:
            if rec.award_category_id and rec.award_category_id.image:
                rec.image = rec.award_category_id.image

    @api.onchange('voting_set_ids')
    def _onchange_voting_set_ids(self):
        for rec in self:
            if rec.voting_set_ids:
                first_set = rec.voting_set_ids[0]
                if first_set.color:
                    rec.color = first_set.color

    # ── Computes ─────────────────────────────────────────────────────────────

    @api.depends('name', 'datetime_start', 'status')
    def _compute_display_name(self):
        for rec in self:
            if rec.datetime_start:
                rec.display_name = f"{rec.name} ({rec.datetime_start.strftime('%Y-%m-%d')})"
            else:
                rec.display_name = rec.name or ''

    @api.depends('vote_ids', 'vote_ids.state')
    def _compute_vote_stats(self):
        for rec in self:
            votes = rec.vote_ids
            rec.votes_cast = len(votes.filtered(lambda v: v.state in ('submitted', 'closed')))
            rec.active_voter_count = len(votes.mapped('voter_partner_id'))

    # ── Write override: cascade status changes to all votes ────────────────

    def write(self, vals):
        result = super().write(vals)
        new_status = vals.get('status')
        if new_status in ('closed', 'finalised'):
            # All votes close — even already-submitted ones
            for rec in self:
                active_votes = rec.vote_ids.filtered(lambda v: v.state != 'closed')
                if active_votes:
                    active_votes.write({'state': 'closed'})
        elif new_status == 'draft':
            # Reset votes to pending
            for rec in self:
                pending_votes = rec.vote_ids.filtered(
                    lambda v: v.state not in ('pending')
                )
                if pending_votes:
                    pending_votes.write({'state': 'pending'})
        elif new_status == 'open':
            # Votes with a recipient → submitted; without a recipient → open
            for rec in self:
                for v in rec.vote_ids:
                    if v.submitted_date:
                        v.state = 'submitted'
                    else:
                        v.state = 'open'
        return result

    # ── Lifecycle actions ───────────────────────────────────────────────────

    def action_open(self):
        self.ensure_one()
        all_partner_ids = self._collect_eligible_voter_partners()
        existing_partner_ids = set(self.vote_ids.mapped('voter_partner_id').ids)
        new_partner_ids = all_partner_ids - existing_partner_ids

        if new_partner_ids:
            today = fields.Date.context_today(self)
            due_date = self.datetime_end.date() if self.datetime_end else False
            vals_list = [
                {
                    'vote_round_id': self.id,
                    'voter_partner_id': pid,
                    'state': 'open',
                    'open_date': today,
                    'due_date': due_date,
                    'award_category_id': self.award_category_id.id or False,
                    'award_sub_category_id': self.award_sub_category_id.id or False,
                    'academic_week_id': self.academic_week_id.id or False,
                }
                for pid in new_partner_ids
            ]
            self.env['aps.award.vote'].create(vals_list)

        self.status = 'open'

    def action_close(self):
        self.ensure_one()
        # Close all open and submitted votes in this round
        votes_to_close = self.vote_ids.filtered(lambda v: v.state in ('open', 'submitted'))
        if votes_to_close:
            votes_to_close.write({'state': 'closed'})
        self.status = 'closed'

    def action_finalise(self):
        self.ensure_one()
        self.status = 'finalised'

    def action_reset_draft(self):
        self.ensure_one()
        self.status = 'draft'

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', f"{self.name} (Copy)")
        default.setdefault('status', 'draft')
        return super().copy(default)

    # ── Scheduled action ────────────────────────────────────────────────────

    @api.model
    def action_send_voting_reminders(self):
        """Cron method: send reminder emails to staff with open votes that close today,
        for rounds that have reminders enabled.
        Runs daily at 8 AM — only targets rounds whose datetime_end is today.
        """
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)

        open_rounds = self.search([
            ('status', '=', 'open'),
            ('datetime_end', '>=', today_start),
            ('datetime_end', '<=', today_end),
        ]).filtered('rule_send_reminder_email')

        if not open_rounds:
            return True

        Vote = self.env['aps.award.vote']
        open_votes = Vote.search([
            ('vote_round_id', 'in', open_rounds.ids),
            ('state', '=', 'open'),
        ])
        if not open_votes:
            return True

        # Group open votes by voter partner
        voters = {}
        for vote in open_votes:
            pid = vote.voter_partner_id.id
            if pid not in voters:
                voters[pid] = {'partner': vote.voter_partner_id, 'votes': []}
            voters[pid]['votes'].append(vote)

        template = self.env.ref('aps_sis.email_template_voting_reminder', raise_if_not_found=False)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')

        for pid, voter_data in voters.items():
            partner = voter_data['partner']
            votes = voter_data['votes']

            if not partner.email:
                continue

            token = partner.sudo()._get_or_create_access_token()
            voting_url = f"{base_url}/awards/vote/{token}"

            # Build per-round summary rows
            vote_rows = []
            for v in votes:
                rnd = v.vote_round_id
                total = rnd.total_voter_count or 0
                cast = rnd.votes_cast or 0
                pct = int(cast * 100 / total) if total else 0
                vote_rows.append({
                    'round_name': rnd.name,
                    'due_date': v.due_date.strftime('%d %b %Y') if v.due_date else 'No due date',
                    'pct_submitted': pct,
                    'votes_cast': cast,
                    'total_voters': total,
                })

            if template:
                template.with_context(
                    voter_name=partner.name,
                    voting_url=voting_url,
                    vote_rows=vote_rows,
                ).send_mail(
                    votes[0].vote_round_id.id,
                    email_values={
                        'recipient_ids': [(4, partner.id)],
                        'email_to': partner.email,
                    },
                    force_send=True,
                )

        return True

    @api.model
    def cron_close_expired_rounds(self):
        """Cron method: close rounds whose end datetime has passed.
        Called every 10 minutes — updates round status and all related
        open/submitted votes to 'closed'.
        """
        now = fields.Datetime.now()
        expired = self.search([('status', '=', 'open'), ('datetime_end', '<=', now)])
        for rnd in expired:
            rnd.action_close()
        return True

    @api.model
    def cron_reschedule_rounds(self):
        """Cron: duplicate rounds where recurring_days > 0 and the reschedule
        deadline (datetime_start + recurring_days) has passed, but no child
        round has been created yet.
        """
        now = fields.Datetime.now()
        candidates = self.search([
            ('recurring_days', '>', 0),
            ('child_reschedule_id', '=', False),
            ('datetime_start', '!=', False),
        ])
        to_reschedule = candidates.filtered(
            lambda r: r.datetime_start and (r.datetime_start + timedelta(days=r.recurring_days) <= now)
        )
        for rnd in to_reschedule:
            shift = timedelta(days=rnd.recurring_days)
            child = rnd.copy({
                'datetime_start': rnd.datetime_start + shift,
                'datetime_end': rnd.datetime_end + shift if rnd.datetime_end else False,
            })
            rnd.child_reschedule_id = child.id
        return True