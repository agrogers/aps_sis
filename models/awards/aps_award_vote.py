from odoo import fields, models


class APSAwardVote(models.Model):
    _name = 'aps.award.vote'
    _description = 'Award Vote'
    _order = 'submitted_date desc, id desc'

    award_category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        required=True,
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
        ondelete='restrict',
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



    
