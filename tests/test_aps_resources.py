from odoo.tests.common import TransactionCase

class TestAPSResource(TransactionCase):

    def test_compute_display_name_simple(self):
        """Test that display_name is set correctly for a resource with no parents."""
        resource = self.env['aps.resources'].create({
            'name': 'Test Resource',
        })
        self.assertEqual(resource.display_name, 'Test Resource')

    def test_compute_display_name_with_parent(self):
        """Test that display_name includes parent for a resource with a parent."""
        parent = self.env['aps.resources'].create({
            'name': 'Parent Resource',
        })
        child = self.env['aps.resources'].create({
            'name': 'Child Resource',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })
        expected = 'Parent Resource 🢒 Child Resource'
        self.assertEqual(child.display_name, expected)

    def test_breadcrumb_last_pill_has_parent_id(self):
        """The second-to-last breadcrumb entry provides the parent_id used
        to query siblings from the frontend widget."""
        parent = self.env['aps.resources'].create({'name': 'Parent'})
        child = self.env['aps.resources'].create({
            'name': 'Child',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })
        bc = child.display_name_breadcrumb
        self.assertIsInstance(bc, list)
        self.assertEqual(len(bc), 2)
        # Second-to-last entry should carry the parent's id
        self.assertEqual(bc[-2]['id'], parent.id)
        # Last entry should carry the child's id
        self.assertEqual(bc[-1]['id'], child.id)

    def test_sibling_resources_query(self):
        """Resources that share the same parent (via parent_ids) are siblings.
        The frontend fetches siblings with domain [('parent_ids', 'in', [parent_id])].
        Verify that this domain returns the expected siblings and excludes others."""
        parent = self.env['aps.resources'].create({'name': 'Parent'})
        sibling_a = self.env['aps.resources'].create({
            'name': 'Sibling A',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })
        sibling_b = self.env['aps.resources'].create({
            'name': 'Sibling B',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })
        unrelated = self.env['aps.resources'].create({'name': 'Unrelated'})

        # The domain the frontend widget uses to fetch siblings
        siblings = self.env['aps.resources'].search(
            [('parent_ids', 'in', [parent.id])]
        )
        self.assertIn(sibling_a, siblings)
        self.assertIn(sibling_b, siblings)
        self.assertNotIn(unrelated, siblings)
        self.assertNotIn(parent, siblings)

    def test_sibling_list_excludes_self(self):
        """The current resource must not appear in its own sibling dropdown."""
        parent = self.env['aps.resources'].create({'name': 'Parent'})
        current = self.env['aps.resources'].create({
            'name': 'Current',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })
        self.env['aps.resources'].create({
            'name': 'Other',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })

        all_children = self.env['aps.resources'].search(
            [('parent_ids', 'in', [parent.id])]
        )
        # Simulating the frontend exclusion of the current record
        siblings = all_children.filtered(lambda r: r.id != current.id)
        self.assertNotIn(current, siblings)
        self.assertEqual(len(siblings), 1)

    def test_root_resource_has_no_parent_in_breadcrumb(self):
        """A root resource (no parents) has a single-entry breadcrumb.
        The frontend should not show the dropdown caret in this case."""
        root = self.env['aps.resources'].create({'name': 'Root'})
        bc = root.display_name_breadcrumb
        # A single-entry breadcrumb means parentId is falsy in the widget
        self.assertEqual(len(bc), 1, "Root breadcrumb must have exactly one entry")
