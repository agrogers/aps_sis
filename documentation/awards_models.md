# Awards Module — Models Documentation

## Overview

The Awards module (located at `models/awards/`) provides a complete end-to-end system for managing award voting and certificate generation within Odoo. It supports configurable award categories, vote rounds with flexible eligibility rules, vote tracking, and certificate issuance with PDF printing. The module integrates with the academic structure (levels, subjects, terms, academic weeks) and HR departments.

---

## Model Index

| File | Model Name | Type | Description |
|------|-----------|------|-------------|
| `aps_award_tag.py` | `aps.award.tag` | Persistent | Simple tag for categorizing awards |
| `aps_award_sub_category.py` | `aps.award.sub.category` | Persistent | Sub-category of an award category |
| `aps_award_category.py` | `aps.award.category` | Persistent | Defines an award category with voting rules |
| `aps_award_voting_set.py` | `aps.award.voting.set` | Persistent | Groups multiple vote rounds into a set |
| `aps_award_vote_round.py` | `aps.award.vote.round` | Persistent | Defines a voting round with eligibility & rules |
| `aps_award_vote.py` | `aps.award.vote` | Persistent | Individual vote cast by a voter for a recipient |
| `aps_certificate_template.py` | `aps.certificate.template` | Persistent | Template for certificate PDF layout |
| `aps_certificate.py` | `aps.certificate` | Persistent | Award certificate issued to a recipient |
| `aps_award_voter_wizard.py` | `aps.award.voter.wizard` | Transient | Wizard to add voters to a vote round |
| `aps_award_candidate_wizard.py` | `aps.award.candidate.wizard` | Transient | Wizard to add eligible candidates to a round |
| `aps_award_vote_round_mass_update_wizard.py` | `aps.award.vote.round.mass.update.wizard` | Transient | Wizard to mass-update multiple vote rounds |

---

## 1. `aps.award.tag` — Award Tag

**File:** `aps_award_tag.py`  
**Model:** `aps.award.tag`  
**Table:** `aps_award_tag`  
**Order:** `name`

A simple, lightweight tag model used to categorize award categories and vote rounds.

### Fields

| Field | Type | Constraints |
|-------|------|------------|
| `name` | `Char` | Required, unique |

### SQL Constraints

- `name_uniq`: Tag name must be unique across all records.

---

## 2. `aps.award.sub.category` — Award Sub-Category

**File:** `aps_award_sub_category.py`  
**Model:** `aps.award.sub.category`  
**Table:** `aps_award_sub_category`  
**Order:** `sequence, name`

Represents a sub-division of an award category. Each sub-category belongs to exactly one parent category.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `category_id` | `Many2one` → `aps.award.category` | Required, `ondelete='cascade'` |
| `name` | `Char` | Required |
| `description` | `Char` | Optional |
| `sequence` | `Integer` | Default 10 |

---

## 3. `aps.award.category` — Award Category

**File:** `aps_award_category.py`  
**Model:** `aps.award.category`  
**Table:** `aps_award_category`  
**Order:** `name`

The core configuration model for an award type. An award category defines what the award is about, who can vote, and how voting is restricted. It also links to sub-categories, tags, levels, terms, and subject categories for filtering.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `name` | `Char` | Required |
| `description` | `Text` | Full description |
| `short_description` | `Text` | Brief description |
| `image` | `Image` | Category image |
| `level_ids` | `Many2many` → `aps.level` | Applicable levels |
| `term_ids` | `Many2many` → `aps.academic.term` | Applicable academic terms |
| `subject_category_ids` | `Many2many` → `aps.subject.category` | Applicable subject categories |
| `certificate_template_id` | `Many2one` → `aps.certificate.template` | Default certificate template (`ondelete='set null'`) |
| `voting_restrictions` | `Selection` | `none` / `number` / `year_level` (default: `none`) |
| `voting_active` | `Boolean` | Whether voting is active (default: `False`) |
| `adhoc_vote` | `Boolean` | Allow ad-hoc voting outside rounds (default: `False`) |
| `open_date` | `Date` | Tracks award history start date |
| `sub_category_ids` | `One2many` → `aps.award.sub.category` | Reverse of sub-category `category_id` |
| `tag_ids` | `Many2many` → `aps.award.tag` | Tags via intermediary table `aps_award_category_tag_rel` |

