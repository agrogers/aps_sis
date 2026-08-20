from odoo import api, fields, models
from odoo.exceptions import UserError


class APSClassRolloverWizard(models.TransientModel):
    _name = 'aps.class.rollover.wizard'
    _description = 'Roll Over Classes to New Academic Year'

    from_year_id = fields.Many2one(
        'aps.academic.year',
        string='Current Academic Year',
        required=True,
        default=lambda self: self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        ),
    )
    to_year_id = fields.Many2one(
        'aps.academic.year',
        string='New Academic Year',
        required=True,
    )
    class_ids = fields.Many2many(
        'aps.class',
        relation='aps_class_rollover_wizard_class_rel',
        column1='wizard_id',
        column2='class_id',
        string='Classes to Roll Over',
        domain="[('academic_year_id', '=', from_year_id)]",
    )
    result_message = fields.Html(readonly=True)
    has_result = fields.Boolean(default=False)

    @api.onchange('from_year_id')
    def _onchange_from_year_id(self):
        self.class_ids = [(5, 0, 0)]

    def action_apply(self):
        self.ensure_one()
        if not self.from_year_id or not self.to_year_id:
            raise UserError(_("Please select both a current and a new academic year."))
        if self.from_year_id == self.to_year_id:
            raise UserError(_("Current and new academic year must be different."))
        if not self.class_ids:
            raise UserError(_("Please select at least one class to roll over."))

        classes = self.class_ids
        existing_names = self.env['aps.class'].search([
            ('academic_year_id', '=', self.to_year_id.id),
        ]).mapped('name')

        created = 0
        skipped = 0
        skipped_names = []

        for cls in classes:
            if cls.name in existing_names:
                skipped += 1
                skipped_names.append(cls.name)
            else:
                cls.copy({
                    'academic_year_id': self.to_year_id.id,
                })
                created += 1

        lines = [f"<b>{created}</b> class(es) rolled over to <b>{self.to_year_id.display_name}</b>."]
        if skipped:
            lines.append(
                f"<b>{skipped}</b> skipped (already exist in target year): "
                + ", ".join(skipped_names)
            )

        self.result_message = "<p>" + "</p><p>".join(lines) + "</p>"
        self.has_result = True
