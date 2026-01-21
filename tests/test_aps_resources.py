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