### Business Logic

- **`write()` override:** When `tag_ids` are updated on a category, all related vote rounds (`aps.award.vote.round`) referencing this category have their `tag_ids` automatically synchronized to match the category's tags. This ensures consistency between category and round tag assignments.

---

## 4. `aps.award.voting.set` — Award Voting Set

**File:** `aps_award_voting_set.py`  
**Model:** `aps.award.voting.set`  
**Table:** `aps_award_voting_set`  
**Order:** `sequence, name`

A grouping mechanism that organizes multiple vote rounds into a named collection. Useful for running voting campaigns or award cycles that span multiple rounds. Voting sets have a visual identity (icon, color) and a date range.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `sequence` | `Integer` | Default 10 |
| `name` | `Char` | Required |
| `icon` | `Image` | Up to 256×256 px |
| `color` | `Char` | Default `#5c1ea8` |
| `date_start` | `Date` | Start date of the voting set |
| `date_end` | `Date` | End date of the voting set |
| `round_ids` | `Many2many` → `aps.award.vote.round` | Via `aps_vote_round_voting_set_rel` |
| `vote_ids` | `Many2many` → `aps.award.vote` | **Computed** — all votes across all rounds in the set |

### Computed Fields

- **`vote_ids`:** Dependent on `round_ids`. Aggregates all `aps.award.vote` records whose `vote_round_id` is in the set's rounds. Uses optimized batch search across all rounds.

---

## 5. `aps.award.vote.round` — Award Vote Round

**File:** `aps_award_vote_round.py`  
**Model:** `aps.award.vote.round`  
**Table:** `aps_award_vote_round`  
**Order:** `datetime_start desc, id desc`

The central model of the awards system. A vote round defines a specific voting event: when it occurs, who can vote, who is eligible as a candidate, what rules govern voting behavior, and what status it has.

### Core Fields

| Field | Type | Details |
|-------|------|---------|
| `name` | `Char` | Required |
| `description` | `Text` | Full description |
| `short_description` | `Text` | Brief description |
| `image` | `Image` | Round image (auto-populated from category) |
| `color` | `Char` | Default `#5c1ea8` |
| `datetime_start` | `Datetime` | Required |
| `datetime_end` | `Datetime` | Required |
| `status` | `Selection` | `draft` / `open` / `closed` / `finalised` (default: `draft`) |
| `recurring_days` | `Integer` | Days before auto-rescheduling next round (0 = disabled) |
| `award_category_id` | `Many2one` → `aps.award.category` | `ondelete='restrict'` |
| `award_sub_category_id` | `Many2one` → `aps.award.sub.category` | `ondelete='restrict'`, domain filtered by `award_category_id` |
| `academic_week_id` | `Many2one` → `aps.academic.week` | `ondelete='restrict'` |
| `tag_ids` | `Many2many` → `aps.award.tag` | Via `aps_award_vote_round_tag_rel` |
| `voting_set_ids` | `Many2many` → `aps.award.voting.set` | Via `aps_vote_round_voting_set_rel` |
| `round_manager_ids` | `Many2many` → `res.partner` | Via `aps_award_vote_round_manager_rel` |
| `display_name` | `Char` | **Computed** — `{name} ({YYYY-MM-DD})` |

### Eligible Voters (JSON-backed virtual fields)

The `eligible_voters` JSON field stores a dict: `{"partner_ids": [...], "level_ids": [...], "subject_category_ids": [...], "department_ids": [...]}`. Backward-compatible with plain list format (treated as `partner_ids`).

**Visibility toggles** (stored booleans controlling which UI sections are shown):
- `voter_show_staff` — People
- `voter_show_levels` — Levels
- `voter_show_categories` — Subject Categories
- `voter_show_departments` — Departments

