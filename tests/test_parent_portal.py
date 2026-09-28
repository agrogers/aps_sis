from odoo import fields
from odoo.tests.common import TransactionCase

from odoo.addons.aps_sis.controllers.portal import APSPortal


class TestParentPortal(TransactionCase):

    def setUp(self):
        super().setUp()
        self.portal = APSPortal()
        self.parent = self.env['res.partner'].create({'name': 'Portal Parent'})
        self.child_partner = self.env['res.partner'].create({
            'name': 'Portal Child',
            'is_student': True,
        })
        self.outside_partner = self.env['res.partner'].create({
            'name': 'Unlinked Child',
            'is_student': True,
        })
        self.child = self.env['aps.student'].create({'partner_id': self.child_partner.id})
        self.outside_child = self.env['aps.student'].create({'partner_id': self.outside_partner.id})
        relation_type = self.env['res.partner.relation.type'].create({
            'name': 'is parent of',
            'name_inverse': 'is child of',
        })
        self.env['res.partner.relation'].create({
            'left_partner_id': self.parent.id,
            'right_partner_id': self.child_partner.id,
            'type_id': relation_type.id,
        })

    def test_parent_can_only_find_linked_children(self):
        children = self.portal._get_parent_students(self.parent, self.env)

        self.assertEqual(children.ids, [self.child.id])
        self.assertNotIn(self.outside_child.id, children.ids)

    def test_progress_summary_and_subject_chart_are_student_scoped(self):
        category = self.env['aps.subject.category'].create({'name': 'Portal Category'})
        subject = self.env['aps.subject'].create({
            'name': 'Portal Subject',
            'category_id': category.id,
        })
        resource = self.env['aps.resources'].create({
            'name': 'Completed Work',
            'subjects': [(6, 0, [subject.id])],
        })
        completed_task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': self.child_partner.id,
        })
        self.env['aps.resource.submission'].create({
            'task_id': completed_task.id,
            'state': 'complete',
            'score': 8,
            'out_of_marks': 10,
            'date_assigned': fields.Date.today(),
        })
        overdue_resource = self.env['aps.resources'].create({'name': 'Overdue Work'})
        overdue_task = self.env['aps.resource.task'].create({
            'resource_id': overdue_resource.id,
            'student_id': self.child_partner.id,
        })
        self.env['aps.resource.submission'].create({
            'task_id': overdue_task.id,
            'state': 'assigned',
            'date_assigned': fields.Date.add(fields.Date.today(), days=-2),
            'date_due': fields.Date.add(fields.Date.today(), days=-1),
        })
        outside_resource = self.env['aps.resources'].create({'name': 'Outside Work'})
        outside_task = self.env['aps.resource.task'].create({
            'resource_id': outside_resource.id,
            'student_id': self.outside_partner.id,
        })
        self.env['aps.resource.submission'].create({
            'task_id': outside_task.id,
            'state': 'complete',
            'score': 10,
            'out_of_marks': 10,
            'date_assigned': fields.Date.today(),
        })
        self.env['aps.resource.submission'].search([])._compute_submission_active()

        summary = self.portal._get_child_progress(self.child, self.env)

        self.assertEqual(summary['total_tasks'], 2)
        self.assertEqual(summary['completed'], 1)
        self.assertEqual(summary['overdue'], 1)
        self.assertEqual(summary['average_score'], 80)
        self.assertEqual(summary['subject_chart'], [{
            'name': subject.display_name,
            'average': 80,
            'count': 1,
        }])
