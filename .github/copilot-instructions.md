# Odoo Custom Addons Development Guide

## Architecture Overview
This workspace contains an Odoo 18 ERP system with OpenEducat education modules and custom addons. Core structure:
- **Main Odoo**: `c:\Dev\Odoo\mvis20251208` (standard Odoo installation)
- **Custom Addons**: `c:\Git\Odoo_Custom_Addons\_live` (POS, accounting, SIS extensions)
- **OpenEducat**: `C:\Git\Odoo_3rd_Party_Addons\openeducat_erp-18.0` (education modules)

Key data flows: Submissions → Tasks → Resources (SIS workflow); Invoices → POS → Accounting (business flow).

## Critical Workflows
- **Start Server**: `cd C:\Dev\Odoo\mvis20251208; python odoo-bin -c odoo.conf -d odoo18v20251208`
- **Upgrade Module**: `python odoo-bin -c odoo.conf -d odoo18v20251208 -u <module_name> --stop-after-init`
- **Debug**: Enable `dev_mode = all` in `odoo.conf` for full debugging tools
- **Assets**: Don't restart server after model/CSS/JS changes; remind me to restart the debug environment

## Project Conventions
- **Addon Structure**: `__manifest__.py` defines dependencies, data, assets; models in `models/`, views in `views/`, static in `static/src/`
- **Related Fields**: Use `fields.Many2one/related` for model links (e.g., `resource_id = fields.Many2one('aps.resources', related='task_id.resource_id')`)
- **State Machines**: Implement workflow states with `selection` fields and `tracking=True` (e.g., assigned → submitted → complete in submissions)
- **Compute Fields**: Auto-calculate derived data (e.g., `result_percent` from score/marks); use `@api.depends()` decorators
- **Permissions**: Check user roles via `self.env.user` or linked employee/faculty records (e.g., `self._get_current_faculty()`)
- **HTML Fields**: Use `widget="html"` in views for rich text (answers, feedback)
- **Assets Loading**: Add CSS/JS to `'web.assets_backend'` in manifest for backend UI

## Integration Patterns
- **OpenEducat Dependency**: Custom addons depend on `'openeducat_core'`; inherit from `op.faculty`, `op.student` models
- **Cross-Addon Communication**: Use related fields and computed updates (e.g., task state syncs with submission states)
- **External APIs**: Minimal; focus on internal Odoo ORM operations
- **Database**: PostgreSQL; use Odoo ORM for all queries (avoid raw SQL)

## Examples
- **Model Relations**: `aps_resource_submission.py` shows task-resource-student linking with computed display names
- **Workflow Actions**: `action_mark_complete()` validates faculty permissions before state changes
- **View Updates**: Add fields to XML views with `attrs` for conditional visibility (e.g., `{'invisible': [('state', 'not in', ('submitted', 'complete'))]}`)
- **Asset Organization**: Group related CSS in dedicated files (e.g., `openeducat.css` for theme-specific styles)

## Common Pitfalls
- Always upgrade modules after manifest changes
- Use absolute paths for file operations
- Test permission checks in multi-user scenarios
- Clear browser cache after asset updates


# Copilot Instructions — Odoo Community Edition v18+

This repository targets **Odoo Community Edition v18**.
Assume **v18 behaviour by default**.
If a feature differs between versions, use **v18 syntax and architecture only**.

---

## XML Views

- Use `<list>` instead of `<tree>`
- Do NOT use `<tree>` (deprecated)
- Do NOT use `attrs=` or `states=`
- Use direct boolean expressions for UI logic:
  - `invisible="condition"`
  - `readonly="condition"`
  - `required="condition"`
- Expressions must be Python-like:
  - `and`, `or`, `not`
  - Field names directly (no tuples or domains)
- Column visibility must use:
  - `optional="show"` or `optional="hide"`
- XPath removals or modifications of buttons must use:
  - `optional="1"`
- Invalid XPath expressions must not be produced
- Do not rely on `context` for UI visibility logic