**Sub-toggles** (which person types to include):
- `voter_levels_include_teachers` (default: `True`)
- `voter_levels_include_students` (default: `True`)
- `voter_categories_include_teachers` (default: `True`)
- `voter_categories_include_students` (default: `False`)

**Virtual Many2many fields** (computed from `eligible_voters` JSON):
- `eligible_voter_partner_ids` → `res.partner`
- `eligible_voter_level_ids` → `aps.level`
- `eligible_voter_category_ids` → `aps.subject.category`
- `eligible_voter_department_ids` → `hr.department`

### Eligible Candidates (JSON-backed virtual fields)

The `eligible_candidates` JSON field stores a dict: `{"level_ids": [...], "subject_category_ids": [...], "student_ids": [...], "department_ids": [...]}`.

**Visibility toggles:**
- `candidate_show_levels` (default: `False`)
- `candidate_show_categories` (default: `False`)
- `candidate_show_students` (default: `False`)
- `candidate_show_departments` (default: `False`)

**Sub-toggles:**
- `candidate_levels_include_teachers` (default: `False`)
- `candidate_levels_include_students` (default: `True`)
- `candidate_categories_include_teachers` (default: `False`)
- `candidate_categories_include_students` (default: `True`)

**Virtual Many2many fields:**
- `eligible_candidate_level_ids` → `aps.level`
- `eligible_candidate_category_ids` → `aps.subject.category`
- `eligible_candidate_student_ids` → `aps.student`
- `eligible_candidate_department_ids` → `hr.department`

### Ineligible Candidates (JSON-backed virtual fields)

The `ineligible_candidates` JSON field stores a dict: `{"exclude_voter": bool, "partner_ids": [...]}`.

**Virtual fields:**
- `ineligible_candidate_exclude_voter` → `Boolean`
- `ineligible_candidate_partner_ids` → `res.partner`
- `ineligible_show_people` → `Boolean`

### Rules (JSON-backed virtual fields)

The `rules` JSON field stores rule configuration as a flexible dict. Virtual fields expose individual rules:

| Virtual Field | Type | Default | Description |
|---------------|------|---------|-------------|
| `rule_limit_votes` | `Boolean` | `False` | Limit number of votes per voter |
| `rule_limit_votes_count` | `Integer` | `1` | Max votes per voter |
| `rule_show_times_awarded` | `Boolean` | `True` | Show "Times Awarded" column |
| `rule_show_last_awarded` | `Boolean` | `True` | Show "Last Awarded" column |
| `rule_show_level_dept` | `Boolean` | `True` | Show "Level / Department" column |
| `rule_limit_candidates_to_own_students` | `Selection` | `no` | `no` / `yes` / `optional` |
| `rule_allow_no_vote` | `Boolean` | `False` | Allow abstention |
| `rule_send_reminder_email` | `Boolean` | `False` | Enable reminder emails for this round |
| `rule_limit_to_voter_year_level` | `Boolean` | `False` | Restrict candidates to voter's year level |

### Statistics Fields

| Field | Type | Details |
|-------|------|---------|
| `votes_cast` | `Integer` | **Computed & stored** — count of submitted/closed votes |
| `active_voter_count` | `Integer` | **Computed & stored** — distinct voters who cast votes |
| `total_voter_count` | `Integer` | **Computed & stored** — total eligible voter count |
| `vote_ids` | `One2many` → `aps.award.vote` | Reverse of `vote_round_id` |
| `result_summary` | `Json` | Stores computed results |
| `rules` | `Json` | Stores rule configuration |

### Key Methods

#### Lifecycle Actions
- **`action_open()`**: 
  1. Calls `_collect_eligible_voter_partners()` to resolve all eligible voters.
  2. Creates `aps.award.vote` records for new voters (skips those who already have a ballot).
  3. Sets vote state to `open`, sets `open_date` to today, `due_date` to round end date.
  4. Sets round status to `open`.

