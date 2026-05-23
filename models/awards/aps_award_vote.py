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
        required=False,  # Filled in by the voter when casting; not required at ballot creation
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
        required=False,         # We might to allow blank and use this as a prompt for teachers to vote without specifying a recipient, especially in the case of write-in votes.
        ondelete='restrict',
    )
    voter_partner_id = fields.Many2one(
        'res.partner',
        string='Voter',
        required=True,
        ondelete='restrict',
    )
    note = fields.Text(string='Note')   # Note from the system about the vote, e.g. "Write-in vote for [Name]" or "Vote cast by [Teacher Name] without specifying a recipient"
    comment = fields.Text(string='Comment')  # Comment from the voter
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



    
