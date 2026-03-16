import uuid
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class APSResource(models.Model):
    _inherit = 'aps.resources'

    def action_generate_share_token(self):
        """(Re)generate the share token, invalidating any previously shared links."""
        self.ensure_one()
        self.share_token = str(uuid.uuid4())

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('primary_parent_id', 'parent_ids')
    def _check_primary_parent(self):
        for rec in self:
            if rec.primary_parent_id and rec.primary_parent_id not in rec.parent_ids:
                raise ValidationError("The primary parent must be one of the selected parent resources.")

    # ── Onchange handlers ─────────────────────────────────────────────────────

    @api.onchange('parent_ids')
    def _onchange_parent_ids(self):
        """Clear primary parent if it's no longer in the parent list, or set it if not set."""
        if self.primary_parent_id and self.primary_parent_id not in self.parent_ids:
            self.primary_parent_id = False
        elif not self.primary_parent_id and self.parent_ids:
            # Set primary parent to the first parent if not set
            self.primary_parent_id = self.parent_ids[0]

    @api.onchange('url')
    def _onchange_url(self):
        """Automatically assign resource type based on URL keywords."""
        if self.url:
            # Search for resource types that have URL keywords
            resource_types = self.env['aps.resource.types'].search([('url_keywords', '!=', False)])
            for resource_type in resource_types:
                if resource_type.url_keywords:
                    # Check if any of the keywords (comma-separated) are in the URL
                    keywords = [kw.strip().lower() for kw in resource_type.url_keywords.split(',')]
                    url_lower = self.url.lower()
                    if any(keyword in url_lower for keyword in keywords):
                        self.type_id = resource_type
                        break  # Stop at the first match

    # ── Primary parent sync ───────────────────────────────────────────────────

    def _sync_primary_parent(self):
        """Ensure `primary_parent_id` is set to a valid parent whenever parents exist."""
        for rec in self:
            if rec.parent_ids:
                if not rec.primary_parent_id or rec.primary_parent_id not in rec.parent_ids:
                    # Use update() to avoid cascading writes and recursion
                    rec.sudo().update({'primary_parent_id': rec.parent_ids[0].id})
            else:
                # No parents: clear primary_parent_id
                if rec.primary_parent_id:
                    rec.sudo().update({'primary_parent_id': False})

    # ── ORM overrides ─────────────────────────────────────────────────────────

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        parent_id = self.env.context.get('default_primary_parent_id')
        if parent_id and 'primary_parent_id' in fields_list:
            res['primary_parent_id'] = parent_id

        # Handle many2many default for parent_ids
        default_parent_ids = self.env.context.get('default_parent_ids')
        if default_parent_ids and 'parent_ids' in fields_list:
            res['parent_ids'] = default_parent_ids
            # Extract parent ID from the many2many command and set primary_parent_id
            if default_parent_ids and len(default_parent_ids) > 0:
                command = default_parent_ids[0]
                if len(command) >= 3 and command[0] == 6 and command[2]:  # (6, 0, [ids])
                    parent_ids_list = command[2]
                    if parent_ids_list and 'primary_parent_id' in fields_list and not res.get('primary_parent_id'):
                        res['primary_parent_id'] = parent_ids_list[0]

        # Set default type_id to the most recently used type
        if 'type_id' in fields_list and not res.get('type_id'):
            # Find the most recent resource with a type_id
            recent_resource = self.search([('type_id', '!=', False)], order='write_date desc', limit=1)
            if recent_resource:
                res['type_id'] = recent_resource.type_id.id

        return res

    def write(self, vals):
        result = super().write(vals)
        # Ensure primary_parent_id stays consistent after any write
        self._sync_primary_parent()

        if 'score_contributes_to_parent' in vals:
            # When the contribution flag changes, re-trigger parent score recalculation
            # for every parent resource that has auto_score submissions.
            parent_resources = self.mapped('parent_ids')
            if parent_resources:
                parent_submissions = self.env['aps.resource.submission'].search([
                    ('resource_id', 'in', parent_resources.ids),
                    ('auto_score', '=', True),
                ])
                if parent_submissions:
                    parent_submissions._recalculate_score_from_children()

        if any(field_name in vals for field_name in ['has_notes', 'primary_parent_id', 'name']):
            self._sync_notes_from_parent()
        if any(field_name in vals for field_name in ['has_question', 'primary_parent_id', 'name']):
            self._sync_questions_from_parent()
        if any(field_name in vals for field_name in ['has_answer', 'primary_parent_id', 'name']):
            self._sync_answers_from_parent()

        if 'name' in vals:
            # When name changes, update display_name for self and direct children
            for rec in self:
                rec._compute_display_name()
                # Update display_name for direct children
                children = self.search([('parent_ids', 'in', rec.id)])
                if children:
                    children._compute_display_name()

        """Update records and invalidate child caches if notes changed."""
        if 'notes' in vals or 'has_notes' in vals:
            self._update_child_notes()
        if 'question' in vals or 'has_question' in vals:
            self._update_child_questions()
        if 'answer' in vals or 'has_answer' in vals:
            self._update_child_answers()
        return result

    def copy(self, default=None):
        default = dict(default or {})
        name = default.get('name') or self.name or ''
        if name and not name.endswith(' (copy)'):
            default['name'] = f"{name} (copy)"
        return super().copy(default)

    @api.model
    def create(self, vals_list):
        records = super().create(vals_list)
        # Ensure primary_parent_id is set whenever parents exist on new records
        records._sync_primary_parent()
        records._sync_notes_from_parent()
        records._sync_questions_from_parent()
        records._sync_answers_from_parent()
        return records

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _get_all_descendants(self):
        """Recursively get all descendants of this resource in the graph."""
        descendants = self.env['aps.resources']
        to_process = self.child_ids  # Direct children

        while to_process:
            descendants |= to_process
            next_level = self.env['aps.resources']
            for child in to_process:
                next_level |= child.child_ids
            to_process = next_level - descendants  # Avoid duplicates

        return descendants

    @api.model
    def _default_assignment_duration(self):
        """Return the default duration for assignments (e.g., 7 days)."""
        from datetime import timedelta
        return timedelta(days=6)
