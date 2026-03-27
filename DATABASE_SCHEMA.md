# APS SIS — Database Schema Reference

> **Module:** `aps_sis` | **Odoo Version:** 18.0 | **Last Updated:** 2026-03-27

This document describes every database model defined or extended by the `aps_sis` module. It is intended as a reference for developers and AI agents working on this codebase.

---

## Table of Contents

- [1. Core SIS Models](#1-core-sis-models)
  - [1.1 aps.academic.year](#11-apsacademicyear)
  - [1.2 aps.academic.term](#12-apsacademicterm)
  - [1.3 aps.level](#13-apslevel)
  - [1.4 aps.subject.category.tag](#14-apssubjectcategorytag)
  - [1.5 aps.subject.category](#15-apssubjectcategory)
  - [1.6 aps.subject](#16-apssubject)
  - [1.7 aps.class](#17-apsclass)
  - [1.8 aps.student](#18-apsstudent)
  - [1.9 aps.student.class](#19-apsstudentclass)
  - [1.10 aps.teacher](#110-apsteacher)
- [2. Resource & Task Models](#2-resource--task-models)
  - [2.1 aps.resources](#21-apsresources)
  - [2.2 aps.resource.types](#22-apsresourcetypes)
  - [2.3 aps.resource.tags](#23-apsresourcetags)
  - [2.4 aps.resource.custom.name](#24-apsresourcecustomname)
  - [2.5 aps.resource.task](#25-apsresourcetask)
  - [2.6 aps.resource.submission](#26-apsresourcesubmission)
- [3. Time Tracking](#3-time-tracking)
  - [3.1 aps.time.tracking](#31-apstimetracking)
- [4. Avatar System](#4-avatar-system)
  - [4.1 aps.avatar.category](#41-apsavatarcategory)
  - [4.2 aps.avatar](#42-apsavatar)
- [5. Media Shop System](#5-media-shop-system)
  - [5.1 aps.media.type](#51-apsmediatype)
  - [5.2 aps.media.collection](#52-apsmediacollection)
  - [5.3 aps.media.category](#53-apsmediacategory)
  - [5.4 aps.media](#54-apsmedia)
  - [5.5 aps.user.media](#55-apsusermedia)
  - [5.6 aps.user.media.settings](#56-apsusermediasettings)
- [6. Dashboard](#6-dashboard)
  - [6.1 aps.dashboard (TransientModel)](#61-apsdashboard-transientmodel)
- [7. Inherited / Extended Models](#7-inherited--extended-models)
  - [7.1 res.partner (extensions)](#71-respartner-extensions)
  - [7.2 res.users (extensions)](#72-resusers-extensions)
  - [7.3 hr.employee (extensions)](#73-hremployee-extensions)
  - [7.4 op.student (extensions)](#74-opstudent-extensions)
  - [7.5 op.faculty (extensions)](#75-opfaculty-extensions)
  - [7.6 op.subject (extensions)](#76-opsubject-extensions)
  - [7.7 op.course (extensions)](#77-opcourse-extensions)
  - [7.8 op.program.level (extensions)](#78-opprogramlevel-extensions)
- [8. Wizard / Transient Models](#8-wizard--transient-models)
  - [8.1 aps.student.class.bulk.wizard](#81-apsstudentclassbulkwizard)
  - [8.2 aps.assign.students.wizard](#82-apsassignstudentswizard)
  - [8.3 aps.assign.students.wizard.line](#83-apsassignstudentswizardline)
  - [8.4 aps.submission.mass.update.wizard](#84-apssubmissionmassupdatewizard)
  - [8.5 aps.resource.mass.update.wizard](#85-apsresourcemassupdatewizard)
  - [8.6 aps.submission.report.wizard](#86-apssubmissionreportwizard)
- [9. Relationship Diagram (Conceptual)](#9-relationship-diagram-conceptual)
- [10. Security Groups](#10-security-groups)
- [11. Key Behaviours & Sync Logic](#11-key-behaviours--sync-logic)
- [12. Partner Relations (partner_multi_relation)](#12-partner-relations-partner_multi_relation)
  - [12.1 res.partner.relation](#121-respartnerrelation)
  - [12.2 res.partner.relation.all (SQL View)](#122-respartnerrelationall-sql-view)
  - [12.3 res.partner.relation.type](#123-respartnerrelationtype)
  - [12.4 res.partner.relation.type.selection (SQL View)](#124-respartnerrelationtypeselection-sql-view)

---

## 1. Core SIS Models

### 1.1 aps.academic.year

**File:** `models/core/aps_academic_year.py`
**Description:** Academic Year
**Order:** `start_date desc`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | translate=True, unique |
| `short_name` | Char | | size=20 |
| `start_date` | Date | ✅ | |
| `end_date` | Date | ✅ | |
| `is_current` | Boolean | | default=False |
| `active` | Boolean | | default=True |
| `display_name` | Char | | computed (short_name or name), stored |

**SQL Constraints:** `unique(name)`
**Validation:** end_date must be after start_date.
**Key Methods:** `action_set_current()` — sets this year as current, clears others.

---

### 1.2 aps.academic.term

**File:** `models/core/aps_academic_term.py`
**Description:** Academic Term
**Order:** `start_date desc`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | translate=True |
| `short_name` | Char | | size=20 |
| `academic_year_id` | Many2one → `aps.academic.year` | ✅ | ondelete=cascade |
| `start_date` | Date | ✅ | |
| `end_date` | Date | ✅ | |
| `active` | Boolean | | default=True |
| `display_name` | Char | | computed (short_name or name), stored |

**Validation:** end_date must be after start_date.

---

### 1.3 aps.level

**File:** `models/core/aps_level.py`
**Description:** Academic Level (e.g. Year 1, Year 2)
**Order:** `sequence, name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | unique |
| `short_name` | Char | | size=20 |
| `sequence` | Integer | | default=10 |
| `active` | Boolean | | default=True |
| `description` | Text | | |
| `tag_ids` | Many2many → `res.partner.category` | | relation=`aps_level_partner_category_rel` |
| `display_name` | Char | | computed (short_name or name), stored |

**SQL Constraints:** `unique(name)`
**Purpose of `tag_ids`:** Maps partner tags to levels. When a partner is marked as a student, their `category_id` tags are compared against level `tag_ids` to auto-assign the student's `level_id`.

---

### 1.4 aps.subject.category.tag

**File:** `models/core/aps_subject_category_tag.py`
**Description:** Subject Category Tag
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | unique |

**SQL Constraints:** `unique(name)`
**Module-level constant:** `_HOME_CLASS_TAG_NAMES = {'Home Class', 'Pastoral Care Subject'}`
**Key Behaviour:** On `write()`, if `name` changes, cascades a home-class recompute for all students enrolled in classes whose subject category uses this tag.

---

### 1.5 aps.subject.category

**File:** `models/core/aps_subject_category.py`
**Description:** Subject Category
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | translate=True, unique |
| `code` | Char | | |
| `description` | Text | | |
| `color_rgb` | Char | | CSS color string |
| `icon` | Image | | max 128×128 |
| `active` | Boolean | | default=True |
| `tag_ids` | Many2many → `aps.subject.category.tag` | | relation=`aps_subject_category_tag_rel` |

**SQL Constraints:** `unique(name)`
**Key Behaviour:** On `write()`, if `tag_ids` changes, calls `_recompute_students_home_class()` which traverses subjects → classes → enrollments → students to update their `home_class_id`.

---

### 1.6 aps.subject

**File:** `models/core/aps_subject.py`
**Description:** Subject
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | translate=True, unique |
| `code` | Char | | |
| `category_id` | Many2one → `aps.subject.category` | | ondelete=set null |
| `level_id` | Many2one → `aps.level` | | ondelete=set null |
| `icon` | Image | | max 128×128 |
| `active` | Boolean | | default=True |

**SQL Constraints:** `unique(name)`
**Onchange:** When `category_id` is set, copies the category icon if the subject has no icon.

---

### 1.7 aps.class

**File:** `models/core/aps_class.py`
**Description:** Class (a section of a subject in an academic year)
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `identifier` | Char | | size=10, e.g. "A", "B", "1" |
| `subject_id` | Many2one → `aps.subject` | | ondelete=restrict |
| `code` | Char | | computed+stored, readonly=False |
| `name` | Char | ✅ | computed+stored, readonly=False |
| `academic_year_id` | Many2one → `aps.academic.year` | | ondelete=set null, defaults to current year |
| `teacher_ids` | Many2many → `res.partner` | | relation=`aps_class_teacher_rel` |
| `assistant_teacher_ids` | Many2many → `res.partner` | | relation=`aps_class_assistant_teacher_rel` |
| `active` | Boolean | | default=True |
| `enrollment_ids` | One2many → `aps.student.class` | | inverse=`home_class_id` |
| `display_name` | Char | | computed (code or name), stored |

**Computed `code`/`name`:** Auto-generated from `subject_id.code/name` + `identifier`. Editable to allow manual override.

---

### 1.8 aps.student

**File:** `models/core/aps_student.py`
**Description:** Student
**Order:** `partner_id`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `partner_id` | Many2one → `res.partner` | ✅ | ondelete=cascade, unique |
| `roll` | Char | | size=20 |
| `level_id` | Many2one → `aps.level` | | ondelete=set null |
| `home_class_id` | Many2one → `aps.class` | | ondelete=set null, auto-computed (event-driven) |
| `active` | Boolean | | default=True |
| `enrollment_ids` | One2many → `aps.student.class` | | inverse=`student_id` |
| `display_name` | Char | | computed: "Name (Roll)" |

**SQL Constraints:** `unique(partner_id)`
**Bidirectional Sync:** create/write/unlink sync `is_student` flag on the linked `res.partner` (uses `skip_student_sync` context flag to prevent infinite loops).
**`_recompute_home_class()`:** Iterates enrolled enrollments; finds the first class whose subject category has a tag named "Home Class" or "Pastoral Care Subject" and sets that as `home_class_id`.
**`action_populate_from_contacts()`:** Batch creates/reactivates student records from all partners with `is_student=True`, syncing level from partner tags.

---

### 1.9 aps.student.class

**File:** `models/core/aps_student_class.py`
**Description:** Student Class Enrollment (junction between student and class)
**Order:** `start_date desc`
**Rec Name:** `student_id`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `student_id` | Many2one → `aps.student` | ✅ | ondelete=cascade |
| `home_class_id` | Many2one → `aps.class` | ✅ | ondelete=cascade |
| `start_date` | Date | | defaults to current academic year start |
| `end_date` | Date | | defaults to current academic year end |
| `active` | Boolean | | default=True |
| `state` | Selection | ✅ | `enrolled`/`withdrawn`/`finished`, default=`enrolled`, tracking=True |
| `display_name` | Char | | computed: "Student / Class" |

**SQL Constraints:** `unique(student_id, home_class_id)`
**Validation:** end_date must be on or after start_date.
**Key Methods:**
- `action_withdraw()` — sets state=withdrawn, end_date=today.
- create/write/unlink all trigger `student._recompute_home_class()`.

---

### 1.10 aps.teacher

**File:** `models/core/aps_teacher.py`
**Description:** Teacher
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `partner_id` | Many2one → `res.partner` | ✅ | ondelete=cascade, unique, indexed |
| `tutor_code` | Char | | size=20 |
| `active` | Boolean | | default=True |
| `name` | Char | | related=`partner_id.name`, stored |
| `email` | Char | | related=`partner_id.email` |
| `phone` | Char | | related=`partner_id.phone` |
| `image_128` | Image | | related=`partner_id.image_128` |
| `display_name` | Char | | computed: "[tutor_code] Name" |

**SQL Constraints:** `unique(partner_id)`
**Bidirectional Sync:** create/write/unlink sync `is_teacher` flag on the linked `res.partner` (uses `skip_teacher_sync` context flag).
**`action_populate_from_contacts()`:** Batch creates/reactivates teacher records from all partners with `is_teacher=True`.

---

## 2. Resource & Task Models

### 2.1 aps.resources

**File:** `models/aps_resources/model.py` (split into package: `model.py`, `computed.py`, `custom_name.py`, `html_parser.py`, `overrides.py`, `parent_sync.py`, `actions.py`)
**Description:** APEX Resources
**Inherits:** `mail.thread`, `mail.activity.mixin`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `sequence` | Integer | | default=10 |
| `name` | Char | | tracking=True |
| `display_name` | Char | | computed, stored |
| `description` | Text | | tracking=True |
| `has_question` | Selection | ✅ | `no`/`yes`/`use_parent`, default=`no` |
| `question` | Html | | |
| `has_answer` | Selection | ✅ | `no`/`yes`/`yes_notes`/`use_parent`, default=`no` |
| `answer` | Html | | model answer |
| `has_default_answer` | Boolean | | |
| `default_answer` | Html | | template answer |
| `has_notes` | Selection | ✅ | `no`/`yes`/`use_parent`, default=`no` |
| `notes` | Html | | |
| `lesson_plan` | Html | | |
| `has_lesson_plan` | Boolean | | stored |
| `has_child_resources` | Selection | ✅ | `no`/`yes`, default=`no` |
| `has_supporting_resources` | Selection | ✅ | `no`/`yes`, default=`no` |
| `thumbnail` | Binary | | |
| `type_id` | Many2one → `aps.resource.types` | | ondelete=set null, tracking=True |
| `type_icon` | Image | | computed from type_id, stored |
| `type_color` | Char | | related=`type_id.color` |
| `url` | Char | | tracking=True |
| `category` | Selection | | `mandatory`/`optional`/`information`, default=`optional` |
| `marks` | Float | | digits=(16,1), max marks for resource |
| `score_contributes_to_parent` | Boolean | | default=True |
| `subjects` | Many2many → `op.subject` | | |
| `tag_ids` | Many2many → `aps.resource.tags` | | |
| `task_ids` | One2many → `aps.resource.task` | | inverse=`resource_id` |
| `parent_ids` | Many2many → `aps.resources` | | relation=`aps_resources_rel` (self-referential) |
| `child_ids` | Many2many → `aps.resources` | | relation=`aps_resources_rel` (inverse) |
| `supporting_parent_ids` | Many2many → `aps.resources` | | relation=`aps_supporting_resources_rel` |
| `supporting_resource_ids` | Many2many → `aps.resources` | | relation=`aps_supporting_resources_rel` (inverse) |
| `primary_parent_id` | Many2one → `aps.resources` | | for display name generation |
| `custom_name_ids` | One2many → `aps.resource.custom.name` | | inverse=`resource_id` |
| `parent_custom_name_data` | Json | | computed, stored |
| `allow_subject_editing` | Boolean | | default=False |
| `points_scale` | Integer | | default=1 |
| `share_token` | Char | | unique UUID, indexed, readonly |
| `share_url` | Char | | computed |
| `is_recently_viewed` | Boolean | | computed with search method |
| `display_name_breadcrumb` | Json | | computed, stored — ancestor chain |
| **Auto-Assign Fields** | | | |
| `auto_assign` | Boolean | | default=False |
| `auto_assign_date` | Date | | next run date |
| `auto_assign_end_date` | Date | | optional stop date |
| `auto_assign_frequency` | Integer | | default=7, days between runs |
| `auto_assign_time` | Float | | decimal time (14.5 = 14:30) |
| `auto_assign_all_students` | Boolean | | default=True |
| `auto_assign_student_ids` | Many2many → `res.partner` | | relation=`aps_resources_auto_assign_students_rel` |
| `auto_assign_notify_student` | Boolean | | default=True |
| `auto_assign_custom_name` | Char | | name override for auto-assigned submissions |
| `auto_assign_log` | Text | | readonly, audit trail |
| **Dashboard Computed** | | | |
| `total_submissions` | Integer | | computed (not stored) |
| `completed_submissions` | Integer | | computed (not stored) |
| `overdue_tasks` | Integer | | computed (not stored) |
| `child_count` | Integer | | computed |
| `has_multiple_parents` | Boolean | | computed |
| `supporting_resource_count` | Integer | | computed |
| `recent_submission_count` | Integer | | computed |
| `supporting_resources_buttons` | Json | | computed — widget data |
| `subject_icons` | Image | | computed, stored |

---

### 2.2 aps.resource.types

**File:** `models/aps_resource_types.py`
**Description:** APEX Resource Type
**Order:** `sequence, name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `sequence` | Integer | | default=10 |
| `name` | Char | ✅ | |
| `description` | Text | | |
| `icon` | Image | | max 64×64 |
| `color` | Char | | CSS color |
| `resource_ids` | One2many → `aps.resources` | | inverse=`type_id` |
| `url_keywords` | Char | | comma-separated for auto-type-matching |

---

### 2.3 aps.resource.tags

**File:** `models/aps_resource_tags.py`
**Description:** APEX Resource Tags

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |
| `color` | Integer | | Odoo color index |

---

### 2.4 aps.resource.custom.name

**File:** `models/aps_resources/custom_name.py`
**Description:** Custom Resource Name for Parent/Child
**Rec Name:** `custom_name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `parent_resource_id` | Many2one → `aps.resources` | ✅ | ondelete=cascade |
| `resource_id` | Many2one → `aps.resources` | ✅ | ondelete=cascade |
| `custom_name` | Char | ✅ | |

**SQL Constraints:** `unique(parent_resource_id, resource_id)`

---

### 2.5 aps.resource.task

**File:** `models/aps_resource_task.py`
**Description:** APEX Task (assignment of a resource to a student)

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `resource_id` | Many2one → `aps.resources` | ✅ | |
| `student_id` | Many2one → `res.partner` | ✅ | domain: `is_student=True` |
| `subject_ids` | Many2many | | related=`resource_id.subjects` |
| `state` | Selection | | `created`/`assigned`/`reassigned`/`due`/`early`/`on-time`/`submitted`/`overdue`/`complete`/`late`, default=`created` |
| `date_assigned` | Date | | computed from submissions, stored |
| `date_due` | Date | | computed from submissions, stored |
| `submission_count` | Integer | | computed, stored |
| `last_result` | Float | | computed, stored |
| `avg_result` | Float | | computed, stored |
| `weighted_result` | Float | | computed, stored (last 10 submissions, recency-weighted) |
| `best_result` | Float | | computed, stored |
| `latest_submission_text` | Char | | computed, stored (JSON pill data) |
| `submission_ids` | One2many → `aps.resource.submission` | | inverse=`task_id` |
| `type_icon` | Image | | computed from resource type, stored |
| `is_current_user_faculty` | Boolean | | computed |
| `display_name` | Char | | computed: "Student - Resource", stored |

**SQL Constraints:** `unique(resource_id, student_id)`

---

### 2.6 aps.resource.submission

**File:** `models/aps_resource_submission.py`
**Description:** APEX Submission
**Inherits:** `mail.thread`, `mail.activity.mixin`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `task_id` | Many2one → `aps.resource.task` | ✅ | |
| `resource_id` | Many2one → `aps.resources` | | related=`task_id.resource_id` |
| `student_id` | Many2one → `res.partner` | | related=`task_id.student_id` |
| `subjects` | Many2many → `op.subject` | | |
| `assigned_by` | Many2one → `op.faculty` | | default: current faculty |
| `submission_name` | Char | | |
| `submission_label` | Char | | grouping label |
| `submission_order` | Integer | | |
| `state` | Selection | ✅ | `assigned`/`submitted`/`complete`, default=`assigned`, tracking=True |
| `date_assigned` | Date | | default=today |
| `time_assigned` | Float | | decimal time |
| `date_submitted` | Date | | tracking=True |
| `date_completed` | Date | | tracking=True |
| `date_due` | Date | | tracking=True |
| `score` | Float | | digits=(16,2), default=-0.01 (sentinel), tracking=True |
| `out_of_marks` | Float | | digits=(16,1), stored, tracking=True |
| `result_percent` | Integer | | computed, stored |
| `due_status` | Selection | | `late`/`on-time`/`early`, computed, stored |
| `days_till_due` | Integer | | computed, stored |
| `actual_duration` | Float | | digits=(16,1), hours |
| `feedback` | Html | | |
| `has_feedback` | Boolean | | computed, stored |
| `answer` | Html | | student's answer |
| `has_answer` | Selection | | related=`resource_id.has_answer` |
| `has_question` | Selection | | `no`/`yes`/`use_parent` |
| `question` | Html | | |
| `model_answer` | Html | | related=`resource_id.answer` |
| `reviewed_by` | Many2many → `op.faculty` | | relation=`aps_submission_reviewed_by_rel` |
| `review_requested_by` | Many2many → `op.faculty` | | relation=`aps_submission_review_request_rel` |
| `is_current_user_faculty` | Boolean | | computed |
| `is_current_user_reviewed` | Boolean | | computed |
| `supporting_resources_buttons` | Json | | related=`resource_id.supporting_resources_buttons` |
| `resource_notes` | Html | | related=`resource_id.notes` |
| `resource_has_notes` | Selection | | related=`resource_id.has_notes` |
| `type_icon` | Image | | computed, stored |
| `subject_icons` | Image | | computed, stored |
| `submission_active` | Boolean | | computed, stored (visible to student after assigned date) |
| `active_datetime` | Datetime | | computed, stored |
| `notified_active` | Boolean | | default varies by group |
| `notification_state` | Selection | ✅ | `not_sent`/`sent`/`posted`/`failed`/`skipped`, default=`skipped` |
| `allow_subject_editing` | Boolean | | default=False |
| `points_scale` | Integer | | default=0 |
| `points` | Integer | | computed, stored |
| `auto_score` | Boolean | | default=True, tracking=True |
| `default_notebook_page_per_user` | Json | | per-user UI state |
| `model_answer_is_notes` | Boolean | | computed |

---

## 3. Time Tracking

### 3.1 aps.time.tracking

**File:** `models/aps_time_tracking.py`
**Description:** Time Tracking Entry
**Order:** `start_time desc`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `partner_id` | Many2one → `res.partner` | | domain: `is_student=True`, default=current user partner |
| `subject_id` | Many2one → `op.subject` | ✅ | indexed |
| `date` | Date | | computed from start_time, stored, readonly=False, indexed |
| `start_time` | Datetime | | |
| `stop_time` | Datetime | | |
| `pause_minutes` | Float | | default=0 |
| `total_minutes` | Float | | computed, stored, readonly=False |
| `notes` | Text | | |
| `is_outside_school_hours` | Boolean | | computed, stored, readonly=False |
| `subject_icon` | Image | | related=`subject_id.icon` |
| `is_current_user_teacher` | Boolean | | computed |
| `display_name` | Char | | computed: "Person - Subject - Date" |

**School hours:** 08:00–15:30 weekdays. Weekends always outside. Auto-detects with timezone conversion.
**Validation:** stop_time ≥ start_time, max 24-hour span.

---

## 4. Avatar System

### 4.1 aps.avatar.category

**File:** `models/aps_avatar.py`
**Description:** Avatar Category
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |
| `avatar_count` | Integer | | computed |

---

### 4.2 aps.avatar

**File:** `models/aps_avatar.py`
**Description:** Avatar
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |
| `image` | Image | | max 512×512 |
| `category_id` | Many2one → `aps.avatar.category` | | ondelete=restrict |
| `student_ids` | One2many → `op.student` | | inverse=`avatar_id`, readonly |
| `student_count` | Integer | | computed |

**Constraint:** An avatar can only be assigned to one student at a time.
**Key Methods:** `bulk_create_from_files()`, `action_assign_random_avatars()`.

---

## 5. Media Shop System

### 5.1 aps.media.type

**File:** `models/aps_media/aps_media.py`
**Description:** Media Type (e.g. Avatar, Card, Wallpaper)
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |
| `icon` | Image | | max 256×256 |
| `cost` | Integer | | default cost for new items |
| `stock_resupply_qty` | Integer | | |
| `stock_resupply_delay` | Integer | | days |
| `stock_max` | Integer | | |
| `stock_min` | Integer | | |
| `media_ids` | One2many → `aps.media` | | inverse=`type_id` |
| `media_count` | Integer | | computed, stored |

---

### 5.2 aps.media.collection

**File:** `models/aps_media/aps_media.py`
**Description:** Media Collection (named grouping)
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |
| `media_ids` | One2many → `aps.media` | | inverse=`collection_id` |
| `media_count` | Integer | | computed, stored |

---

### 5.3 aps.media.category

**File:** `models/aps_media/aps_media.py`
**Description:** Media Category (tag-style)
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |

---

### 5.4 aps.media

**File:** `models/aps_media/aps_media.py`
**Description:** Purchasable Media Item
**Order:** `name`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `name` | Char | ✅ | |
| `image` | Image | | max 1024×1024 |
| `type_id` | Many2one → `aps.media.type` | | ondelete=restrict |
| `collection_id` | Many2one → `aps.media.collection` | | ondelete=restrict |
| `category_ids` | Many2many → `aps.media.category` | | |
| `cost` | Integer | | points |
| `stock_available` | Integer | | |
| `stock_resupply_qty` | Integer | | default=1 |
| `stock_resupply_delay` | Integer | | default=7 days |
| `stock_max` | Integer | | default=1 |
| `stock_min` | Integer | | default=0 |
| `history` | Text | | audit log |
| `date_available` | Date | | default=today |
| `date_unavailable` | Date | | optional end date |
| `qty_sold` | Integer | | |
| `date_sold` | Date | | last sale date |
| `user_media_ids` | One2many → `aps.user.media` | | inverse=`media_id` |
| `display_name` | Char | | computed: "Name (Type)" |

**Key Methods:** `action_buy()` — handles purchase with stock locking, point deduction, and ownership record creation. `bulk_create_from_files()` — batch upload.

---

### 5.5 aps.user.media

**File:** `models/aps_media/aps_media.py`
**Description:** User Media ownership record
**Order:** `partner_id, media_id`

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `partner_id` | Many2one → `res.partner` | ✅ | ondelete=cascade |
| `media_id` | Many2one → `aps.media` | ✅ | ondelete=restrict |
| `cost` | Integer | | points paid at purchase |
| `status` | Selection | | `wishlist`/`purchased`/`for_sale`/`sold`/`unavailable` |
| `use_as` | Selection | | `avatar`/`wallpaper`/`card_back` |
| `sell_price` | Integer | | asking price |
| `date_purchased` | Date | | |
| `display_name` | Char | | computed: "Partner - Media (Status)" |

---

### 5.6 aps.user.media.settings

**File:** `models/aps_media/aps_media.py`
**Description:** User Media Settings (per-partner preferences)

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `partner_id` | Many2one → `res.partner` | ✅ | ondelete=cascade |
| `enable_wallpaper` | Boolean | | |
| `use_icons_as_wallpaper` | Boolean | | |
| `wallpaper_quad` | Boolean | | 2×2 tile mode |
| `wallpaper_refresh_minutes` | Integer | | default=0 (disabled) |

---

## 6. Dashboard

### 6.1 aps.dashboard (TransientModel)

**File:** `models/aps_dashboard.py`
**Description:** APS Dashboard (in-memory statistics)

All fields are computed and **not stored**:

| Field | Type |
|-------|------|
| `total_submissions` | Integer |
| `completed_submissions` | Integer |
| `overdue_tasks` | Integer |
| `active_resources` | Integer |
| `total_tasks` | Integer |
| `top_student` | Char |
| `overdue_students` | Integer |

---

## 7. Inherited / Extended Models

### 7.1 res.partner (extensions)

**Files:** `models/res_partner.py`, `models/core/res_partner_teacher.py`, `models/core/res_partner_student.py`

| Added Field | Type | Source File |
|-------------|------|-------------|
| `gender` | Selection (`male`/`female`/`other`) | `res_partner.py` |
| `is_parent` | Boolean | `res_partner.py` (re-labelled) |
| `is_student` | Boolean | `res_partner.py` (re-labelled) |
| `is_teacher` | Boolean | `res_partner.py` (new) |
| `student_count` | Integer (computed) | `res_partner.py` |
| `submission_ids` | One2many → `aps.resource.submission` | `res_partner.py` |
| `teacher_count` | Integer (computed) | `res_partner_teacher.py` |
| `aps_student_count` | Integer (computed) | `res_partner_student.py` |

**Key Behaviours:**
- **Teacher sync (`res_partner_teacher.py`):** When `is_teacher` changes on a partner, auto-creates/activates/deactivates the linked `aps.teacher` record.
- **Student sync (`res_partner_student.py`):** When `is_student` changes, auto-creates/activates/deactivates the linked `aps.student` record with level auto-assignment from `_get_aps_level_for_partner()`. When `category_id` (partner tags) changes, re-syncs the student's `level_id`.
- **Gender/name sync (`res_partner.py`):** Propagates name/gender changes to linked `op.student`, `op.faculty`, `hr.employee` records.

---

### 7.2 res.users (extensions)

**File:** `models/res_users.py`

| Added Field | Type | Key Attributes |
|-------------|------|----------------|
| `avatar_id` | Many2one → `aps.avatar` | self-readable/writable |
| `avatar_image` | Image | related=`avatar_id.image`, readonly |
| `points_balance` | Integer | default=0, self-readable |

---

### 7.3 hr.employee (extensions)

**File:** `models/hr_employee.py`

No new fields. Overrides `write()` to sync mobile phone changes to linked `op.faculty` records.

---

### 7.4 op.student (extensions)

**File:** `models/op_student.py`

| Added Field | Type | Key Attributes |
|-------------|------|----------------|
| `show_all_courses` | Boolean | default=False |
| `avatar_id` | Many2one → `aps.avatar` | |
| `course_detail_ids_filtered` | One2many (computed) | filtered by running state |

Overrides: `create()` and `write()` for name computation from first/middle/last name parts.

---

### 7.5 op.faculty (extensions)

**File:** `models/op_faculty.py`

Makes `last_name` and `birth_date` non-required (defaults provided). Overrides create/write for name computation. Adds `_onchange_emp_id()` to populate faculty fields from employee.

---

### 7.6 op.subject (extensions)

**File:** `models/op_subject.py`

| Added Field | Type | Key Attributes |
|-------------|------|----------------|
| `faculty_ids` | Many2many → `op.faculty` | relation=`op_faculty_op_subject_rel` |
| `icon` | Image | max 64×64 |
| `category_id` | Many2one → `aps.subject.category` | |

Adds `_generate_color_from_name()` for deterministic color generation and `get_subject_colors_map()` for dashboard chart colouring.

---

### 7.7 op.course (extensions)

**File:** `models/op_course.py`

| Added Field | Type | Key Attributes |
|-------------|------|----------------|
| `sequence` | Integer | default=10 |
| `short_name` | Char | size=16 |

---

### 7.8 op.program.level (extensions)

**File:** `models/op_program_level.py`

| Added Field | Type | Key Attributes |
|-------------|------|----------------|
| `sequence` | Integer | default=10 |
| `short_name` | Char | size=16 |
| `code` | Char | size=8 |

---

## 8. Wizard / Transient Models

### 8.1 aps.student.class.bulk.wizard

**File:** `wizard/aps_student_class_bulk_wizard.py`
**Description:** Bulk Maintain Student Class Enrollments

| Field | Type | Key Attributes |
|-------|------|----------------|
| `academic_year_id` | Many2one → `aps.academic.year` | defaults to current year |
| `partner_ids` | Many2many → `res.partner` | domain: `is_student=True` |
| `class_ids` | Many2many → `aps.class` | |
| `operation` | Selection | `add`/`remove`, default=`add` |
| `warning_message` | Html | computed — level mismatch warnings |
| `has_warnings` | Boolean | computed |

**`action_apply()`:** For "add" — creates or reactivates enrollments. For "remove" — archives them.

---

### 8.2 aps.assign.students.wizard

**File:** `models/aps_assign_students_wizard.py`
**Description:** Assign Students to Resource Wizard

| Field | Type | Key Attributes |
|-------|------|----------------|
| `resource_id` | Many2one → `aps.resources` | required, readonly |
| `date_assigned` | Date | required, default=today |
| `time_assigned` | Float | decimal time |
| `date_due` | Date | required |
| `student_ids` | Many2many → `res.partner` | domain: `is_student=True` |
| `assigned_by` | Many2one → `op.faculty` | |
| `custom_submission_name` | Char | |
| `submission_label` | Char | |
| `affected_resource_line_ids` | One2many → `aps.assign.students.wizard.line` | |
| `allow_subject_editing` | Boolean | |
| `has_question` | Selection | `no`/`yes`/`use_parent` |
| `question` | Html | |
| `has_answer` | Selection | `no`/`yes`/`yes_notes`/`use_parent` |
| `answer` | Html | |
| `has_default_answer` | Boolean | |
| `default_answer` | Html | |
| `subjects` | Many2many → `op.subject` | |
| `points_scale` | Integer | default=1 |
| `notify_student` | Boolean | default=True |
| `can_assign` | Boolean | computed |
| `warning_message` | Char | computed |

---

### 8.3 aps.assign.students.wizard.line

**File:** `models/aps_assign_students_wizard.py`
**Description:** Wizard line for affected child resources

| Field | Type | Key Attributes |
|-------|------|----------------|
| `sequence` | Integer | default=10 |
| `wizard_id` | Many2one → `aps.assign.students.wizard` | required |
| `resource_id` | Many2one → `aps.resources` | required |
| `type_icon` | Binary | related |
| `description` | Text | related |
| `has_question` | Selection | related |
| `has_answer` | Selection | related |
| `points_scale` | Integer | related |
| `supporting_resources_buttons` | Json | related |
| `selected` | Boolean | default=True |
| `parent_custom_name_data` | Json | related |
| `parent_resource_id` | Many2one → `aps.resources` | |
| `submission_order` | Integer | |

---

### 8.4 aps.submission.mass.update.wizard

**File:** `models/aps_submission_mass_update_wizard.py`
**Description:** Mass Update Submissions Wizard

Provides toggle+value pairs for bulk-updating any submission field (state, dates, scores, subjects, text fields, notification state). Requires confirmation before applying.

---

### 8.5 aps.resource.mass.update.wizard

**File:** `models/aps_resource_mass_update_wizard.py`
**Description:** Mass Update Resources Wizard

Provides toggle+value pairs for bulk-updating any resource field (name, description, type, category, marks, URLs, question/answer settings, etc.).

---

### 8.6 aps.submission.report.wizard

**File:** `wizard/submission_report_wizard.py`
**Description:** Submission Report Options

| Field | Type | Key Attributes |
|-------|------|----------------|
| `submission_ids` | Many2many → `aps.resource.submission` | |
| `submission_count` | Integer | |
| `show_score` | Boolean | default=True |
| `show_metadata` | Boolean | default=True |
| `show_answer` | Boolean | default=True |
| `show_feedback` | Boolean | default=True |
| `show_model_answer` | Boolean | default=True |
| `page_break_before_resource` | Boolean | default=False |
| `page_break_before_student` | Boolean | default=False |
| `page_break_after_model_answer` | Boolean | default=False |

Generates a PDF report via `aps_sis.submission_report_action`.

---

## 9. Relationship Diagram (Conceptual)

```
res.partner ──── is_teacher ────► aps.teacher
     │
     └──── is_student ────► aps.student ◄──── aps.student.class ────► aps.class
                                  │                                       │
                                  │ level_id                              │ subject_id
                                  ▼                                       ▼
                             aps.level                               aps.subject
                                  │                                       │
                                  │ tag_ids                               │ category_id
                                  ▼                                       ▼
                         res.partner.category                  aps.subject.category
                                                                          │
                                                                          │ tag_ids
                                                                          ▼
                                                              aps.subject.category.tag

aps.resources ──── task_ids ────► aps.resource.task ──── submission_ids ────► aps.resource.submission
     │                                    │
     │ type_id                            │ student_id
     ▼                                    ▼
aps.resource.types                   res.partner

aps.academic.year ◄──── aps.academic.term
                   ◄──── aps.class (academic_year_id)

aps.media ──── user_media_ids ────► aps.user.media ────► res.partner
   │
   ├── type_id ────► aps.media.type
   ├── collection_id ────► aps.media.collection
   └── category_ids ────► aps.media.category

res.users ──── avatar_id ────► aps.avatar ──── category_id ────► aps.avatar.category
```

---

## 10. Security Groups

Defined in `security/aps_sis_security.xml`:

| Group | XML ID | Purpose |
|-------|--------|---------|
| Teacher | `group_aps_teacher` | Full CRUD on all models |
| Student | `group_aps_student` | Read-only on most models; write on submissions, tasks, time tracking, user media |
| (Internal User) | `base.group_user` | Read-only on core SIS models |

Access rules are defined in `security/ir.model.access.csv` (74 rules total).

---

## 11. Key Behaviours & Sync Logic

### Partner ↔ Teacher Bidirectional Sync
- Setting `is_teacher=True` on a partner auto-creates an `aps.teacher` record.
- Creating an `aps.teacher` record auto-sets `is_teacher=True` on the partner.
- Archiving either side archives the other.
- Context flag `skip_teacher_sync` prevents infinite loops.

### Partner ↔ Student Bidirectional Sync
- Setting `is_student=True` on a partner auto-creates an `aps.student` record with auto-assigned level.
- Creating an `aps.student` record auto-sets `is_student=True` on the partner.
- Level is determined by matching partner tags (`category_id`) against `aps.level.tag_ids`.
- Changing partner tags re-syncs the student's level.
- Context flag `skip_student_sync` prevents infinite loops.

### Home Class Auto-Assignment
- `aps.student.home_class_id` is a regular stored field (not computed).
- Recomputed via `_recompute_home_class()` which is event-driven:
  - Triggered on `aps.student.class` create/write/unlink
  - Triggered on `aps.subject.category` write when `tag_ids` changes
  - Triggered on `aps.subject.category.tag` write when `name` changes
- Logic: Finds the first enrolled enrollment whose class's subject's category has a tag named "Home Class" or "Pastoral Care Subject".

### Resource → Task → Submission Chain
- Resources are assigned to students via Tasks (1 task per student per resource).
- Each Task has multiple Submissions (attempts).
- Task state is derived from submission states (overdue > assigned > most recent submission's due_status).
- Submission scores roll up to task-level statistics (last, average, weighted, best).

### Auto-Assignment (Cron)
- Resources with `auto_assign=True` are processed by a cron job.
- Creates submissions on `auto_assign_date`, then advances the date by `auto_assign_frequency` days.
- Stops after `auto_assign_end_date`.

---

## 12. Partner Relations (partner_multi_relation)

> **External module:** `partner_multi_relation` (OCA, Therp BV) — v18.0.1.0.0
> **Dependency added to:** `aps_sis/__manifest__.py` `depends` list
> Use these models to record relationships between partners (e.g., parent/child, guardian/student).

### 12.1 res.partner.relation

**File:** `partner_multi_relation/models/res_partner_relation.py`
**Description:** Physical storage table for partner-to-partner relationships.

| Field | Type | Required | Key Attributes |
|-------|------|----------|----------------|
| `left_partner_id` | Many2one → `res.partner` | ✅ | ondelete=cascade |
| `right_partner_id` | Many2one → `res.partner` | ✅ | ondelete=cascade |
| `type_id` | Many2one → `res.partner.relation.type` | ✅ | ondelete=restrict |
| `date_start` | Date | | |
| `date_end` | Date | | |

**Validation:** `date_start` cannot be after `date_end`.
**Note:** Do not use this model directly for One2many fields — use `res.partner.relation.all` instead.

---

### 12.2 res.partner.relation.all (SQL View)

**File:** `partner_multi_relation/models/res_partner_relation_all.py`
**Description:** `_auto=False` SQL view that exposes each physical relation twice — once in the forward direction, once in the inverse direction. This makes relations effectively symmetric from a UI/query perspective.

| Field | Type | Notes |
|-------|------|-------|
| `this_partner_id` | Many2one → `res.partner` | The "left" partner from this row's perspective |
| `other_partner_id` | Many2one → `res.partner` | The "right" partner from this row's perspective |
| `type_id` | Many2one → `res.partner.relation.type` | The relation type |
| `type_selection_id` | Many2one → `res.partner.relation.type.selection` | Used for display/filtering |
| `date_start` | Date | |
| `date_end` | Date | |
| `is_inverse` | Boolean | `True` when this row represents the inverse direction |
| `active` | Boolean | `False` when `date_end` is in the past |
| `res_model` | Char | Model name for smart button linking |
| `res_id` | Integer | Record ID for smart button linking |
| `any_partner_id` | Many2many (search helper) | Used to search relations involving a given partner |

**Usage pattern — One2many on res.partner:**
```python
relation_ids = fields.One2many(
    'res.partner.relation.all', 'this_partner_id',
    string='Relations',
)
```
**Domain filter for student context:**
```python
[('type_selection_id.name', 'in', ['is parent of', 'is guardian of'])]
```

---

### 12.3 res.partner.relation.type

**File:** `partner_multi_relation/models/res_partner_relation_type.py`
**Description:** Defines the types of relationship that can exist between partners.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | Char | ✅ | translate=True. Forward label, e.g. "is parent of" |
| `name_inverse` | Char | ✅ | translate=True. Inverse label, e.g. "is child of" |
| `contact_type_left` | Selection (`c`=Organisation, `p`=Person) | | Restrict left side to org or person |
| `contact_type_right` | Selection (`c`=Organisation, `p`=Person) | | Restrict right side to org or person |
| `partner_category_left` | Many2one → `res.partner.category` | | Optional tag restriction on left partner |
| `partner_category_right` | Many2one → `res.partner.category` | | Optional tag restriction on right partner |
| `allow_self` | Boolean | | Whether a partner can be related to itself |
| `is_symmetric` | Boolean | | If true, forward and inverse labels are identical |
| `handle_invalid_onchange` | Selection | | One of: `restrict`, `ignore`, `end`, `delete` |

---

### 12.4 res.partner.relation.type.selection (SQL View)

**File:** `partner_multi_relation/models/res_partner_relation_type_selection.py`
**Description:** `_auto=False` SQL view. Exposes each `res.partner.relation.type` twice — once for the forward direction, once for the inverse. Used as the target of `type_selection_id` in `res.partner.relation.all`.

| Field | Type | Notes |
|-------|------|-------|
| `name` | Char | The direction-specific label (forward `name` or inverse `name_inverse`) |
| `type_id` | Many2one → `res.partner.relation.type` | The underlying type |
| `is_inverse` | Boolean | `True` for the inverse row |
| `contact_type_this` | Selection | Contact type constraint for `this_partner_id` |
| `contact_type_other` | Selection | Contact type constraint for `other_partner_id` |
| `partner_category_this` | Many2one → `res.partner.category` | Tag restriction for `this_partner_id` |
| `partner_category_other` | Many2one → `res.partner.category` | Tag restriction for `other_partner_id` |
