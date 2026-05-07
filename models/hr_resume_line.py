from odoo import fields, models


class HrResumeLine(models.Model):
    """Override hr.resume.line to make start and end dates optional.

    Standard Odoo requires date_start on resume lines, but this is
    overly restrictive for entries such as ongoing roles or
    qualifications that have no fixed start date.
    """

    _inherit = 'hr.resume.line'

    date_start = fields.Date(required=False)
    date_end = fields.Date(required=False)
