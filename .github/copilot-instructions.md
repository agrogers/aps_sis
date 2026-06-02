# Odoo Custom Addons Development Guide

## Architecture Overview
This workspace contains an Odoo 18 ERP system with OpenEducat education modules and custom addons. Core structure:
- **Main Odoo**: `c:\Dev\Odoo\mvis20251208` (standard Odoo installation)
- **Custom Addons**: `c:\Git\Odoo_Custom_Addons\_live` (POS, accounting, SIS extensions)
- **OpenEducat**: `C:\Git\Odoo_3rd_Party_Addons\openeducat_erp-18.0` (education modules)

Key data flows: Submissions → Tasks → Resources (SIS workflow); Invoices → POS → Accounting (business flow).

## wkhtmltopdf Full-Page Background Images — What Works and What Doesn't

wkhtmltopdf (used by Odoo for PDF reports) has significant CSS rendering limitations compared to browsers.
**Do not re-attempt the approaches listed as broken below.**

### ❌ BROKEN — Do NOT use these

| Approach | Why it fails |
|---|---|
| `background-image: url(data:...)` + `background-size: cover` | Image disappears entirely |
| `background-image: url(data:...)` + `background-size: 100% 100%` | Squashes image, ignores aspect ratio |
| `background-image: url(data:...)` + `background-size: contain` | Doesn't fill the page |
| `<img position: absolute; width: 100%; height: 100%>` in a content-driven parent | Height resolves against content height, not paper height — image shrinks with less content |
| `<img position: fixed; width: 100%; height: 100%>` | Percentages on `fixed` resolve unreliably; image disappears |
| `<img position: fixed>` with explicit mm `width` + `height` directly on the img | wkhtmltopdf won't stretch `<img>` against its natural aspect ratio; fills height and leaves horizontal gaps |
| `<img position: fixed>` inside a parent with `overflow: hidden` | `overflow: hidden` clips `position: fixed` children in wkhtmltopdf |

### ✅ CORRECT approach — `position: fixed` with explicit paper dimensions in mm

```python
# In the model, provide exact paper dimensions based on format+orientation:
_PAGE_DIMENSIONS_MM = {
    ('a4', 'portrait'):   ('210mm', '297mm'),
    ('a4', 'landscape'):  ('297mm', '210mm'),
    ('a5', 'portrait'):   ('148mm', '210mm'),
    ('a5', 'landscape'):  ('210mm', '148mm'),
}

def _get_page_dimensions_style(self):
    self.ensure_one()
    tmpl = self.certificate_template_id
    w, h = self._PAGE_DIMENSIONS_MM.get(
        (tmpl.page_format, tmpl.page_orientation or 'portrait'), ('210mm', '297mm')
    )
    return f'width: {w}; height: {h};'
```

```xml
<!-- In the QWeb template — fixed-positioned div sized to exact paper mm, img fills it -->
<div t-attf-style="position: fixed; top: 0; left: 0; #{o._get_page_dimensions_style()} z-index: 0;">
    <img t-attf-src="#{o._get_certificate_frame_data_uri()}"
         style="width: 100%; height: 100%;"/>
</div>
<!-- Content sits on top -->
<div style="position: relative; z-index: 1; ...">...</div>
```

**Key rules:**
- `position: fixed` must be on the **wrapper `<div>`**, NOT on the `<img>` itself — wkhtmltopdf won't stretch `<img>` against its natural aspect ratio even with explicit dimensions.
- The `<img>` inside uses `width: 100%; height: 100%` to fill the fixed div.
- Must use **absolute mm dimensions** (e.g. `width: 297mm; height: 210mm`) on the div, NOT `width: 100%; height: 100%`.
- The parent of the fixed div must NOT have `overflow: hidden`.
- Content layer needs `position: relative; z-index: 1` to render above the image.

### Binary field / data URI notes
- Odoo `fields.Binary` stores data as base64. When read from the ORM it is already base64-encoded.
- `fields.Image` via the UI may double-encode: the field value is base64 of a base64 string.
  - Detect by decoding once and checking if result is itself valid base64 that starts with PNG/JPEG magic bytes.
