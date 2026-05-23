from . import aps_avatar
from . import aps_media
from . import aps_time_tracking
from . import ai_feedback_storage_mixin
from . import resources
from . import ai
from . import submissions
from . import aps_assign_students_wizard
from . import aps_dashboard
from . import core
from . import res_users
from . import op_program_level
from . import op_course
from . import op_subject
from . import op_faculty
from . import hr_employee
from . import hr_resume_line
from . import conditional_views
from . import op_student
from . import res_partner
from . import awards
from . import asc_timetable



# OpenEducat SIS has table names that do not follow highschool naming conventions.
# New names for OpenEucat Models
# op.department -> Department
# op.program.level -> Program Level (Undergraduate, Graduate)
# op.program -> Program (e.g., Primary, Seconary, IGCSE)
# op.course -> Academic Level (e.g., Year 7, Year 8, Year 9)
# op.student.course -> Student Course
# op.batch -> Batch (Year 1/2023-24, Year 2/2024-25)
# op.subject -> Subject (e.g., Mathematics, Science)
# op.subject.registration -> Subject Registration
# # op.classroom -> Classroom
# op.faculty -> Faculty
# op.student -> Student
# op.enrollment -> Enrollment