- **`action_close()`**: Sets status to `closed`.

- **`action_finalise()`**: Sets status to `finalised`.

- **`action_reset_draft()`**: Sets status to `draft`.

#### Voter Resolution
- **`_collect_eligible_voter_partners()`**: Resolves all eligible voter `res.partner` IDs by combining:
  1. Explicitly listed partners from `eligible_voters["partner_ids"]`.
  2. Teachers/assistant teachers from classes matching specified levels and/or subject categories (controlled by sub-toggles).
  3. Students whose level matches specified voter levels.
  4. Students enrolled in classes with matching subject categories.
  5. Active employees in specified departments.

- **`_get_voters_dict()`** / **`_set_voters_dict(data)`**: Accessor methods for the `eligible_voters` JSON field, handling legacy flat-list format.

#### Onchange Handlers
- **`_onchange_award_category_id()`**: Auto-populates `image` from the selected category.
- **`_onchange_voting_set_ids()`**: Auto-populates `color` from the first voting set.

#### Copy
- **`copy()`**: Appends "(Copy)" to the name and resets status to `draft`.

#### Convenience
- **`action_copy_voter_config_to_candidates()`**: Copies eligible voter levels, subject categories, and departments to the candidate eligibility lists.

#### Scheduled Actions
- **`action_send_voting_reminders()`** (cron method): Sends reminder emails to staff with open votes in rounds where `rule_send_reminder_email` is enabled. Groups votes by voter, builds per-round summary rows, and sends via the `email_template_voting_reminder` mail template.

---

## 6. `aps.award.vote` — Award Vote

**File:** `aps_award_vote.py`  
**Model:** `aps.award.vote`  
**Table:** `aps_award_vote`  
**Order:** `submitted_date desc, id desc`

Represents a single vote cast by a voter for a recipient. Each vote is tied to a vote round and can transition through states: `pending` → `open` → `submitted` → `closed`. Also provides RPC methods for the Vote Analysis Dashboard.

### Core Fields

| Field | Type | Details |
|-------|------|---------|
| `description` | `Text` | **Computed & editable** — inherited from round or category |
| `short_description` | `Text` | **Computed & editable** — inherited from round or category |
| `image` | `Image` | **Computed & editable** — inherited from round or category |
| `award_category_id` | `Many2one` → `aps.award.category` | Optional, `ondelete='restrict'` |
| `award_sub_category_id` | `Many2one` → `aps.award.sub.category` | Optional, domain filtered by category |
| `academic_week_id` | `Many2one` → `aps.academic.week` | Optional |
| `recipient_partner_id` | `Many2one` → `res.partner` | The person being voted for |
| `voter_partner_id` | `Many2one` → `res.partner` | Required — the person casting the vote |
| `note` | `Text` | Optional note |
| `comment` | `Text` | Optional comment |
| `submitted_date` | `Date` | Date the vote was submitted |
| `open_date` | `Date` | Date the vote was opened |
| `due_date` | `Date` | Deadline for voting |
| `vote_round_id` | `Many2one` → `aps.award.vote.round` | Optional, `ondelete='set null'` |
| `state` | `Selection` | `pending` / `open` / `submitted` / `closed` (default: `open`) |
| `voter_access_token` | `Char` | **Computed** — access token for voter portal |

### Related/Convenience Fields (stored, read-only)

| Field | Related To |
|-------|-----------|
| `round_name` | `vote_round_id.name` |
| `round_status` | `vote_round_id.status` |
| `round_image` | `vote_round_id.image` |
| `round_datetime_start` | `vote_round_id.datetime_start` |
| `round_datetime_end` | `vote_round_id.datetime_end` |
| `category_name` | `award_category_id.name` |
| `category_image` | `award_category_id.image` |
| `recipient_name` | `recipient_partner_id.name` |
| `voter_name` | `voter_partner_id.name` |

### Computed Fields Logic