- PNG magic: `b'\x89PNG\r\n\x1a\n'` (8 bytes)
- JPEG magic: first 2 bytes `b'\xff\xd8'`
- Use `data:image/png;base64,...` or `data:image/jpeg;base64,...` accordingly; do NOT hardcode `image/svg+xml`.


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

### RGB Color Picker
- Use `widget="color"` on a `fields.Char` to get a full RGB color picker (hex value stored as a string, e.g. `#5c1ea8`).
- Do **NOT** use `widget="color_picker"` — that is Odoo's integer dot-color selector, not an RGB picker.
- Example (correct):
  ```python
  color = fields.Char(string='Color', default='#5c1ea8')
  ```
  ```xml
  <field name="color" widget="color"/>
  ```

### List View Field Attributes
- **NEVER use `style=` on a `<field>` element inside a `<list>` view** — Odoo's RNG validator rejects it and will raise a `ValidationError` at load time.
- To control image size in list views, use Odoo's built-in CSS helper classes on the `class=` attribute:
  - `o_image_24_max` — 24 px
  - `o_image_32_max` — 32 px
  - `o_image_48_max` — 48 px
  - `o_image_64_max` — 64 px
- Example (correct):
  ```xml
  <field name="image_128" widget="image" class="o_image_24_max" optional="show"/>
  ```
- Example (WRONG — will fail validation):
  ```xml
  <field name="image_128" widget="image" style="width:24px;height:24px;" optional="show"/>
  ```

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

---

## AI Feedback Pipeline (`models/ai/`)

### Single source of truth for payload assembly

**Always use `_build_payload` from `ai_answer_base.py`** to assemble AI chat payloads.
Never create a standalone prompt-assembly method that reimplements section iteration, heading
formatting, system-message construction, or response-format injection.

| Path | How to call `_build_payload` |
|---|---|
| Generic (non-targeted) | `self._build_payload(prompts, dynamic_data, include_reasoning=..., response_format_fallback=PROMPT_RESPONSE_FORMAT_GENERIC)` |
| Targeted | `self._build_payload(prompts, dynamic_data, include_reasoning=...)` — uses the default `PROMPT_RESPONSE_FORMAT` |

Import `PROMPT_RESPONSE_FORMAT_GENERIC` from `.ai_answer_base` when calling from `ai_answer_generic.py`.

### Section keys

All valid `message_section` values are defined in `PROMPT_SECTION_ORDER` in `ai_answer_base.py`.
Do not add new hard-coded section strings outside that file.

| Key | Purpose |
|---|---|
| `system` | Overrides the system message (optional; defaults to `_build_system_content()`) |
| `ai_instructions` | Specific grading/feedback instructions |
| `maximum_mark` | Mark ceiling |
| `question` | Task question text |
| `model_answer` | Reference answer |
| `notes` | Additional notes for the AI |
| `detailed_feedback` | Targeted path only — prior-phase context |
| `additional_context` | Catch-all for any other context |
| `summary` | Generic path — brief overview prompt |
| `detailed_analysis` | Generic path — point-by-point prompt |
| `results_table` | Generic path — criteria/mark table prompt |
| `student_answer` | Student's submitted answer |
| `response_format` | JSON schema instruction (usually auto-injected from fallback) |

### Shared helpers in `ai_answer_base.py`

The following methods are defined **once** in the base and must **not** be duplicated
in `ai_answer_generic.py`, `ai_answer_targeted.py`, or any other mixin:

- `_build_payload` — payload assembly (see above)
- `_build_dynamic_section_data` — maps ctx dict → section-keyed dict
- `_build_system_content` — constructs default system message
- `_parse_structured_response` — JSON extraction from raw AI response
- `_extract_score` / `_extract_score_comment` — score parsing helpers
- `_normalize_feedback_html` — plain-text → HTML fallback
- `_html_to_text` — strips HTML tags for prompt injection

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