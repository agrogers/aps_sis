import re
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

    @api.model_create_multi
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

    def _resolve_submission_names(self, top_level_resource, top_level_name=None):
        """Build a mapping of resource id → submission name for a set of resources
        being assigned under *top_level_resource*.

        ``self`` is the full recordset of resources to assign (including the
        top-level resource itself).

        Custom names defined via ``aps.resource.custom.name`` are respected.
        When a custom name is found on a parent→child link the custom name
        cascades to all descendants below that link using the same
        overlap-removal algorithm as ``_compute_display_name``.

        Returns ``dict[int, str]`` mapping resource id to its submission name.
        """
        separator = ' 🢒 '
        base_name = top_level_name or top_level_resource.display_name or top_level_resource.name or ''

        # Pre-load all custom name records relevant to resources in self.
        custom_names = self.env['aps.resource.custom.name'].search([
            ('resource_id', 'in', self.ids),
            ('parent_resource_id', 'in', self.ids),
        ])
        # Build lookup: (parent_id, child_id) → custom_name
        custom_map = {}
        for cn in custom_names:
            custom_map[(cn.parent_resource_id.id, cn.resource_id.id)] = cn.custom_name

        # Build adjacency: parent_id → [child_ids] restricted to resources in self
        resource_ids_set = set(self.ids)
        children_of = {}
        for res in self:
            for child in res.child_ids:
                if child.id in resource_ids_set:
                    children_of.setdefault(res.id, []).append(child)

        # Walk the tree from top_level_resource with BFS, propagating names.
        result = {}
        # Queue entries: (resource, accumulated_display_name, name_substitutions)
        # name_substitutions is a list of (original_prefix, replacement_prefix) pairs
        # that cascade from ancestor custom names to all descendants.
        queue = [(top_level_resource, base_name, [])]
        visited = set()

        while queue:
            resource, parent_display, inherited_subs = queue.pop(0)
            if resource.id in visited:
                continue
            visited.add(resource.id)

            if resource.id == top_level_resource.id:
                effective_display = base_name
                subs_for_children = inherited_subs
            else:
                # Check for a custom name on any ancestor→resource link that is in
                # the assignment set.
                custom_name_found = None
                effective_name = resource.name or ''
                for parent in resource.parent_ids:
                    if parent.id in resource_ids_set:
                        cn = custom_map.get((parent.id, resource.id))
                        if cn:
                            custom_name_found = cn
                            break

                if custom_name_found:
                    # This resource has its own custom name — use it directly
                    # and add a substitution rule for descendants.
                    subs_for_children = inherited_subs + [(effective_name, custom_name_found)]
                    effective_name = custom_name_found
                else:
                    # Apply inherited substitutions: replace longest matching
                    # prefix first to avoid partial matches.
                    subs_for_children = inherited_subs
                    for original, replacement in sorted(
                        inherited_subs, key=lambda s: len(s[0]), reverse=True
                    ):
                        if effective_name.startswith(original):
                            effective_name = replacement + effective_name[len(original):]
                            break

                # Apply overlap-removal algorithm (same logic as _compute_display_name)
                effective_display = self._build_display_segment(parent_display, effective_name, separator)

            result[resource.id] = effective_display

            # Enqueue children
            for child in children_of.get(resource.id, []):
                if child.id not in visited:
                    queue.append((child, effective_display, subs_for_children))

        # Resources in self that weren't reached by BFS (disjoint from the tree)
        for res in self:
            if res.id not in result:
                result[res.id] = base_name + separator + (res.name or '')

        # Strip ancestor prefix — keep only the selected resource's own
        # name segment and its descendants (e.g. "A 🢒 B 🢒 C" → "C").
        top_resolved = result.get(top_level_resource.id, '')
        last_sep_idx = top_resolved.rfind(separator)
        if last_sep_idx >= 0:
            prefix = top_resolved[:last_sep_idx + len(separator)]
            result = {
                rid: n[len(prefix):] if n.startswith(prefix) else n
                for rid, n in result.items()
            }

        return result

    @api.model
    def _build_display_segment(self, parent_display, child_name, separator=' 🢒 '):
        """Combine parent_display and child_name using the same overlap-removal
        algorithm used by ``_compute_display_name``."""
        if not child_name:
            return parent_display

        current_name = child_name

        # Remove bracketed text that matches part of the parent
        if current_name and parent_display:
            bracketed_texts = re.findall(r'\([^)]+\)|\[[^\]]+\]|{[^}]+}', current_name)
            for bracketed in bracketed_texts:
                content = bracketed[1:-1]
                if content in parent_display:
                    current_name = current_name.replace(bracketed, '').strip()

        # Remove leading words from child that appear in parent's last segment
        if current_name and parent_display:
            parent_last_segment = parent_display.split(separator)[-1] if separator in parent_display else parent_display
            parent_words = set(re.findall(r'\b[a-zA-Z]+\b', parent_last_segment.lower()))
            child_words = re.split(r'(\s+)', current_name)
            words_to_remove = 0
            for word in child_words:
                word_lower = word.lower().strip()
                if not word_lower or word.isspace():
                    words_to_remove += 1
                    continue
                if word_lower in parent_words:
                    words_to_remove += 1
                else:
                    break
            if words_to_remove > 0:
                current_name = ''.join(child_words[words_to_remove:]).strip()
                current_name = re.sub(r'^[\s:;.,\-–—()\[\]{}]+', '', current_name).strip()

        # Find overlapping characters between end of parent and start of child
        overlap_length = 0
        parent_len = len(parent_display)
        current_len = len(current_name)
        match_found = False
        for i in range(1, min(parent_len, current_len) + 1):
            if current_name[:i] == parent_display[-i:]:
                overlap_length = i
                match_found = True
            else:
                if match_found:
                    break

        # Word boundary check
        # Exception: Q-prefixed names (Q1, Q5a, etc.) allow shorter overlaps
        # and skip the word-boundary check so Q1a collapses to "a" under Q1.
        q_prefix = bool(re.match(r'^Q\d', current_name))
        min_overlap = 2 if q_prefix else 3
        if overlap_length >= min_overlap and not q_prefix:
            child_boundary = (overlap_length >= current_len or
                              not current_name[overlap_length].isalnum())
            parent_start = parent_len - overlap_length
            parent_boundary = (parent_start == 0 or
                               not parent_display[parent_start - 1].isalnum())
            if not (child_boundary and parent_boundary):
                overlap_length = 0

        if overlap_length >= min_overlap:
            remaining_name = current_name[overlap_length:].lstrip()
            remaining_name = re.sub(r'^[\s:;.,\-–—()\[\]{}]+', '', remaining_name).strip()
            if remaining_name:
                return parent_display + separator + remaining_name
            else:
                return parent_display
        else:
            if current_name:
                return parent_display + separator + current_name
            else:
                return parent_display
