from odoo.tests.common import TransactionCase

class TestAPSResource(TransactionCase):

    SEPARATOR = ' \U0001F892 '  # ' 🢒 '

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
        expected = 'Parent Resource' + self.SEPARATOR + 'Child Resource'
        self.assertEqual(child.display_name, expected)

    def test_compute_display_name_three_level_hierarchy(self):
        """Test that display_name correctly shows the full 3-level chain.

        Hierarchy: PH1-1P-202405 > Q7 > Q7a
        Expected: PH1-1P-202405 🢒 Q7 🢒 a
        (the 'Q7' prefix is stripped from 'Q7a' because Q7 is the direct parent)

        This is a regression test for the bug where the middle resource was
        dropped from the chain, producing 'PH1-1P-202405 🢒 Q7a' instead of
        'PH1-1P-202405 🢒 Q7 🢒 a'.
        """
        sep = self.SEPARATOR
        root = self.env['aps.resources'].create({'name': 'PH1-1P-202405'})
        mid = self.env['aps.resources'].create({
            'name': 'Q7',
            'parent_ids': [(6, 0, [root.id])],
            'primary_parent_id': root.id,
        })
        leaf = self.env['aps.resources'].create({
            'name': 'Q7a',
            'parent_ids': [(6, 0, [mid.id])],
            'primary_parent_id': mid.id,
        })
        self.assertEqual(mid.display_name, 'PH1-1P-202405' + sep + 'Q7')
        self.assertEqual(leaf.display_name, 'PH1-1P-202405' + sep + 'Q7' + sep + 'a')

    def test_sync_primary_parent_picks_most_specific(self):
        """Test that _sync_primary_parent picks the deepest parent, not parent_ids[0].

        When a resource has both an ancestor and a direct parent in parent_ids,
        the primary_parent_id should be set to the direct parent (most specific),
        not the ancestor (which has a lower database id / comes first in the M2M).
        """
        sep = self.SEPARATOR
        root = self.env['aps.resources'].create({'name': 'PH1-1P-202405'})
        mid = self.env['aps.resources'].create({
            'name': 'Q7',
            'parent_ids': [(6, 0, [root.id])],
            'primary_parent_id': root.id,
        })
        # Create leaf with both root AND mid in parent_ids but no explicit primary_parent_id
        # _sync_primary_parent should pick mid (more specific) not root (lower id)
        leaf = self.env['aps.resources'].create({
            'name': 'Q7a',
            'parent_ids': [(6, 0, [root.id, mid.id])],
        })
        # primary_parent_id should have been set to mid (more specific)
        self.assertEqual(leaf.primary_parent_id, mid)
        self.assertEqual(leaf.display_name, 'PH1-1P-202405' + sep + 'Q7' + sep + 'a')

    def test_compute_display_name_name_change_cascades(self):
        """Test that renaming a resource cascades to all descendants."""
        sep = self.SEPARATOR
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
        # Rename root and verify cascade to all descendants
        root.write({'name': 'NewRoot'})
        child.invalidate_recordset()
        grandchild.invalidate_recordset()
        self.assertEqual(child.display_name, 'NewRoot' + sep + 'Child')
        self.assertEqual(grandchild.display_name, 'NewRoot' + sep + 'Child' + sep + 'Grandchild')