- **`_compute_description_fields()`**: Cascading fallback — tries `vote_round_id` first, then `award_category_id` for description, short_description, and image.
- **`_compute_voter_access_token()`**: Uses `partner.sudo()._get_or_create_access_token()` to generate a portal access token.

### Vote Analysis Dashboard RPC Methods

#### `get_vote_analysis_filter_options()`
Returns available filter dropdown options:
- Rounds (status: open, closed, finalised)
- Categories (all)
- Sub-categories (all)
- Voting sets (all)

#### `get_recipient_domain(recipient_type, level_ids, department_ids)`
Returns partner IDs matching a recipient type filter:
- `student`: Filters by `aps.student`, optionally by level
- `staff`: Filters by `hr.employee`, optionally by department

#### `get_vote_analysis_data(filters)`
The primary dashboard data endpoint. Aggregates submitted/closed votes by various dimensions.

**Filter parameters:**
- `date_from`, `date_to` — date range on `submitted_date`
- `round_ids`, `category_ids`, `sub_category_ids` — filter by round/category
- `recipient_ids` — explicit partner filter
- `series_by` — group votes by: `round`, `category`, `sub_category`, or `voting_set`
- `recipient_type` — `all`, `student`, or `staff`
- `level_ids`, `department_ids` — further narrow by academic level or HR department
- `overlay` — `certificates` to include certificate counts

**Returns:**
- `series`: list of `{id, name}` for the X-axis dimension
- `recipients`: list of `{id, name, votes: {series_id: count}, total}` sorted by total descending
- `certificate_counts`: dict of `{partner_id: count}` when overlay is certificates

**Notable behavior:**
- Two-layer recipient filtering: type-based pool intersected with explicit IDs
- Voting set series requires pre-fetching round-to-voting-set mappings
- Each recipient's `votes` dict maps series IDs to vote counts

#### `get_vote_details(vote_ids)`
Returns individual vote records with:
- Recipient/voter/round/category names and IDs
- Submitted date, state, comment
- `has_certificate` flag (True if linked to any certificate)
- `cert_usage_count` (how many certificates reference this vote)

#### `update_vote_comment(vote_id, comment)`
Updates the comment field of a specific vote.

#### `get_certificate_details(filters)`
Returns certificates for a given recipient, optionally filtered by date range, category, or specific vote.

#### `create_certificate_from_selected_votes(vote_ids, recipient_id)`
Creates an `aps.certificate` from a set of selected votes. Workflow:
1. Fetches selected votes and extracts category/sub-category/round info.
2. Looks up the certificate template from the award category.
3. Collects all unique voter partners as `related_partner_ids`.
4. Aggregates all non-empty comments as `notes`.
5. Creates the certificate record linked to all selected votes and voters.

---

## 7. `aps.certificate.template` — Certificate Template

**File:** `aps_certificate_template.py`  
**Model:** `aps.certificate.template`  
**Table:** `aps_certificate_template`

Defines the visual layout and mail template for a certificate. Referenced by award categories as their default certificate template.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `name` | `Char` | Required |
| `active` | `Boolean` | Default `True` |
| `page_format` | `Selection` | `a4` / `a5` (default: `a4`) |
| `page_orientation` | `Selection` | `portrait` / `landscape` (default: `portrait`) |
| `frame_image` | `Binary` | Background frame image (stored as attachment) |
| `mail_template_id` | `Many2one` → `mail.template` | Required, domain: `model_id.model = 'aps.certificate'` |
| `certificate_ids` | `One2many` → `aps.certificate` | Reverse of `certificate_template_id` |

---

## 8. `aps.certificate` — Certificate

**File:** `aps_certificate.py`  
**Model:** `aps.certificate`  
**Table:** `aps_certificate`  
**Inherits:** `mail.thread`, `mail.activity.mixin`  
**Order:** `certificate_date desc, id desc`

