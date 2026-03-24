# APEX — Academic Progress and Excellence (`aps_sis`)

**Version:** 18.0.1.0.42  
**License:** LGPL-3  
**Author:** APS  
**Odoo:** Community Edition 18.0  
**Depends on:** `base`, `openeducat_core`, `web`, `mail`, `portal`, `hr`

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Models](#models)
   - [APSResource](#apsresource)
   - [APSResourceTask](#apsresourcetask)
   - [APSResourceSubmission](#apsresourcesubmission)
   - [Supporting Models](#supporting-models)
4. [Security & Access Control](#security--access-control)
5. [Key Workflows](#key-workflows)
6. [Dashboard & Analytics](#dashboard--analytics)
7. [Progress Prediction Algorithm](#progress-prediction-algorithm)
8. [Leaderboards](#leaderboards)
9. [Frontend Components](#frontend-components)
10. [Controllers](#controllers)
11. [Gamification](#gamification)
12. [Developer Notes](#developer-notes)

---

## Overview

APEX is a comprehensive **student progress tracking and academic management system** built as a custom Odoo 18 addon. It extends the [OpenEducat](https://www.openeducat.org/) SIS (Student Information System) with:

- Assignment creation and distribution to students
- Submission tracking with grading and feedback
- Real-time analytics dashboards with KPI cards and charts
- Predictive completion estimates based on historical pace
- Progress and completion leaderboards
- Gamification (avatars, badges, confetti rewards)
- Optional student study-time tracking
- Public portal sharing of resources via tokenized URLs

---

## Architecture

```
aps_sis/
├── models/                     # Odoo ORM models (Python)
│   ├── aps_resources/          # Resource (assignment) definition
│   ├── aps_resource_task.py    # Resource → Student assignment link
│   ├── aps_resource_submission.py  # Student submission records + analytics
│   ├── aps_resource_types.py   # Resource categorisation
│   ├── aps_resource_tags.py    # Resource tagging
│   ├── aps_time_tracking.py    # Study-time logging
│   ├── aps_dashboard.py        # Transient model for dashboard stats
│   ├── aps_avatar.py           # Gamification avatar store
│   └── extensions/             # Overrides for op.student, op.faculty, etc.
├── views/                      # XML views, menus, and actions
├── security/                   # Groups, ACLs, record rules
├── data/                       # Cron jobs, email templates, seed data
├── controllers/                # Portal HTTP controllers
├── wizard/                     # Transient wizard models
└── static/src/
    ├── components/             # OWL dashboard components
    └── js/                     # Standalone widgets and utilities
```

---

## Models

### APSResource

**File:** `models/aps_resources/model.py`  
**Technical Name:** `aps.resources`

The central content object — a piece of academic work (homework, quiz, exam, practice sheet, progress tracker, etc.).

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char | Resource name (displayed in lists and titles) |
| `question` | Html | The question/task content, supports rich text |
| `answer` | Html | Model answer (teacher-visible only) |
| `notes` | Html | Additional notes; `exclude:` directives here control leaderboard filtering |
| `type_id` | Many2one → `aps.resource.type` | Resource category (Homework, Quiz, Exam, etc.) |
| `subjects` | Many2many → `op.subject` | Subjects this resource belongs to |
| `marks` | Float | Total marks available |
| `points_scale` | Integer | Gamification points awarded on completion |
| `task_ids` | One2many → `aps.resource.task` | Per-student assignment records |

**Key method:**
- `get_pace_dates()` — Returns `{start_date, end_date}` for resources used as progress trackers (pace schedule).

---

### APSResourceTask

**File:** `models/aps_resource_task.py`  
**Technical Name:** `aps.resource.task`

A **1-to-1 link** between a resource and a specific student — represents the assignment of a resource to a student.

| Field | Type | Description |
|-------|------|-------------|
| `resource_id` | Many2one → `aps.resources` | The assigned resource |
| `student_id` | Many2one → `res.partner` | The student partner |
| `state` | Selection | `draft / assigned / complete` |
| `submission_count` | Integer (computed) | Number of attempts submitted |
| `best_result` | Float (computed) | Highest `result_percent` across submissions |
| `weighted_result` | Float (computed) | Weighted score based on resource configuration |
| `avg_result` | Float (computed) | Average across all submissions |

---

### APSResourceSubmission

**File:** `models/aps_resource_submission.py`  
**Technical Name:** `aps.resource.submission`

Records a **single student attempt** at a resource. This is the primary data source for all analytics.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | Many2one → `aps.resource.task` | Parent task |
| `resource_id` | Many2one → `aps.resources` | Related resource (convenience) |
| `student_id` | Many2one → `res.partner` | Submitting student |
| `state` | Selection | `draft / submitted / complete` |
| `score` | Float | Raw score awarded |
| `result_percent` | Float (computed) | `score / resource.marks × 100` |
| `date_submitted` | Datetime | When the student submitted |
| `date_completed` | Datetime | When the teacher marked complete |
| `date_due` | Date | Submission deadline |
| `answer` | Html | Student's submitted answer |
| `feedback` | Html | Teacher feedback |
| `subjects` | Many2many → `op.subject` | Subjects this submission counts toward |
| `submission_active` | Boolean | Whether this submission counts in analytics |

**Key analytics methods:**

| Method | Returns | Used by |
|--------|---------|---------|
| `get_progress_leaderboard_data(limit)` | Ranked list by current average progress % | Dashboard progress leaderboard |
| `get_completion_leaderboard_data(limit)` | Ranked list by predicted completion % at deadline | Dashboard completion leaderboard |
| `get_progress_data_for_dashboard()` | Time-series data per subject | Progress line + bar charts |
| `get_student_comparison_data()` | Current student vs. peer averages | Dashboard comparison chart |
| `get_leaderboard_data(domain, limit)` | Generic points-based leaderboard | Points leaderboard |

---

### Supporting Models

| Model | Technical Name | Purpose |
|-------|---------------|---------|
| Resource Type | `aps.resource.type` | Categorises resources (Homework, Quiz, etc.) |
| Resource Tag | `aps.resource.tag` | Freeform tags for filtering |
| Avatar | `aps.avatar` | Gamification avatars linked to students |
| Avatar Category | `aps.avatar.category` | Groups avatars into themed sets |
| Time Tracking | `aps.time.tracking` | Per-subject study-time log entries |
| Dashboard (transient) | `aps.dashboard` | Aggregated KPI values for UI rendering |
| Assign Wizard (transient) | `aps.assign.students.wizard` | Bulk resource → student assignment |
| Submission Mass Update Wizard | `aps.submission.mass.update.wizard` | Batch grade/update submissions |

**OpenEducat model extensions** (via inheritance):

| Extended Model | Additions |
|----------------|-----------|
| `op.student` | Avatar field, subject enrollment helpers |
| `op.faculty` | Permission helpers (`_get_current_faculty()`) |
| `op.subject` | Icon, category, subject colour for charts |
| `op.student.course.detail` | Enrolled subjects (M2M) for progress filtering |

---

## Security & Access Control

### Groups (`security/groups.xml`)

| Group | XML ID | Description |
|-------|--------|-------------|
| Student | `group_aps_student` | View assigned resources, submit attempts, view own dashboard |
| Teacher | `group_aps_teacher` | Manage resources, grade submissions, view all dashboards |
| Manager | `group_aps_manager` | Full admin access (implies Teacher) |

### ACL rules (`security/ir.model.access.csv`)

| Model | Students | Teachers |
|-------|----------|---------|
| Resources | Read | Full CRUD |
| Tasks | Read + Create/Write | Full CRUD |
| Submissions | Read + Create/Write (own) | Full CRUD |
| Avatars | Read | Full CRUD |
| Tags / Types | Read | Full CRUD |

Record-level rules enforce that students can only access their own task and submission records.

---

## Key Workflows

### 1. Resource Assignment

```
Teacher creates APSResource
        ↓
Run "Assign Students" wizard (APSAssignStudentsWizard)
        ↓
One APSResourceTask record created per student
        ↓
Student sees task on their dashboard
```

### 2. Submission Lifecycle

```
APSResourceTask (state: assigned)
        ↓  Student submits answer
APSResourceSubmission (state: submitted)
        ↓  Teacher reviews and grades
APSResourceSubmission (state: complete)  +  score stored
        ↓
result_percent computed → feeds analytics
```

### 3. Progress Tracking

Resources whose `name` contains **" Progress"** (space + "Progress") are treated as **progress tracker resources**. Their submissions form the historical data series used for:
- The progress line chart (trend over time)
- The progress bar chart (current snapshot per subject)
- The completion prediction (extrapolation to deadline)

---

## Dashboard & Analytics

The main dashboard is an **OWL 2 client action** (`apex_dashboard.Dashboard`) loaded as a backend view.

### KPI Cards

Each card shows a current value and a comparison against a previous period (configurable: 7 / 14 / 30 / 90 / 180 / 365 days):

| KPI | Description |
|-----|-------------|
| Total Submissions | Number of submission records in the period |
| Tasks Assigned | Number of resource tasks created |
| Overdue Tasks | Tasks past `date_due` and not complete |
| Points Earned | Sum of gamification points |
| Student Rank | Position in the progress leaderboard |

### Charts

| Chart | Component | Description |
|-------|-----------|-------------|
| Progress Line Chart | `progress_charts.js` | Time-series result_percent per subject |
| Progress Bar Chart | `progress_charts.js` | Current % + predicted remaining % stacked |
| Progress Leaderboard | `leaderboard.js` | Students ranked by average current progress |
| Completion Prediction Leaderboard | `leaderboard.js` | Students ranked by predicted % at deadline |
| Student Comparison | `progress_charts.js` | Current student vs. class percentiles |
| Time Tracking | `time_tracking_dashboard.js` | Cumulative study time per subject |

---

## Progress Prediction Algorithm

The prediction is calculated identically in two places — the frontend (for the progress **bar chart**) and the backend (for the **completion leaderboard**) — to keep both in sync.

### Goal

> "If this student continues working at their recent pace, what % of the course will they have completed by the deadline?"

### Step-by-step

#### Step 1 — Determine the deadline

The **latest `end_date`** across all Progress resources is used as the single course deadline.

```
deadline = max(resource.get_pace_dates()['end_date']
               for resource in progress_resources)
```

If no deadline exists, or it has already passed, **no prediction is shown**.

#### Step 2 — Days remaining

```
days_remaining = deadline − today   (in fractional days, JS; integer days, Python)
```

#### Step 3 — Calculate the daily rate (per subject)

For each subject, the historical submission data points are sorted ascending by date. Only data points from the **last 4 months (120 days)** are used to calculate the rate. This makes the prediction reflect recent pace rather than the student's pace at the very beginning of the course.

```
four_months_ago = today − 120 days

recent_points = [p for p in sorted_points if p.date >= four_months_ago]

# Fall back to all data if fewer than 2 recent points exist
first_point = recent_points[0]  if len(recent_points) >= 2
              else sorted_points[0]

last_point  = sorted_points[-1]   # Most recent submission

days_between = last_point.date − first_point.date

daily_rate = (last_point.progress − first_point.progress) / days_between
```

If `daily_rate ≤ 0` (no forward progress in the window), **no prediction is added** for that subject.

#### Step 4 — Project to deadline

```
predicted_total = min(current_progress + daily_rate × days_remaining, 100%)
```

The result is capped at 100% — a student cannot be predicted to exceed full completion.

#### Step 5 — Predicted segment (bar chart only)

The bar chart stacks two segments per subject:

```
bar_segment_1 = current_progress          (solid colour)
bar_segment_2 = predicted_total − current_progress  (light grey, dashed border)
```

`bar_segment_2` is what `_calculatePredictionData()` returns.

#### Step 6 — Average across subjects (completion leaderboard only)

```
avg_predicted = mean(predicted_total for each enrolled, non-excluded subject)
```

Students are then ranked by `avg_predicted` descending.

### Where it lives

| Location | File | Method |
|----------|------|--------|
| Frontend (bar chart) | `static/src/components/progress_charts.js` | `_calculatePredictionData()` |
| Backend (leaderboard) | `models/aps_resource_submission.py` | `get_completion_leaderboard_data()` |

### Edge cases

| Condition | Behaviour |
|-----------|-----------|
| Deadline has passed | No prediction shown anywhere |
| Subject already at 100% | Predicted segment = 0; counted as 100 in leaderboard avg |
| Fewer than 2 data points | No prediction for that subject |
| Negative daily rate | No prediction for that subject |
| Fewer than 2 points in 4-month window | Falls back to using the full history |

---

## Leaderboards

### Progress Leaderboard

**Source:** `get_progress_leaderboard_data()`  
**Metric:** Average **current** `result_percent` across enrolled, non-excluded subjects.  
**Track mode:** `'progress'` — 3-zone gradient:
- Red zone: below the pace redline
- Yellow zone: between redline and expected pace
- Light grey: at or ahead of pace

### Completion Prediction Leaderboard

**Source:** `get_completion_leaderboard_data()`  
**Metric:** Average **predicted** `result_percent` at the course deadline.  
**Track mode:** `'completion'` — full gradient from red → orange → yellow → green anchored to absolute progress % thresholds:

| Threshold | Colour |
|-----------|--------|
| 0–50% | Red |
| 70% | Orange |
| 90% | Yellow |
| 100% | Green |

The gradient is mapped relative to the visible range of students on the leaderboard so the colour signal is always meaningful regardless of the actual spread of values.

---

## Frontend Components

All components use **OWL 2** (Odoo Web Library) and ES modules. No legacy `odoo.define` or `require` patterns.

### Dashboard (`components/dashboard.js`)

Main entry point. Manages:
- Global period filter (7 / 14 / 30 / 90 / 180 / 270 / 365 days)
- Student selector (teacher mode: filter to one student)
- All async data fetches (ORM calls via `this.orm.call(...)`)
- Loading states for progressive rendering
- Local storage of user preferences (period, student)
- Confetti reward animation on high-score events

### Progress Charts (`components/progress_charts.js`)

Renders:
- **Progress line chart** — Chart.js time-series, one dataset per subject showing `result_percent` over time, with a separate "pace" dataset
- **Progress bar chart** — Horizontal Chart.js stacked bar; current progress (colour-coded by subject) + predicted segment (grey, dashed border via custom plugin)
- **Student comparison chart** — Line/bar comparing current student to class percentiles

Key method: `_calculatePredictionData()` (see [Progress Prediction Algorithm](#progress-prediction-algorithm)).

### Leaderboard (`components/leaderboard/leaderboard.js`)

Reusable ranked display. Props:

| Prop | Type | Description |
|------|------|-------------|
| `entries` | Array | Leaderboard rows |
| `displayLimit` | Number | Maximum entries shown (default 15) |
| `valueSuffix` | String | Unit appended to values (e.g. `'%'`) |
| `isFaculty` | Boolean | Switches image source (partner photo vs. avatar) |
| `currentUserPartnerId` | Number | Highlights the logged-in user's entry |
| `trackMode` | String | `'default'` / `'progress'` / `'completion'` |
| `redlinePercent` | Number | Redline threshold (progress mode only) |
| `pacePercent` | Number | Pace threshold (progress mode only) |

Entries are displayed **left (worst) → right (best)**. Spacers between entries have proportional `flex-grow` values based on the point gap between adjacent students, so the horizontal positions reflect relative rank distance.

### Other Widgets

| Widget | File | Description |
|--------|------|-------------|
| KPI Card | `components/kpi_card/` | Value + period-over-period % change |
| KPI Gauge | `components/kpi_gauge/` | Circular tier/rank indicator |
| Chart Renderer | `components/chart_renderer/` | Generic Chart.js wrapper |
| Timer Systray | `components/timer_systray/` | System tray time-entry start/stop |
| Time Tracking Dashboard | `components/time_tracking_dashboard/` | Study-time summary by subject |
| Percent Pie Ranged | `static/src/js/percentpie_ranged_widget.js` | Partial pie progress indicator |
| Math Formula Renderer | `static/src/js/math_formula_renderer.js` | LaTeX/MathML rendering |
| Share URL Widget | `static/src/js/share_url_widget.js` | Portal share-link generator |
| Avatar Selector | `static/src/js/avatar_selector.js` | Student avatar selection UI |
| Badge Decorator | `static/src/js/badge_decorator_widget.js` | Achievement badges on records |

---

## Controllers

### Portal Controller (`controllers/portal.py`)

Handles HTTP routes for public/portal resource sharing:

- **`_slugify_heading(text)`** — Converts heading text to URL-safe anchor IDs.
- **`_process_notes_html(notes_html)`** — Parses resource notes HTML and injects an auto-generated Table of Contents before the first heading.

Portal URLs use tokenized parameters to grant read-only access to specific resources without requiring an Odoo login.

---

## Gamification

| Feature | Model/File | Description |
|---------|-----------|-------------|
| Avatars | `aps.avatar`, `aps.avatar.category` | Custom images students can select as their leaderboard avatar |
| Points | `aps.resources.points_scale` field | Each resource awards a configurable number of points on completion |
| Confetti | `static/src/js/confetti.browser.min.js` | Animated celebration on dashboard KPI milestones |
| Leaderboard rings | `leaderboard.js → getRingColor()` | 🥇 Blue / 🥈 Red / 🥉 Gold for podium positions |

---

## Developer Notes

### Adding a new Progress resource

Any resource with **` Progress`** (a space followed by the word "Progress") in its `name` field is automatically treated as a progress tracker and included in all analytics calculations.

### Excluding subjects from leaderboards

Add a line in the resource's `notes` field:

```
exclude: Subject Name 1, Subject Name 2
```

These subjects are stripped from both leaderboard calculations. A second directive `exclude_from_avg:` removes subjects from the average without hiding them entirely.

### Upgrading the module

```powershell
python odoo-bin -c odoo.conf -d <database> -u aps_sis --stop-after-init
```

### Running with debug mode

Add `dev_mode = all` to `odoo.conf` to enable the developer menu, which is useful for inspecting computed fields and triggering manual recomputation.

### Asset changes

JavaScript and CSS changes to `static/src/` are picked up without a server restart in debug mode. Clear browser cache if changes are not reflected.