### Binding Specific Views to Actions

To force an action to use specific list and form views (e.g., when clicking a list row should open a particular form view), use `ir.actions.act_window.view` records:

```xml
<record id="action_my_model" model="ir.actions.act_window">
    <field name="name">My Records</field>
    <field name="res_model">my.model</field>
    <field name="view_mode">list,form</field>
</record>

<!-- Bind specific views to the action -->
<record id="action_my_model_view_list" model="ir.actions.act_window.view">
    <field name="sequence">1</field>
    <field name="view_mode">list</field>
    <field name="view_id" ref="view_my_model_list"/>
    <field name="act_window_id" ref="action_my_model"/>
</record>

<record id="action_my_model_view_form" model="ir.actions.act_window.view">
    <field name="sequence">2</field>
    <field name="view_mode">form</field>
    <field name="view_id" ref="view_my_model_form"/>
    <field name="act_window_id" ref="action_my_model"/>
</record>
```

Do NOT use `<field name="views">` or `eval="[(ref(...), 'list')]"` patterns — they are not standard v18 syntax.

---

## Reports

### Paper Formats and Page Layout

For PDF reports, control page margins, orientation, and headers using `report.paperformat` records instead of CSS `@page` rules:

```xml
<!-- Define custom paper format -->
<record id="paperformat_custom_report" model="report.paperformat">
    <field name="name">Custom Report Format</field>
    <field name="format">A4</field>
    <field name="orientation">Portrait</field>
    <field name="margin_top">0</field>        <!-- Top margin in mm -->
    <field name="margin_bottom">0</field>    <!-- Bottom margin in mm -->
    <field name="margin_left">10</field>     <!-- Left margin in mm -->
    <field name="margin_right">10</field>    <!-- Right margin in mm -->
    <field name="header_line" eval="False"/> <!-- Disable header line -->
    <field name="header_spacing">0</field>   <!-- Header spacing in mm -->
</record>

<!-- Reference in report action -->
<record id="report_action" model="ir.actions.report">
    <field name="paperformat_id" ref="module.paperformat_custom_report"/>
    <!-- ... other fields ... -->
</record>
```

**Important**: Define paperformat records **before** report actions that reference them in XML files to avoid "External ID not found" errors.

### Layout Templates

- Use `web.basic_layout` for clean reports without headers/footers
- Use `web.external_layout` for reports with company headers/footers
- Avoid CSS-based header manipulation; use paperformat settings instead

### QWeb Templates

- Use `t-set` variables for conditional logic and data processing
- Access report data via the `data` variable passed from wizards
- Use `loop.index` for iteration counters (available in t-foreach loops)
- For page breaks, use `<div style="page-break-before: always;"></div>`

---

## JavaScript / Frontend

- Use **ES modules only**
- Do NOT use:
  - `odoo.define`
  - `require()`
  - legacy `web.*` imports
- Use **OWL 2 components**
- Do NOT use:
  - legacy widgets
  - `extend()`
  - `this._super()`
- Use modern class-based inheritance:
  - `class X extends Component`
- Do NOT include `/** @odoo-module */` (removed in v18)

---

## Point of Sale (POS)

- Use **Odoo v18 POS architecture only**
- POS code must be OWL 2
- Do NOT use:
  - `Registries.Component.extend`
  - legacy screen inheritance
  - monkey-patching POS globals
- Do NOT use legacy `models.js` or `models.load_models`
- POS data must be loaded via modern loaders/services
- Assume strict module imports and explicit dependencies

---

## Python / ORM

- Prefer `@api.model_create_multi` for `create()`
- Compute fields must declare **exact dependencies**
- Related stored fields require correct dependency chains
- Do NOT rely on implicit recomputation
- Avoid over-broad `@api.depends`
- Community Edition APIs only (no Enterprise-only features)

---

## Deprecated / Legacy Patterns (DO NOT USE)