Represents an issued award certificate. Tracks the recipient, the award category, associated votes, and printing history. Integrates with mail tracking and activity management.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `name` | `Char` | **Computed** — `{partner.name} - {event}` |
| `partner_id` | `Many2one` → `res.partner` | Required, indexed, tracked |
| `subject_id` | `Many2one` → `aps.subject` | Tracked |
| `event` | `Char` | Required, tracked |
| `certificate_date` | `Date` | Default `today`, required, tracked |
| `award_category_id` | `Many2one` → `aps.award.category` | Tracked, `ondelete='restrict'` |
| `award_sub_category_id` | `Many2one` → `aps.award.sub.category` | Tracked, domain filtered by category |
| `academic_week_id` | `Many2one` → `aps.academic.week` | Tracked |
| `date_awarded` | `Date` | Tracked |
| `related_partner_ids` | `Many2many` → `res.partner` | Via `aps_certificate_related_partner_rel` |
| `related_vote_ids` | `Many2many` → `aps.award.vote` | Via `aps_certificate_vote_rel` — votes that generated this certificate |
| `certificate_template_id` | `Many2one` → `aps.certificate.template` | Required, tracked |
| `last_printed` | `Datetime` | Read-only, tracked |
| `home_class_id` | `Many2one` → `aps.class` | **Computed & editable** — student's home class |
| `notes` | `Text` | Extended notes |

### Page Dimensions

The model defines a static mapping of page format + orientation to mm dimensions:

| Format | Orientation | Width | Height |
|--------|------------|-------|--------|
| A4 | Portrait | 210mm | 297mm |
| A4 | Landscape | 297mm | 210mm |
| A5 | Portrait | 148mm | 210mm |
| A5 | Landscape | 210mm | 148mm |

### Key Methods

- **`_get_page_dimensions_style()`**: Returns CSS `width: X; height: Y;` string for the certificate's template format/orientation.

- **`_get_certificate_frame_data_uri()`**: Converts the template's `frame_image` (binary/base64) into a `data:` URI. Handles double-encoded base64 and detects MIME type (PNG, JPEG, or SVG).

- **`_render_certificate_body_html()`**: Renders the certificate's body HTML using the template's `mail_template_id`. Uses `_generate_template()` and wraps the result in `Markup`.

- **`action_print_certificate()`**: 
  1. Updates `last_printed` to current datetime.
  2. Selects the correct PDF report action based on `page_format` + `page_orientation` (4 combinations: A4/A5 × portrait/landscape).
  3. Returns the report action for the certificate.

---

## 9. `aps.award.voter.wizard` — Add People Voters Wizard (Transient)

**File:** `aps_award_voter_wizard.py`  
**Model:** `aps.award.voter.wizard` (TransientModel)

A wizard dialog that allows adding multiple `res.partner` records as eligible voters to a vote round. Merges new partner IDs into the existing `eligible_voters` JSON dict, preserving order and deduplicating.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `vote_round_id` | `Many2one` → `aps.award.vote.round` | Required, `ondelete='cascade'` |
| `partner_ids` | `Many2many` → `res.partner` | Via `aps_award_voter_wizard_partner_rel` |

### Method

- **`action_confirm()`**: Merges selected partner IDs into the round's `eligible_voters["partner_ids"]` list, preserving existing entries and deduplicating.

---

## 10. `aps.award.candidate.wizard` — Add Eligible Candidates Wizard (Transient)

**File:** `aps_award_candidate_wizard.py`  
**Model:** `aps.award.candidate.wizard` (TransientModel)

A wizard dialog for adding eligible candidates to a vote round. Supports three modes: adding by levels, by subject categories, or by specific students.

### Fields

| Field | Type | Details |
|-------|------|---------|
| `vote_round_id` | `Many2one` → `aps.award.vote.round` | Required, `ondelete='cascade'` |
| `mode` | `Selection` | `level` / `category` / `student` |
| `level_ids` | `Many2many` → `aps.level` | When mode = `level` |
| `category_ids` | `Many2many` → `aps.subject.category` | When mode = `category` |
| `student_ids` | `Many2many` → `aps.student` | When mode = `student` |

### Method

