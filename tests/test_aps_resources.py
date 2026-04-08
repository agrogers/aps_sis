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

    # --- Share URL tests ---

    def test_share_token_auto_generated_on_create(self):
        """A new resource must have a share_token set automatically."""
        resource = self.env['aps.resources'].create({'name': 'Shareable Resource'})
        self.assertTrue(resource.share_token, "share_token must be set on create")

    def test_share_token_is_unique(self):
        """Each new resource receives a distinct share_token."""
        r1 = self.env['aps.resources'].create({'name': 'Resource 1'})
        r2 = self.env['aps.resources'].create({'name': 'Resource 2'})
        self.assertNotEqual(r1.share_token, r2.share_token)

    def test_share_url_contains_token(self):
        """share_url includes the share_token as a path component."""
        resource = self.env['aps.resources'].create({'name': 'Shared'})
        self.assertIn(resource.share_token, resource.share_url)
        self.assertIn('/resource/share/', resource.share_url)

    def test_share_token_not_copied_on_duplicate(self):
        """Duplicating a resource must generate a new, distinct share_token."""
        original = self.env['aps.resources'].create({'name': 'Original'})
        copy = original.copy()
        self.assertTrue(copy.share_token, "Copied resource must have a share_token")
        self.assertNotEqual(original.share_token, copy.share_token)

    def test_action_generate_share_token_changes_token(self):
        """action_generate_share_token must replace the token with a new UUID."""
        resource = self.env['aps.resources'].create({'name': 'Regen Test'})
        old_token = resource.share_token
        resource.action_generate_share_token()
        self.assertNotEqual(resource.share_token, old_token)
        self.assertTrue(resource.share_token)

    def test_action_generate_share_token_updates_share_url(self):
        """After regenerating the token the share_url reflects the new token."""
        resource = self.env['aps.resources'].create({'name': 'URL Regen'})
        old_url = resource.share_url
        resource.action_generate_share_token()
        self.assertNotEqual(resource.share_url, old_url)
        self.assertIn(resource.share_token, resource.share_url)

    def test_share_token_lookup(self):
        """The controller domain [('share_token', '=', token)] resolves correctly."""
        resource = self.env['aps.resources'].create({'name': 'Lookup Test'})
        found = self.env['aps.resources'].sudo().search(
            [('share_token', '=', resource.share_token)], limit=1
        )
        self.assertEqual(found, resource)

    def test_invalid_share_token_returns_no_record(self):
        """An unknown token must not match any resource."""
        found = self.env['aps.resources'].sudo().search(
            [('share_token', '=', 'invalid-token-that-does-not-exist')], limit=1
        )
        self.assertFalse(found)

    # --- Display name edge-case tests ---

    def _make_chain(self, *names):
        """Helper: create a resource chain and return all records.

        ``_make_chain('A', 'B', 'C')`` creates three resources where
        B's primary parent is A and C's primary parent is B.
        Returns a list of records ``[A, B, C]``.
        """
        records = []
        parent = None
        for name in names:
            vals = {'name': name}
            if parent:
                vals['parent_ids'] = [(6, 0, [parent.id])]
                vals['primary_parent_id'] = parent.id
            rec = self.env['aps.resources'].create(vals)
            records.append(rec)
            parent = rec
        return records

    def test_display_name_no_false_overlap_ict_textbook(self):
        """ICT > Textbook must NOT strip the leading 'T' from Textbook.

        Regression: the overlap detector matched the last char of 'ICT'
        with the first char of 'Textbook', producing 'ICT 🢒 extbook'.
        """
        parent, child = self._make_chain('ICT', 'Textbook')
        self.assertEqual(child.display_name, 'ICT 🢒 Textbook')

    def test_display_name_three_level_chain(self):
        """A three-level chain should concatenate all ancestors."""
        gp, p, c = self._make_chain('Year 10', 'Math', 'Algebra')
        self.assertEqual(c.display_name, 'Year 10 🢒 Math 🢒 Algebra')

    def test_display_name_bracket_dedup(self):
        """Bracketed text matching the parent should be removed from child."""
        parent, child = self._make_chain('Year 10 Math', 'Equations (Year 10 Math)')
        self.assertIn('Equations', child.display_name)
        # The bracketed '(Year 10 Math)' should be stripped
        self.assertNotIn('(Year 10 Math)', child.display_name)

    def test_display_name_leading_word_dedup(self):
        """Leading words in the child that appear in the parent's last segment
        should be removed to avoid redundancy."""
        parent, child = self._make_chain('Ch 14: File Management', 'File Management Video Overview')
        # 'File Management' duplicates the parent tail — only 'Video Overview' should remain
        self.assertIn('Video Overview', child.display_name)
        # Should not have double "File Management"
        count = child.display_name.count('File Management')
        self.assertEqual(count, 1, f"'File Management' appears {count} times in '{child.display_name}'")

    def test_display_name_no_overlap_short_names(self):
        """Short parent names must not corrupt short child names."""
        cases = [
            ('A', 'B', 'A 🢒 B'),
            ('AB', 'CD', 'AB 🢒 CD'),
            ('IT', 'Tasks', 'IT 🢒 Tasks'),
        ]
        for pname, cname, expected in cases:
            parent, child = self._make_chain(pname, cname)
            self.assertEqual(
                child.display_name, expected,
                f"Chain '{pname}' > '{cname}' gave '{child.display_name}', expected '{expected}'",
            )

    def test_display_name_identical_parent_child(self):
        """When parent and child have the same name, the child display_name
        should still include the parent (no empty segment)."""
        parent, child = self._make_chain('Topic A', 'Topic A')
        # The overlap logic should collapse but the parent must still appear
        self.assertTrue(child.display_name.startswith('Topic A'))

    def test_display_name_real_overlap(self):
        """A genuine word-boundary overlap should be collapsed.

        E.g. parent 'Year 10 Intro' and child 'Intro to Functions' overlap on
        the full word 'Intro'.
        """
        parent, child = self._make_chain('Year 10 Intro', 'Intro to Functions')
        self.assertIn('Year 10 Intro', child.display_name)
        self.assertIn('to Functions', child.display_name)
        self.assertEqual(child.display_name.count('Intro'), 1)

    def test_display_name_no_partial_word_overlap(self):
        """Mid-word overlaps must NOT be collapsed.

        'Alge' at end of parent overlaps start of 'Algebra' but breaks
        mid-word — both segments should appear in full.
        """
        parent, child = self._make_chain('Intro to Alge', 'Algebra Basics')
        self.assertEqual(child.display_name, 'Intro to Alge 🢒 Algebra Basics')

    # --- Custom name submission resolution tests ---

    def test_resolve_names_no_custom_name(self):
        """Without custom names, _resolve_submission_names uses default names
        with the standard overlap-removal algorithm."""
        exam, q1, q1a = self._make_chain('Exam1', 'Q1', 'Q1a')
        resources = exam | q1 | q1a
        name_map = resources._resolve_submission_names(exam)
        self.assertEqual(name_map[exam.id], 'Exam1')
        self.assertIn('Q1', name_map[q1.id])
        self.assertIn('a', name_map[q1a.id])

    def test_resolve_names_custom_name_on_direct_child(self):
        """A custom name on a parent→child link replaces the child's name
        in the submission name."""
        exam2 = self.env['aps.resources'].create({'name': 'Exam2'})
        q5 = self.env['aps.resources'].create({
            'name': 'Q5',
            'parent_ids': [(6, 0, [exam2.id])],
            'primary_parent_id': exam2.id,
        })
        # Set custom name: under Exam2, Q5 is known as Q1
        self.env['aps.resource.custom.name'].create({
            'parent_resource_id': exam2.id,
            'resource_id': q5.id,
            'custom_name': 'Q1',
        })
        resources = exam2 | q5
        name_map = resources._resolve_submission_names(exam2)
        self.assertEqual(name_map[exam2.id], 'Exam2')
        self.assertEqual(name_map[q5.id], 'Exam2 🢒 Q1')

    def test_resolve_names_custom_name_cascades_to_grandchild(self):
        """A custom name on Exam2→Q5 should cascade so Q5a becomes Q1a
        (prefix substitution + overlap-removal).

        Tree: Exam2 > Q5 (custom=Q1) > Q5a → expects Exam2 > Q1 > Q1a
        """
        exam2 = self.env['aps.resources'].create({'name': 'Exam2'})
        q5 = self.env['aps.resources'].create({
            'name': 'Q5',
            'parent_ids': [(6, 0, [exam2.id])],
            'primary_parent_id': exam2.id,
        })
        q5a = self.env['aps.resources'].create({
            'name': 'Q5a',
            'parent_ids': [(6, 0, [q5.id])],
            'primary_parent_id': q5.id,
        })
        self.env['aps.resource.custom.name'].create({
            'parent_resource_id': exam2.id,
            'resource_id': q5.id,
            'custom_name': 'Q1',
        })
        resources = exam2 | q5 | q5a
        name_map = resources._resolve_submission_names(exam2)
        self.assertEqual(name_map[exam2.id], 'Exam2')
        self.assertEqual(name_map[q5.id], 'Exam2 🢒 Q1')
        # Q5a → prefix Q5 substituted to Q1 → Q1a, then overlap removal with "Exam2 🢒 Q1"
        self.assertIn('Q1', name_map[q5a.id],
                       "Grandchild must reference Q1 (the cascaded custom name)")
        self.assertNotIn('Q5', name_map[q5a.id],
                          "Original name Q5 must not appear in grandchild submission name")

    def test_resolve_names_deep_cascade(self):
        """Custom name cascades three levels deep: Q5 > Q5a > Q5a.i

        With custom name Q1 on Q5:
        - Q5 → Q1
        - Q5a → Q1a (prefix substitution)
        - Q5a.i → Q1a.i (prefix substitution)
        """
        exam2 = self.env['aps.resources'].create({'name': 'Exam2'})
        q5 = self.env['aps.resources'].create({
            'name': 'Q5',
            'parent_ids': [(6, 0, [exam2.id])],
            'primary_parent_id': exam2.id,
        })
        q5a = self.env['aps.resources'].create({
            'name': 'Q5a',
            'parent_ids': [(6, 0, [q5.id])],
            'primary_parent_id': q5.id,
        })
        q5ai = self.env['aps.resources'].create({
            'name': 'Q5a.i',
            'parent_ids': [(6, 0, [q5a.id])],
            'primary_parent_id': q5a.id,
        })
        self.env['aps.resource.custom.name'].create({
            'parent_resource_id': exam2.id,
            'resource_id': q5.id,
            'custom_name': 'Q1',
        })
        resources = exam2 | q5 | q5a | q5ai
        name_map = resources._resolve_submission_names(exam2)
        # Verify no descendant references "Q5"
        for res in [q5, q5a, q5ai]:
            self.assertNotIn('Q5', name_map[res.id],
                             f"Resource '{res.name}': found Q5 in '{name_map[res.id]}' — "
                             f"custom name Q1 should have cascaded")
        # Verify the custom name prefix appears throughout
        self.assertIn('Q1', name_map[q5.id])
        self.assertIn('Q1', name_map[q5a.id])
        self.assertIn('Q1', name_map[q5ai.id])

    def test_resolve_names_custom_top_level_name(self):
        """Passing a custom top_level_name overrides the top-level resource's
        display name in all generated submission names."""
        exam, q1 = self._make_chain('Exam1', 'Q1')
        resources = exam | q1
        name_map = resources._resolve_submission_names(exam, top_level_name='Final Exam')
        self.assertEqual(name_map[exam.id], 'Final Exam')
        self.assertIn('Final Exam', name_map[q1.id])

    def test_resolve_names_no_custom_uses_default(self):
        """Without any custom names, children use their original names
        (same as display_name overlap-removal logic)."""
        parent = self.env['aps.resources'].create({'name': 'Math'})
        child = self.env['aps.resources'].create({
            'name': 'Algebra',
            'parent_ids': [(6, 0, [parent.id])],
            'primary_parent_id': parent.id,
        })
        resources = parent | child
        name_map = resources._resolve_submission_names(parent)
        self.assertEqual(name_map[parent.id], 'Math')
        self.assertEqual(name_map[child.id], 'Math 🢒 Algebra')

    def test_resolve_names_out_of_order_resources(self):
        """Resources may not be in tree order. The algorithm must still
        correctly resolve names regardless of recordset iteration order."""
        exam = self.env['aps.resources'].create({'name': 'Exam'})
        q1 = self.env['aps.resources'].create({
            'name': 'Q1',
            'parent_ids': [(6, 0, [exam.id])],
            'primary_parent_id': exam.id,
        })
        q1a = self.env['aps.resources'].create({
            'name': 'Q1a',
            'parent_ids': [(6, 0, [q1.id])],
            'primary_parent_id': q1.id,
        })
        # Deliberately pass in reverse order
        resources = q1a | q1 | exam
        name_map = resources._resolve_submission_names(exam)
        self.assertEqual(name_map[exam.id], 'Exam')
        self.assertIn('Q1', name_map[q1.id])
        self.assertIn('a', name_map[q1a.id])

