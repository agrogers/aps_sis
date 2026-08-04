"""Rename aps.student.class.home_class_id → class_id.

The old field name was misleading — despite being called "home_class_id",
it was a generic reference to the class being enrolled in (any class,
not the student's homeroom). The actual home class is computed on
aps.student.home_class_id instead.
"""


def migrate(cr, version):
    cr.execute('ALTER TABLE aps_student_class RENAME COLUMN home_class_id TO class_id')