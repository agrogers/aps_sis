# APS SIS Copilot Instructions

## Client-action navigation

When an OWL component opens a filtered `aps.resource.submission` list from a KPI, chart, table cell, or badge:

- Use the Odoo action service obtained with `useService("action")`.
- Prefer an explicit action dictionary when applying a dynamic domain:

```javascript
this.action.doAction({
    type: "ir.actions.act_window",
    name: "Filtered Submissions",
    res_model: "aps.resource.submission",
    views: [[false, "list"], [false, "form"]],
    domain: submissionDomain,
});
```

- Do not rely on an XML action ID while expecting `domain` or `additionalContext.active_domain` to filter the opened list. The existing submission action has context and search-panel defaults that can override or obscure the intended cell domain.
- The domain must include every dimension represented by the clicked cell: student, submission state, date/week range, resource type, and subject. For subjects, include both explicit submission subjects and resource subjects when the data model permits either:

```javascript
[
    ["student_id", "=", studentId],
    ["state", "in", ["submitted", "complete"]],
    ["date_submitted", ">=", weekStart],
    ["date_submitted", "<=", weekEnd],
    ["type_id", "=", resourceTypeId],
    "|",
    ["subjects", "in", [subjectId]],
    ["resource_id.subjects", "in", [subjectId]],
]
```

- For total cells, use the same domain dimensions but the selected overall date range instead of one week.
- Do not use only `[("student_id", "=", studentId)]`; that opens every submission for the student.
- Do not pass a domain only through `additionalContext.active_domain` unless the target action is known to consume it. Test the resulting list view and confirm the visible records match the clicked cell count.

## OWL callback context

Template callbacks such as `() => onCellClick(cell)` or event handlers can lose component context in this codebase. Bind handlers that access `this.state`, `this.orm`, or `this.actionService` in `setup()`:

```javascript
this.onCellClick = this.onCellClick.bind(this);
this.toggleType = this.toggleType.bind(this);
```

Validate both the action call and the resulting domain after changes.

## Weekly submission results

The weekly submission grid is a plain OWL/HTML grid in `static/src/components/weekly_submission_results/`, not SlickGrid. Percentage cells use the reusable `PercentPie` component. Resource-type filters distinguish `null` (All), `[]` (None), and an array of IDs (subset). Persisted facts are rebuilt from `aps.resource.submission` records.