- **`action_confirm()`**: Based on `mode`, merges selected records into the round's `eligible_candidates` JSON dict under the appropriate key (`level_ids`, `subject_category_ids`, or `student_ids`), preserving order and deduplicating.

---

## 11. `aps.award.vote.round.mass.update.wizard` — Mass Update Vote Rounds Wizard (Transient)

**File:** `aps_award_vote_round_mass_update_wizard.py`  
**Model:** `aps.award.vote.round.mass.update.wizard` (TransientModel)

A wizard that allows bulk-updating multiple vote rounds simultaneously. Each field has a corresponding `update_<field>` boolean toggle and a `<field>_value` field. Only enabled fields are applied.

### Fields (pattern: `update_X` boolean + `X_value`)

| Toggle | Value Field | Type |
|--------|------------|------|
| `update_name` | `name_value` | `Char` |
| `update_description` | `description_value` | `Text` |
| `update_short_description` | `short_description_value` | `Text` |
| `update_color` | `color_value` | `Char` (default: `#5c1ea8`) |
| `update_datetime_start` | `datetime_start_value` | `Datetime` |
| `update_datetime_end` | `datetime_end_value` | `Datetime` |
| `update_status` | `status_value` | `Selection` (draft/open/closed/finalised) |
| `update_recurring_days` | `recurring_days_value` | `Integer` |
| `update_award_category_id` | `award_category_id_value` | `Many2one` → `aps.award.category` |
| `update_award_sub_category_id` | `award_sub_category_id_value` | `Many2one` → `aps.award.sub.category` (domain filtered by category) |
| `update_academic_week_id` | `academic_week_id_value` | `Many2one` → `aps.academic.week` |
| `update_tag_ids` | `tag_ids_value` | `Many2many` → `aps.award.tag` |
| `update_voting_set_ids` | `voting_set_ids_value` | `Many2many` → `aps.award.voting.set` |
| `update_round_manager_ids` | `round_manager_ids_value` | `Many2many` → `res.partner` |

### Method

- **`action_update()`**: 
  1. Validates that rounds are selected.
  2. Builds an `updates` dict from all enabled toggle/value pairs.
  3. Raises `UserError` if no updates are selected.
  4. Calls `write(updates)` on all selected rounds.
  5. Displays a success notification with the count of updated rounds.

---

## Data Flow Summary

```
aps.award.tag ─────────────────────────────────────────────────────────────┐
                                                                           │
aps.award.sub.category ──── belongs to ──── aps.award.category ── tags ────┘
                                                 │
                                    ┌────────────┼────────────┐
                                    │            │            │
                         certificate_template   levels      terms
                                    │
                    aps.award.voting.set ── rounds ── aps.award.vote.round
                         │                                    │
                         │                    ┌───────────────┼───────────────┐
                         │                    │               │               │
                         │           eligible_voters   eligible_candidates   rules
                         │              (JSON)            (JSON)            (JSON)
                         │                    │
                         └── aps.award.vote ──┘
                                    │
                          (selected votes create)
                                    │
                          aps.certificate ─── uses ─── aps.certificate.template
                                    │
                          (mail template renders PDF)
```

### Lifecycle Flow

1. **Setup:** Create tags → Create award categories (with sub-categories, tags, certificate template) → Create voting sets (optional grouping).
2. **Round Creation:** Create a vote round, assign it to a category, configure eligible voters (by staff, levels, subject categories, departments), configure eligible candidates, set rules.
3. **Open Round:** `action_open()` resolves all eligible voters and creates `aps.award.vote` records for each.
4. **Voting:** Voters cast their votes via the portal or backend; vote state transitions from `open` to `submitted`.
5. **Close Round:** `action_close()` stops further voting.
6. **Finalise:** `action_finalise()` marks the round complete.
7. **Certificate Generation:** From the vote analysis dashboard, select winning votes and use `create_certificate_from_selected_votes()` to generate an `aps.certificate`.
8. **Print:** `action_print_certificate()` renders the PDF via the configured template and mail template.