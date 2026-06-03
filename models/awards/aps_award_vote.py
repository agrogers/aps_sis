from odoo import api, fields, models


class APSAwardVote(models.Model):
    _name = 'aps.award.vote'
    _description = 'Award Vote'
    _order = 'submitted_date desc, id desc'

    description = fields.Text(
        string='Description',
        compute='_compute_description_fields', store=True, readonly=False,
    )
    short_description = fields.Text(
        string='Short Description',
        compute='_compute_description_fields', store=True, readonly=False,
    )
    image = fields.Image(
        string='Image',
        compute='_compute_description_fields', store=True, readonly=False,
    )

    @api.depends(
        'vote_round_id.description', 'vote_round_id.short_description', 'vote_round_id.image',
        'award_category_id.description', 'award_category_id.short_description', 'award_category_id.image',
    )
    def _compute_description_fields(self):
        for rec in self:
            rnd = rec.vote_round_id
            cat = rec.award_category_id
            rec.description = (rnd and rnd.description) or (cat and cat.description) or False
            rec.short_description = (rnd and rnd.short_description) or (cat and cat.short_description) or False
            rec.image = (rnd and rnd.image) or (cat and cat.image) or False

    award_category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        required=False,
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
    recipient_partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=False,
        ondelete='restrict',
    )
    voter_partner_id = fields.Many2one(
        'res.partner',
        string='Voter',
        required=True,
        ondelete='restrict',
    )
    note = fields.Text(string='Note')
    comment = fields.Text(string='Comment')
    submitted_date = fields.Date(string='Date')
    open_date = fields.Date(string='Open Date')
    due_date = fields.Date(string='Due Date')
    vote_round_id = fields.Many2one(
        'aps.award.vote.round',
        string='Vote Round',
        required=False,
        ondelete='set null',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('open', 'Open'),
            ('submitted', 'Submitted'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='open',
        required=True,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Related / convenience fields for list, pivot, graph views
    # ------------------------------------------------------------------

    round_name = fields.Char(
        related='vote_round_id.name', string='Round', store=True, readonly=True,
    )
    round_status = fields.Selection(
        related='vote_round_id.status', string='Round Status', store=True, readonly=True,
    )
    round_image = fields.Image(
        related='vote_round_id.image', string='Round Image', readonly=True,
    )
    round_datetime_start = fields.Datetime(
        related='vote_round_id.datetime_start', string='Round Start', store=True, readonly=True,
    )
    round_datetime_end = fields.Datetime(
        related='vote_round_id.datetime_end', string='Round End', store=True, readonly=True,
    )
    category_name = fields.Char(
        related='award_category_id.name', string='Category', store=True, readonly=True,
    )
    category_image = fields.Image(
        related='award_category_id.image', string='Category Image', readonly=True,
    )
    recipient_name = fields.Char(
        related='recipient_partner_id.name', string='Recipient Name', store=True, readonly=True,
    )
    voter_name = fields.Char(
        related='voter_partner_id.name', string='Voter Name', store=True, readonly=True,
    )
    voter_access_token = fields.Char(
        string='Voter Access Token',
        compute='_compute_voter_access_token',
    )

    @api.depends('voter_partner_id')
    def _compute_voter_access_token(self):
        for rec in self:
            if not rec.voter_partner_id:
                rec.voter_access_token = ''
                continue
            employee = self.env['hr.employee'].sudo().search(
                [('user_id.partner_id', '=', rec.voter_partner_id.id)], limit=1
            )
            rec.voter_access_token = employee._get_or_create_access_token() if employee else ''
