# Active Context — APEX

## Current Focus
Course Explorer feature — a split-pane client action for browsing course content.

## Recent Changes
- Created `course_explorer` client action with OWL 2 components
- Added Python RPC methods: `get_course_explorer_data()`, `get_course_explorer_subject_categories()`, `_resolve_notes()`
- Implemented bidirectional scroll sync with IntersectionObserver
- Fixed HTML rendering by importing `markup` from `@odoo/owl`
- Fixed content ordering to match tree traversal order
- Fixed sidebar toggle button visibility when collapsed
- Added structural parent inclusion for tree completeness

## Key Design Decisions
- Subject category dropdown filters resources (not individual subjects)
- Parent resources with `has_notes='no'` included in tree when children have notes
- No content shown until a subject category is selected
- Content sections collected during tree traversal (not sorted afterward)
- HTML wrapped in `markup()` for proper rendering via `t-out`
- `markup` imported from `@odoo/owl` (NOT `@web/core/utils/markup` — that module doesn't exist)

## Open Questions
- None currently — all features implemented and tested

## Active Working Files
- `models/resources/actions.py` — RPC methods for course explorer
- `static/src/components/course_explorer/course_explorer.js` — OWL component
- `static/src/components/course_explorer/course_explorer.xml` — QWeb template
- `static/src/components/course_explorer/course_explorer.css` — Styles
- `views/resources/aps_course_explorer_views.xml` — Action + menu