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
    # ------------------------------------------------------------------ #
    # Hierarchy level tests
    # ------------------------------------------------------------------ #

    def test_level_root_resource(self):
        """Root resources (no parents) must have level 0."""
        root = self.env['aps.resources'].create({'name': 'Root'})
        self.assertEqual(root.level, 0)

    def test_level_child_resource(self):
        """Direct children of a root resource must have level 1."""
        root = self.env['aps.resources'].create({'name': 'Root'})
        child = self.env['aps.resources'].create({
            'name': 'Child',
            'parent_ids': [(6, 0, [root.id])],
            'primary_parent_id': root.id,
        })
        self.assertEqual(child.level, 1)

    def test_level_grandchild_resource(self):
        """Grandchildren must have level 2."""
        root = self.env['aps.resources'].create({'name': 'Root'})
        child = self.env['aps.resources'].create({
            'name': 'Child',
            'parent_ids': [(6, 0, [root.id])],
            'primary_parent_id': root.id,
        })
        grandchild = self.env['aps.resources'].create({
            'name': 'Grandchild',
            'parent_ids': [(6, 0, [child.id])],
            'primary_parent_id': child.id,
        })
        self.assertEqual(grandchild.level, 2)

    def test_level_multiple_parents_uses_minimum(self):
        """When a resource has multiple parents at different levels the minimum is used."""
        root = self.env['aps.resources'].create({'name': 'Root'})
        child = self.env['aps.resources'].create({
            'name': 'Child',
            'parent_ids': [(6, 0, [root.id])],
            'primary_parent_id': root.id,
        })
        # shared has two parents: root (level 0) and child (level 1)
        # expected level = min(0, 1) + 1 = 1
        shared = self.env['aps.resources'].create({
            'name': 'Shared',
            'parent_ids': [(6, 0, [root.id, child.id])],
            'primary_parent_id': root.id,
        })
        self.assertEqual(shared.level, 1)

    def test_level_updates_when_parent_removed(self):
        """Removing a parent should trigger level recomputation."""
        root = self.env['aps.resources'].create({'name': 'Root'})
        child = self.env['aps.resources'].create({
            'name': 'Child',
            'parent_ids': [(6, 0, [root.id])],
            'primary_parent_id': root.id,
        })
        grandchild = self.env['aps.resources'].create({
            'name': 'Grandchild',
            'parent_ids': [(6, 0, [child.id])],
            'primary_parent_id': child.id,
        })
        self.assertEqual(grandchild.level, 2)

        # Remove child's parent so child becomes root -> grandchild should become level 1
        child.write({'parent_ids': [(5,)], 'primary_parent_id': False})
        # The stored computed field should be automatically re-triggered by the ORM
        # via the parent_ids.level dependency chain.
        self.assertEqual(grandchild.level, 1)
