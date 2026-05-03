# `score_contributes_to_parent` Field

**Model:** `aps.resources`  
**File:** `models/aps_resources/model.py`

## Definition

```python
score_contributes_to_parent = fields.Boolean(
    string='Contributes to Parent Score',
    default=True,
    help="When enabled, this resource's score is included in the parent resource's total score calculation.",
)
```

A boolean flag on a resource that controls whether its child submissions are included when a parent resource's score is automatically calculated from its children.

---

## Behaviour

- **Default:** `True` — all resources contribute to their parent's score unless explicitly opted out.
- When `True`, child submissions for this resource are summed into the parent's `auto_score` calculation.
- When `False`, this resource's submissions are excluded from the parent total, but the resource itself still exists and can be submitted and marked normally.
- If **no** contributing children remain after filtering, the parent score recalculation is skipped entirely.

---

## How Parent Recalculation is Triggered

### On field change (`write()` override)

**File:** `models/aps_resources/overrides.py`

When `score_contributes_to_parent` is written (toggled on or off), the `write()` override:

1. Finds all parent resources linked via `parent_ids`.
2. Searches for parent submissions where `auto_score = True`.
3. Calls `_recalculate_score_from_children()` on those submissions immediately.

```python
if 'score_contributes_to_parent' in vals:
    parent_resources = self.mapped('parent_ids')
    if parent_resources:
        parent_submissions = self.env['aps.resource.submission'].search([
            ('resource_id', 'in', parent_resources.ids),
            ('auto_score', '=', True),
        ])
        if parent_submissions:
            parent_submissions._recalculate_score_from_children()
```

### During score recalculation (`_recalculate_score_from_children()`)

**File:** `models/submissions/auto_score.py`

When a parent submission recalculates its score from children, contributing children are filtered first:

```python
contributing_children = child_resources.filtered(lambda r: r.score_contributes_to_parent)
if not contributing_children:
    continue
```

The guard also requires that **every contributing child** has at least one `submitted` or `complete` submission before the parent score is updated — preventing partial/premature totals.

---

## UI

| Location | Detail |
|---|---|
| Resource form view | `boolean_toggle` widget, only visible when `parent_ids` is set (`invisible="not parent_ids"`) |
| Mass update wizard | Can bulk-toggle the flag across many resources at once; triggers `write()` which fires the recalculation |

**File:** `views/aps_resources_views.xml`

```xml
<field name="score_contributes_to_parent" widget="boolean_toggle" invisible="not parent_ids"/>
```

---

## Related Files

| File | Role |
|---|---|
| `models/aps_resources/model.py` | Field definition |
| `models/aps_resources/overrides.py` | `write()` override — triggers parent recalc on change |
| `models/submissions/auto_score.py` | `_recalculate_score_from_children()` — respects the flag when summing |
| `models/aps_resource_mass_update_wizard.py` | Bulk update support |
| `views/aps_resources_views.xml` | Form UI toggle |
| `views/aps_resource_mass_update_wizard_views.xml` | Mass update wizard UI |
| `tests/test_aps_resource_submission.py` | Tests covering toggle behaviour and parent score updates |

---

## Test Coverage

Tests at `tests/test_aps_resource_submission.py` (line ~299) verify:

- Setting `score_contributes_to_parent = False` on a child resource immediately removes that child's score from the parent total.
- Re-enabling it (`True`) immediately re-includes the score.
- Duplicate child submissions (same label, same resource) use the **highest** score to avoid distorting the total.

---

# `auto_score` Field

**Model:** `aps.resource.submission`  
**File:** `models/submissions/auto_score.py`

## What it does

When `auto_score = True` on a parent submission, the submission's `score` and `answer` fields are automatically calculated by summing the scores of its children's submissions. The result is written back to the parent submission along with an HTML summary in the `answer` field.

## Where to set it

Submission form view → *(details tab)* → **Other Details** group → **Auto Score** toggle (`boolean_toggle` widget).

## How it is triggered

Two entry points both ultimately call `_recalculate_score_from_children()`:

| Trigger | File | How |
|---|---|---|
| Child submission score changes | `auto_score.py` → `_check_and_update_parent_score()` | Finds parent submissions with `auto_score=True` and recalculates |
| `score_contributes_to_parent` toggled on resource | `aps_resources/overrides.py` → `write()` | Finds parent submissions with `auto_score=True` and recalculates |

## Conditions that block recalculation

All of the following must be true for a parent submission to be updated. If any condition fails, that parent record is **silently skipped**.

| # | Condition | What blocks it |
|---|---|---|
| 1 | `record.auto_score == True` | The parent submission does not have Auto Score enabled |
| 2 | `record.resource_id.child_ids` is non-empty | The parent resource has no child resources at all |
| 3 | At least one child resource has `score_contributes_to_parent = True` | All children are opted out of contributing |
| 4 | Every contributing child has at least one submission in state `submitted` or `complete` for the same student (and same `submission_label` if the parent has one) | One or more contributing children haven't been submitted yet — the parent won't update until **all** children are in |
| 5 | At least one child submission exists in the search results | No child submission records found |
| 6 | `total_out_of > 0` | If the combined `out_of_marks` across all children is zero, `new_score` is set to `sentinel_zero` (treated as no score) rather than `0.0` |

## Scoring logic

1. Child submissions are fetched for the same `student_id` and (if set) `submission_label`.
2. **Deduplication:** if a child resource has multiple submissions with the same label, only the one with the **highest score** is used.
3. Results are sorted by `submission_order`, then `submission_name`.
4. `total_score` and `total_out_of` are summed across deduplicated children.
5. An HTML answer summary is generated in the format:  
   `Child Name) Score: X/Y` per line, followed by `TOTAL: X/Y`.
6. The parent submission is written with `score`, `answer`, and `auto_score=True` (to prevent the `write()` override from clearing the flag).

## `_check_and_update_parent_score()`

Called after a child submission's score changes. For each parent resource linked via `resource_id.parent_ids`:

1. Finds the parent task for the same student.
2. Finds the parent submission, preferring one matching the child's `submission_label`.
3. If `parent_submission.auto_score` is `True`, calls `_recalculate_score_from_children()`.

## Related files

| File | Role |
|---|---|
| `models/submissions/auto_score.py` | Core logic — `_recalculate_score_from_children()`, `_check_and_update_parent_score()` |
| `models/aps_resources/overrides.py` | Triggers recalc when `score_contributes_to_parent` changes |
| `views/aps_resource_submission_views.xml` | `auto_score` toggle on the submission form (Other Details group) |
