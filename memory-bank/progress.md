# Progress — APEX

## Completed
- [x] Module structure and architecture established
- [x] Core `aps.resources` model with hierarchy support
- [x] Resource submission and grading workflow
- [x] AI-assisted marking infrastructure
- [x] Subject/category management
- [x] Award and certificate system
- [x] **Course Explorer** — Full implementation:
  - [x] Python RPC methods (`get_course_explorer_data`, `get_course_explorer_subject_categories`, `_resolve_notes`)
  - [x] OWL 2 component with recursive tree nodes
  - [x] Split-pane layout with collapsible sidebar
  - [x] Subject category dropdown filter
  - [x] HTML content rendering via `markup()` from `@odoo/owl`
  - [x] Content ordering matching tree traversal (depth-first, sequence-based)
  - [x] Bidirectional scroll sync (IntersectionObserver)
  - [x] localStorage persistence (expand/collapse, scroll, category, sidebar)
  - [x] Structural parent inclusion (parents with notes='no' shown when children have notes)
  - [x] Inherited content deduplication (use_parent resolves up chain)
  - [x] Sidebar toggle button always visible (moved outside left pane)
  - [x] Tested and verified working on localhost:8070

## In Progress
- None

## Known Issues
- Some image 500 errors in content (pre-existing broken image links, not code-related)