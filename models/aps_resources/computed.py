import re
from odoo import models, fields, api


class APSResource(models.Model):
    _inherit = 'aps.resources'

    @api.depends('subjects')
    def _compute_subject_icons(self):
        for record in self:
            if record.subjects:
                first = record.subjects[:1]
                record.subject_icons = first.icon if first else False
            else:
                record.subject_icons = False

    @api.depends('share_token')
    def _compute_share_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            if rec.share_token:
                rec.share_url = f'{base_url}/resource/share/{rec.share_token}'
            else:
                rec.share_url = False

    @api.depends('type_id', 'type_id.icon')
    def _compute_type_icon(self):
        # This is needed because without it the icon is never cached properly.
        # That means there is a lot of annoying downloads on every page refresh.
        # It is duplicated in other models as well.
        for record in self:
            record.type_icon = record.type_id.icon if record.type_id else False

    @api.depends('url', 'name', 'display_name', 'type_icon', 'type_id.name',
                 'supporting_resource_ids', 'supporting_resource_ids.url',
                 'supporting_resource_ids.name', 'supporting_resource_ids.display_name',
                 'supporting_resource_ids.type_icon', 'supporting_resource_ids.type_id.name',
                 'supporting_resource_ids.sequence', 'supporting_resource_ids.notes',
                 'supporting_resource_ids.has_notes', 'supporting_resource_ids.has_question')
    def _compute_supporting_resources_buttons(self):
        """Compute JSON data for resource links widget."""
        for resource in self:
            links = []
            # Only process if resource.id is a real id (not NewId)
            if resource.url and isinstance(resource.id, int):
                links.append({
                    'id': resource.id,
                    'name': resource.name or resource.display_name,
                    'url': resource.url,
                    'icon_url': f'/web/image/aps.resources/{resource.id}/type_icon' if resource.type_icon else False,
                    'type_name': resource.type_id.name if resource.type_id else 'Resource',
                    'is_main': True,
                    'out_of_marks': resource.marks,
                })
            # Add supporting resources with URLs, or notes-only resources (no URL, no question)
            for supporting in resource.supporting_resource_ids.sorted('sequence'):
                if not isinstance(supporting.id, int):
                    continue
                if supporting.url:
                    links.append({
                        'id': supporting.id,
                        'name': supporting.name or supporting.display_name,
                        'url': supporting.url,
                        'icon_url': f'/web/image/aps.resources/{supporting.id}/type_icon' if supporting.type_icon else False,
                        'type_name': supporting.type_id.name if supporting.type_id else 'Resource',
                        'is_main': False,
                        'out_of_marks': supporting.marks,
                    })
                elif supporting.notes and supporting.has_question == 'no':
                    # Resource has notes but no URL and no question — show a notes popup
                    links.append({
                        'id': supporting.id,
                        'name': supporting.name or supporting.display_name,
                        'url': None,
                        'icon_url': f'/web/image/aps.resources/{supporting.id}/type_icon' if supporting.type_icon else False,
                        'type_name': supporting.type_id.name if supporting.type_id else 'Resource',
                        'is_main': False,
                        'out_of_marks': supporting.marks,
                        'link_type': 'notes',
                    })
            resource.supporting_resources_buttons = links

    @api.depends('child_ids')
    def _compute_child_count(self):
        for rec in self:
            # Count resources that have this resource as a parent
            rec.child_count = self.search_count([('parent_ids', 'in', rec.id)])

    @api.depends('parent_ids')
    def _compute_has_multiple_parents(self):
        for rec in self:
            rec.has_multiple_parents = len(rec.parent_ids) > 1

    @api.depends('custom_name_ids.custom_name', 'custom_name_ids.parent_resource_id')
    def _compute_parent_custom_name_data(self):
        """Compute a Python list containing the custom names for this resource keyed by parent id.
        This uses `fields.Json` so we assign a native Python structure and let Odoo handle serialization."""
        for rec in self:
            data = []
            for c in rec.custom_name_ids:
                if c.parent_resource_id and c.custom_name:
                    # Replace NewId (in-memory) ids with False so JSON serialization succeeds
                    cid = c.id if isinstance(c.id, int) else False
                    data.append({
                        'parent_resource_id': c.parent_resource_id.id,
                        'custom_name': c.custom_name,
                        'id': cid,
                    })
            rec.parent_custom_name_data = data or False

    @api.depends('task_ids.submission_ids')
    def _compute_dashboard_stats(self):
        for rec in self:
            submissions = rec.task_ids.mapped('submission_ids')
            rec.total_submissions = len(submissions)
            rec.completed_submissions = len(submissions.filtered(lambda s: s.state == 'complete'))
            rec.overdue_tasks = len(rec.task_ids.filtered(lambda t: t.date_due and t.date_due < fields.Date.today() and t.state != 'complete'))

    @api.depends('primary_parent_id.display_name', 'primary_parent_id.name', 'name', 'parent_ids')
    def _compute_display_name(self):
        """Build display name from ancestor chain, removing redundant overlapping characters."""
        for rec in self:
            # Priority: 1. primary_parent_id, 2. first parent from parent_ids, 3. just name
            parent_to_use = rec.primary_parent_id or (rec.parent_ids and rec.parent_ids[0])

            if parent_to_use:
                parent_display = parent_to_use.display_name or parent_to_use.name or ''
                current_name = rec.name or ''
                separator = ' 🢒 '

                # Remove bracketed text that matches part or all of the parent
                if current_name and parent_display:
                    # Find all text in brackets (round, square, or curly)
                    bracketed_texts = re.findall(r'\([^)]+\)|\[[^\]]+\]|{[^}]+}', current_name)
                    for bracketed in bracketed_texts:
                        # Remove brackets to get the content
                        content = bracketed[1:-1]  # Remove first and last character (brackets)
                        # Check if this content appears in the parent display name
                        if content in parent_display:
                            # Remove the entire bracketed text from current_name
                            current_name = current_name.replace(bracketed, '').strip()

                # Remove leading words from child that appear in parent's last segment.
                # Handles cases like "File Management Video Overview" → "Video Overview"
                # when parent ends with "Ch 14: File Management".
                if current_name and parent_display:
                    # Get the last segment of parent (after last separator)
                    parent_last_segment = parent_display.split(separator)[-1] if separator in parent_display else parent_display
                    # Normalize: extract words (alphanumeric sequences), lowercase
                    parent_words = set(re.findall(r'\b[a-zA-Z]+\b', parent_last_segment.lower()))

                    # Split child name into words while preserving structure
                    child_words = re.split(r'(\s+)', current_name)  # Split but keep separators

                    # Find how many leading words to remove (words that appear in parent)
                    words_to_remove = 0
                    for word in child_words:
                        word_lower = word.lower().strip()
                        if not word_lower or word.isspace():
                            words_to_remove += 1
                            continue
                        # Check if word appears in parent (fuzzy: allow 1-2 char difference for typos)
                        if word_lower in parent_words or any(
                            self._similar_words(word_lower, pw) for pw in parent_words
                        ):
                            words_to_remove += 1
                        else:
                            break

                    if words_to_remove > 0:
                        current_name = ''.join(child_words[words_to_remove:]).strip()
                        # Strip leading punctuation left over after word removal
                        current_name = re.sub(r'^[\s:;.,\-–—()\[\]{}]+', '', current_name).strip()

                # Find overlapping characters between start of current_name and end of parent_display
                overlap_length = 0
                parent_len = len(parent_display)
                current_len = len(current_name)

                # Check if current_name starts with the suffix of parent_display
                # Compare current_name[0:n] with parent_display[-n:] for increasing n
                match_found = False
                for i in range(1, min(parent_len, current_len) + 1):
                    if current_name[:i] == parent_display[-i:]:
                        overlap_length = i
                        match_found = True
                    else:
                        if match_found:
                            break

                # Remove overlapping characters from current_name
                if overlap_length > 0:
                    remaining_name = current_name[overlap_length:].lstrip()
                    # Strip any "." that appear at the start of the remaining name
                    remaining_name = re.sub(r'^[\s:;.,\-–—()\[\]{}]+', '', remaining_name).strip()
                    if remaining_name:
                        rec.display_name = parent_display + separator + remaining_name
                    else:
                        rec.display_name = parent_display
                else:
                    # No overlap, concatenate normally
                    if current_name:
                        rec.display_name = parent_display + separator + current_name
                    else:
                        rec.display_name = parent_display
            else:
                rec.display_name = rec.name or ''

    @api.depends('display_name', 'primary_parent_id', 'parent_ids')
    def _compute_display_name_breadcrumb(self):
        """Build a stored list of {id, label} pairs for the breadcrumb pills widget.

        The list runs from the top-level ancestor down to (and including) the current
        resource.  Labels are taken from the segments of ``display_name`` (split by the
        🢒 separator) so they match what is already shown on screen.  IDs are resolved by
        walking up the primary_parent_id / first-parent chain so the pills can open the
        correct form record.
        """
        separator = ' 🢒 '
        for rec in self:
            display = rec.display_name or rec.name or ''
            segments = display.split(separator) if display else [display]

            # Walk from the current record upward to collect the ancestor chain.
            # We stop if we visit a record twice (cycle guard) or reach a root.
            chain = []
            current = rec
            visited = set()
            while current:
                if current in visited:
                    break
                visited.add(current)
                chain.append(current)
                parent = current.primary_parent_id or (current.parent_ids and current.parent_ids[0])
                if not parent:
                    break
                current = parent

            # chain[0] = current record, chain[-1] = root ancestor — reverse so root is first.
            chain.reverse()

            n_seg = len(segments)
            n_chain = len(chain)
            breadcrumb = []
            for i, segment in enumerate(segments):
                # Align from the right so the last segment always maps to the current record.
                chain_idx = n_chain - n_seg + i
                if 0 <= chain_idx < n_chain:
                    res = chain[chain_idx]
                    # Resolve to an integer id; NewId instances (during creation) are not useful as links.
                    origin = getattr(res, '_origin', None)
                    res_id = (origin.id if origin and isinstance(origin.id, int) else
                              res.id if isinstance(res.id, int) else False)
                else:
                    res_id = False
                breadcrumb.append({'id': res_id, 'label': segment})

            rec.display_name_breadcrumb = breadcrumb or [{'id': False, 'label': display}]

    def _similar_words(self, word1, word2):
        """Check if two words are similar (allowing for typos). Returns True if edit distance <= 2."""
        if abs(len(word1) - len(word2)) > 2:
            return False
        if len(word1) < 4 or len(word2) < 4:
            return word1 == word2  # Short words must match exactly
        # Simple check: same start and similar length
        common_prefix = 0
        for c1, c2 in zip(word1, word2):
            if c1 == c2:
                common_prefix += 1
            else:
                break
        # If most characters match, consider similar
        return common_prefix >= min(len(word1), len(word2)) - 2
