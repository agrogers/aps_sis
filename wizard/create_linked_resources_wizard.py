from odoo import api, fields, models


class CreateLinkedResourcesWizard(models.TransientModel):
    _name = 'aps.create.linked.resources'
    _description = 'Create Linked Resources from Field Headings'

    resource_id = fields.Many2one(
        'aps.resources', string='Resource', required=True, readonly=True,
        ondelete='cascade',
    )
    source_field = fields.Selection([
        ('question', 'Question'),
        ('answer', 'Answer'),
        ('notes', 'Notes'),
        ('lesson_plan', 'Lesson Plan'),
    ], string='Source Field', required=True, default='question')
    heading_count = fields.Integer(string='Headings Found', compute='_compute_headings', readonly=True)
    heading_preview = fields.Text(string='Headings Preview', compute='_compute_headings', readonly=True)

    # ------------------------------------------------------------------
    # Computed preview
    # ------------------------------------------------------------------

    @api.depends('source_field', 'resource_id')
    def _compute_headings(self):
        for rec in self:
            html = rec.resource_id[rec.source_field] if rec.resource_id and rec.source_field else False
            headings = self.env['aps.resources']._extract_top_headings_from_html(html or '')
            rec.heading_count = len(headings)
            rec.heading_preview = '\n'.join(f'• {h}' for h in headings) if headings else ''

    # ------------------------------------------------------------------
    # Create linked resources
    # ------------------------------------------------------------------

    def action_create(self):
        """Parse headings from the selected source field and create a linked
        child resource for each heading found at the top-most level."""
        self.ensure_one()
        resource = self.resource_id

        html = resource[self.source_field]
        if not html:
            return self._notification(
                'No Content',
                f'The {self.source_field_label} field is empty.',
                'warning',
            )

        headings = self.env['aps.resources']._extract_top_headings_from_html(html)
        if not headings:
            return self._notification(
                'No Headings Found',
                f'No headings (H1–H6) were found in the {self.source_field_label} field.',
                'warning',
            )

        existing_names = set(resource.child_ids.mapped('name'))
        created = self.env['aps.resources']
        skipped = []
        for title in headings:
            if title in existing_names:
                skipped.append(title)
                continue
            vals = {
                'name': title,
                'parent_ids': [(4, resource.id)],
                'primary_parent_id': resource.id,
                'subjects': [(6, 0, resource.subjects.ids)],
                'type_id': resource.type_id.id,
            }
            # Set has_* fields based on source field
            if self.source_field == 'question':
                vals['has_question'] = 'use_parent'
                vals['has_answer'] = 'use_parent'
            elif self.source_field == 'answer':
                vals['has_answer'] = 'use_parent'
                vals['has_question'] = 'use_parent'
            elif self.source_field == 'notes':
                vals['has_notes'] = 'use_parent'
            # lesson_plan: no has_* fields set on children

            child = self.env['aps.resources'].create(vals)
            created |= child

        if not created and not skipped:
            return self._notification(
                'Nothing to Create',
                'No new headings found to create resources from.',
                'warning',
            )

        # Mark parent as having linked resources and refresh display names
        if created:
            resource.has_child_resources = 'yes'
        resource._compute_display_name()

        msg_parts = []
        if created:
            msg_parts.append(f'Created {len(created)} linked resource(s).')
        if skipped:
            msg_parts.append(f'Skipped {len(skipped)} already existing: {", ".join(skipped)}.')

        return {
            'type': 'ir.actions.act_window_close',
            'infos': {
                'notification': {
                    'title': 'Resources Created',
                    'message': ' '.join(msg_parts),
                    'type': 'success',
                    'sticky': bool(skipped),
                },
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def source_field_label(self):
        return dict(self._fields['source_field'].selection).get(self.source_field, self.source_field)

    def _notification(self, title, message, msg_type='info', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': msg_type,
                'sticky': sticky,
            },
        }
