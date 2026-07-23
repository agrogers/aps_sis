# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**APEX - Academic Progress and Excellence** (`aps_sis`) is an Odoo 18 Community Edition module that manages academic tasks, student progress, resource hierarchies, submissions, grading, AI-assisted marking, and awards.

## Architecture

- **Main Odoo**: `d:\Dev\Odoo\mvis1B` (Standard Odoo 18 installation)
- **Custom Addons**: `d:\git\odoo_B_custom_addons\aps_sis` (This module)
- **Database**: `mvis1B` (Odoo 18 Community)

### Key Models
- `aps.resources` — Core resource model (homework, exams, lessons). Inherits `mail.thread`, `mail.activity.mixin`
- `aps.resource.submission` — Student submissions for resources
- `aps.resource.task` — Assignment tasks linking students to resources
- `aps.subject` / `aps.subject.category` — Subject and category management
- `aps.student` / `aps.student.class` — Student enrollment
- `aps.ai.model` / `ai_prompts` — AI-assisted marking infrastructure
- `aps.resource.tags` — Resource tagging with hierarchy display support

### Module Structure
```
aps_sis/
├── models/           # Python models and business logic
│   └── resources/    # Resource-specific models (model.py, actions.py)
├── views/            # XML view definitions
│   └── resources/    # Resource-specific views
├── static/src/
│   ├── components/   # OWL 2 client-action components (main UI)
│   ├── js/           # Standalone JS widgets and utilities
│   ├── xml/          # QWeb templates for widgets
│   ├── css/          # Stylesheets
│   └── lib/          # Third-party libraries (chart.js, slickgrid)
├── security/         # Access groups and ir.model.access
├── wizard/           # Wizard models and views
├── reports/          # PDF report templates
├── data/             # Cron jobs, email templates, seed data
└── tests/            # Python unit tests
```

## Development Patterns

### OWL 2 Components (Odoo 18)
- **No** `/ @odoo-module */` tags, `odoo.define()`, or `require()` — use native ES modules
- **No** `owl="1"` flags — all templates are OWL 2 by default
- **Import** `markup` from `@odoo/owl` (NOT `@web/core/utils/markup`)
- **Register** client actions via `registry.category("actions").add("tag_name", ComponentClass)`
- **Register** view widgets via `registry.category("view_widgets").add("name", ComponentClass)`
- Assets are auto-discovered via `components/**` wildcards in `__manifest__.py`

### Python/ORM
- Always use `@api.model_create_multi` for bulk `create()` methods
- Use `@api.depends` explicitly for computed fields
- Prefer ORM over raw SQL (`self.env.cr.execute`)
- HTML fields return `Markup` objects; wrap with `from markupsafe import Markup` when building custom HTML

### XML Views
- Use `<list>` not `<tree>` (deprecated)
- No `attrs=` or `states=` — use inline expressions (`invisible="condition"`)
- Use `column_invisible="True"` to hide entire list columns
- Binding views via `ir.actions.act_window.view` records

## Key Files

| File | Purpose |
|------|---------|
| `models/resources/model.py` | Core `aps.resources` field definitions |
| `models/resources/actions.py` | All RPC methods, hierarchy data, AI actions |
| `views/aps_sis_menu.xml` | APEX app menu structure |
| `__manifest__.py` | Module metadata, dependencies, asset registration |

## Testing

- Python tests in `tests/` directory
- Run: `python odoo-bin -d mvis1B -u aps_sis --test-tags=/aps_sis`
- Module upgrade: `python odoo-bin -d mvis1B -u aps_sis --stop-after-init`