- **`<tree>`** — *Do not use.* Use `<list>` instead (with `editable="top"` when inline editing is needed). - `attrs=`
- `states=`
- `odoo.define`
- `require('web...')`
- `Registries.Component.extend`
- `models.load_models`
- `this._super()`
- `@odoo-module` comment (v18)

> Tip: Add a quick grep/linter check for the `<tree>` tag in CI or pre-commit hooks to prevent regressions.

---

## General Rules

- Prefer explicit, declarative syntax over implicit behaviour
- Avoid clever hacks or backward compatibility code
- If uncertain about an API or pattern, say so instead of guessing
- Do NOT generate pre-v17 or pre-v18 code

To create a professional and beautiful Odoo v18 dashboard, you can use the following detailed prompt for an AI. This prompt is structured to leverage Odoo's modern **OWL (Odoo Web Library)** framework and best practices for creating responsive, data-driven custom dashboards.

---

### v18 Dashboard with OWL

**Role:** You are a senior Odoo v18 Developer.
**Objective:** Create a modern, responsive custom dashboard for Odoo v18 using the OWL framework. The dashboard should include dynamic KPI cards, interactive charts, and a global date filter.

#### 1. Technical Requirements & Architecture

* 
**Framework:** Use **OWL (Odoo Web Library)** and standard Odoo v18 client actions.


* 
**Services:** Utilize `orm` for data fetching and `action` for drill-down navigation.


* 
**Styling:** Use Odoo's built-in Bootstrap classes (e.g., `o_dashboard`, `row`, `col-lg-3`) and standard utility classes for shadows and spacing.


* 
**Components:** Implement a parent `Dashboard` component that manages state and sub-components for `KpiCard` and `ChartRenderer`.



#### 2. Layout & Views

* 
**Container:** A scrollable `div` with `vh-100`, `overflow-auto`, and a muted background (`bg-muted`).


* 
**Header:** A top section containing the dashboard title (e.g., "Sales Overview") and a global filter dropdown (Options: Last 7 Days, 30 Days, 90 Days, 365 Days).


* **KPI Section:** A row of four cards displaying key metrics.
* 
**Chart Section:** A grid layout (using Bootstrap `row` and `col-lg-6`) to display various charts like Bar, Line, Pie, and Donut charts.



#### 3. Data Handling & Fields

* 
**State Management:** Use `useState` to manage dynamic data for KPIs and charts based on the selected filter.


* **ORM Methods:**
* Use `searchCount` for simple numeric KPIs (e.g., total quotations).


* Use `readGroup` for aggregated data like total revenue or average order value.




* **Logic:**
* Calculate percentage changes by comparing the current period data with the previous period (e.g., current 30 days vs. previous 30 days).


* Format currency and large numbers (e.g., dividing by 1000 and adding a "k" suffix for thousands).





#### 4. Interaction & Drill-down

* 
**Filters:** When a user selects a date range, all KPIs and charts must automatically update via an `onchange` event that triggers new ORM calls.


* 
**Action Service:** Clicking on a KPI card or chart element should redirect the user to the corresponding model's list or pivot view, filtered by the active date range.



#### 5. Code Structure Deliverables

Please provide:

1. 
****manifest**.py**: Including dependencies on `web`, `sales`, and `board`.


2. 
**XML Template**: Clean QWeb templates for the dashboard and its sub-components.


3. **JavaScript (OWL)**:
* The main dashboard component with `onWillStart` for initial data loading.


* Logic to handle date calculations using the standard Odoo libraries.


* A generic `ChartRenderer` component that integrates with `Chart.js` (Odoo's default library).





---

### Key Development Tips for Odoo v18:

* 
**Reuse Components:** Define a single `KpiCard` component and pass different props (title, value, percentage, icon) to keep the code DRY.


* 
**Dynamic Styling:** Change the color of percentage tags (Success/Green for positive, Danger/Red for negative) dynamically based on the value.


* 
**Performance:** Use `onWillStart` to fetch all necessary data before the component mounts to ensure a smooth user experience.