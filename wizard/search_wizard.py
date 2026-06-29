from odoo import api, fields, models


class APSSISSearchWizard(models.TransientModel):
    _name = 'aps.sis.search.wizard'
    _description = 'Resource/Submission Search Wizard'

    search_target = fields.Selection(
        [('resource', 'Resources'), ('submission', 'Submissions')],
        default='resource',
        required=True,
        string='Search In',
    )
    is_favourite = fields.Boolean(
        string='Favourites Only',
        help='Show only resources marked as favourites',
    )
    subject_category_ids = fields.Many2many(
        'aps.subject.category',
        string='Subject Categories',
    )
    type_ids = fields.Many2many(
        'aps.resource.types',
        string='Resource Types',
    )
    name_text = fields.Char(
        string='Name / Search Text',
        help='Search by name, display name, or other text fields',
    )

    # ------------------------------------------------------------------
    # Settings persistence (per-user via ir.config_parameter)
    # ------------------------------------------------------------------
    def _load_defaults(self):
        """Load last-used values from ir.config_parameter for this user."""
        ICP = self.env['ir.config_parameter'].sudo()
        prefix = f'aps.sis.search.wizard.user.{self.env.uid}'
        defaults = {
            'search_target': ICP.get_param(f'{prefix}.search_target', default='resource'),
            'is_favourite': ICP.get_param(f'{prefix}.is_favourite', default='False') == 'True',
        }
        for key, val in defaults.items():
            if hasattr(self, key):
                setattr(self, key, val)

    def _save_settings(self):
        """Persist current wizard values per user."""
        ICP = self.env['ir.config_parameter'].sudo()
        prefix = f'aps.sis.search.wizard.user.{self.env.uid}'
        ICP.set_param(f'{prefix}.search_target', self.search_target or 'resource')
        ICP.set_param(f'{prefix}.is_favourite', str(bool(self.is_favourite)))

    # ------------------------------------------------------------------
    # Action: build domain and open target list view
    # ------------------------------------------------------------------
    def action_search(self):
        self.ensure_one()
        self._save_settings()

        domain = []

        # Name text search
        if self.name_text:
            domain.append(('display_name', 'ilike', self.name_text))

        # Subject categories
        if self.subject_category_ids:
            domain.append(('subject_categories', 'in', self.subject_category_ids.ids))

        # Resource types
        if self.type_ids:
            domain.append(('type_id', 'in', self.type_ids.ids))

        if self.search_target == 'resource':
            # Favourites — only applicable to resources
            if self.is_favourite:
                domain.append(('favourite_user_ids', 'in', [self.env.uid]))

            return {
                'type': 'ir.actions.act_window',
                'name': 'Resources',
                'res_model': 'aps.resources',
                'view_mode': 'list,kanban,form',
                'domain': domain,
                'target': 'current',
            }

        else:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Submissions',
                'res_model': 'aps.resource.submission',
                'view_mode': 'list,form,pivot,kanban,graph,calendar',
                'domain': domain,
                'context': {'search_default_submission_active': 1},
                'target': 'current',
            }