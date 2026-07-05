# Claude Instructions for Odoo v18

---
applyTo: '**'
---


# Odoo 18 Development Instructions

This workspace targets **Odoo Community Edition v18**. Assume **v18 native behavior by default**. If a pattern or syntax differs between versions, use **v18 architecture exclusively**.

---

## Architecture 

This workspace integrates an Odoo 18 ERP system with custom application addons.

* **Main Odoo**: `c:\Dev\Odoo\mvis???` (Standard core Odoo installation)
* **Custom Addons**: `c:\Git\Odoo_Custom_Addons\` (POS, accounting, and SIS extensions)


## General Development Principles

* **Search Visibility**: When adding database fields to models, always check if they belong in the corresponding `<search>` view to ensure user filterability.
* **Explicit Layouts**: Use the `optional="show"` or `optional="hide"` attributes in `<list>` views to give users runtime configuration authority.
* **Display Names**: Always implement model-level display configurations via a computed `display_name` field. **Never use the deprecated `name_get()` method.**
* **Manifest data ordering**: Files that define XML IDs must be listed **before** files that reference those IDs via `%(xml_id)d` in the `data` list. Odoo loads data files sequentially, and a `%(xml_id)d` reference fails with `ValueError: External ID not found` if the target XML ID hasn't been created yet.
* **Code Generation Guardrails**: Do NOT generate code using pre-v18 syntax. If uncertain about a new v18 API pattern, flag it as a limitation instead of speculating.

---

## XML Views

* Use `<list>` instead of `<tree>`. `<tree>` is officially deprecated.
* **Attributes Policy**: Never use `attrs=` or `states=`. Use direct, Python-like conditional expressions on field tags:
* `invisible="condition"`
* `readonly="condition"`
* `required="condition"`


* **Logical Evaluators**: Conditions must use clean logical terms (`and`, `or`, `not`) and evaluate field names directly (do not wrap expressions inside legacy tuple arrays or domain lists).
* **Column-Level vs Row-Level Visibility**:
* To hide an entire column in a list view conditionally, use `column_invisible="condition"`.
* Do NOT use `invisible="..."` on a field tag inside a `<list>` view if your intention is to hide the whole grid column.



### Security Groups — Dropdown vs Checkboxes

**Key rule:** Odoo renders groups as a **dropdown** when a category has a **clean linear inheritance chain** (each group implies the previous one). If the chain is broken or extra non-implied groups exist in the same category, Odoo falls back to **checkboxes**.

```xml
<!-- ✅ Renders as a dropdown: clean Student → Teacher → Manager chain -->
<record id="module_category_school" model="ir.module.category">
    <field name="name">School Management</field>
</record>

<record id="group_student" model="res.groups">
    <field name="name">Student</field>
    <field name="category_id" ref="module_category_school"/>
</record>

<record id="group_teacher" model="res.groups">
    <field name="name">Teacher</field>
    <field name="category_id" ref="module_category_school"/>
    <field name="implied_ids" eval="[(4, ref('group_student'))]"/>
</record>

<record id="group_manager" model="res.groups">
    <field name="name">Manager</field>
    <field name="category_id" ref="module_category_school"/>
    <field name="implied_ids" eval="[(4, ref('group_teacher'))]"/>
</record>
```

**Rules for dropdown:**
1. All groups in the category must form a **single linear chain** (A ← B ← C).
2. **No extra groups** in that category — any side-group (e.g. "Voting Token Access") that doesn't fit the chain forces checkboxes.
3. Move unrelated permission groups to `base.module_category_hidden` instead.

If the chain must include extra implied groups, merge them into Manager's `implied_ids` so they don't appear as separate entries in the category.

### RGB Color Picker

* Use `widget="color"` on a `fields.Char` field to instantiate a full Hex/RGB color picker.
* **Avoid `widget="color_picker"**` — that is Odoo’s legacy indexed integer dot selector.

```python
color = fields.Char(string='Color Code', default='#5c1ea8')

```

```xml
<field name="color" widget="color"/>

```

### List View Field Formatting Restrictions

* **NEVER use the `style=` attribute on a `<field>` element inside a `<list>` view.** The RNG schemas will reject it, throwing a `ValidationError` at module load time.
* To enforce explicit image sizing inside lists, utilize Odoo’s core CSS styling modifiers on the `class` attribute:
* `o_image_24_max` (24px) | `o_image_32_max` (32px) | `o_image_48_max` (48px) | `o_image_64_max` (64px)



```xml
<field name="image_128" widget="image" class="o_image_24_max" optional="show"/>

<field name="image_128" widget="image" style="width:24px;" optional="show"/>

```

### Image Field Handling

* Always structure binary image records utilizing `fields.Image`. Avoid using string-based types (`fields.Char`) to map structural graphics.
* **List Layouts**: Define thumbnails explicitly using the options dictionary attribute:
```xml
<field name="image_128" widget="image" options="{'size': [24, 24]}" optional="show"/>

```


* **Form Layouts**: Apply the native avatar class wrappers:
```xml
<field name="image_1920" widget="image" class="oe_avatar" options="{'preview_image': 'image_128'}"/>

```



### Binding Views to Actions

Force specific rendering hierarchies for view targets via explicit `ir.actions.act_window.view` bindings. Do not declare views inside inline evaluations or legacy structural properties.

```xml
<record id="action_custom_model" model="ir.actions.act_window">
    <field name="name">Records</field>
    <field name="res_model">custom.model</field>
    <field name="view_mode">list,form</field>
</record>

<record id="action_custom_model_list" model="ir.actions.act_window.view">
    <field name="sequence" eval="1"/>
    <field name="view_mode">list</field>
    <field name="view_id" ref="view_custom_model_list"/>
    <field name="act_window_id" ref="action_custom_model"/>
</record>

```

---

## JavaScript & Frontend Framework (OWL 2)

Odoo 18 treats javascript modules natively.

* **NO `/ @odoo-module */` tags**: This directive comment block is obsolete and has been entirely removed from the asset system pipelines in v18.
* **NO `odoo.define()` or `require()` calls**: Use native JavaScript `import` and `export` statements exclusively.
* **NO `owl="1"` flags**: All QWeb template XML structures located inside the static web bundles are treated as native OWL 2 components by default.

### OWL 2 Template Compilation Standards

* **Pure JavaScript in Templates**: Logic inside directives (`t-if`, `t-elif`, `t-esc`, `t-out`, `t-att`) compiles straight into client-side JS functions. **Python expressions (`not`, `and`, `or`) are invalid.**
* *Wrong*: `<t t-if="not record.active or record.hidden"/>`
* *Right*: `<t t-if="!record.active || record.hidden"/>`


* **Explicit Execution Scoping**: All attributes, internal configurations, methods, and component state hooks accessed inside templates must be explicitly mapped using their execution scope context (`this.` or `props.`).
* *Exception*: Iterative loop variables declared via `t-as` within a `t-foreach` block do not receive an explicit prefix.
* *Right*: `<div t-if="this.state.isVisible"><span t-out="props.title"/></div>`



### Event Directives (`t-on-*`)

* Do not supply un-invoked paths or foreign object references to event targets. Always hand the runtime handler an implicit local binding string or map it via a clean inline expression function wrapper.
* *Wrong*: `t-on-click="props.onCallback"`
* *Right*: `t-on-click="() => props.onCallback()"`
* *Right*: `t-on-click="handleButtonClick"` (where `handleButtonClick` is an explicit method on the local Component class)



---

## Point of Sale (POS)

The POS frontend engine has been fully rewritten for Odoo 18. **The legacy JS model infrastructure (`models.js` / `models.load_models`) no longer exists.**

* **Reactive Models**: Data layers and registries use a native, reactive Python-like class engine on the frontend.
* **Component Modifications**: Do not use `Registries.Component.extend`. Use native standard JS inheritance or use the patch utility system (`patch`) from `@web/core/utils/patch` to override components or services.
* Data fetching must utilize standard mock-sync engines or modern reactive services over explicit positional model mutations.

---

## Python & ORM Architecture

* **Multi-Record Operations**: Always decorate bulk model injections using the `@api.model_create_multi` method decorator over standard single-record iterations inside `create()`.
* **Computed Attributes**: Computed properties (`compute='_compute_field'`) must have robust `@api.depends` mappings detailing exact internal and related dependencies. Never rely on implicit recomputations.
* **Database Rules**: Write clean queries using the Odoo ORM mapping layers. Avoid raw SQL cursor injections (`self.env.cr.execute`) unless working with unique operational edge-cases.

---

## PDF Reports & wkhtmltopdf Engine

### Full-Page Background Graphics

The engine has major limitations rendering fluid CSS layouts across print pages. Do not configure absolute parameters or canvas dimensions targeting raw percentage variables on fixed containers.

#### Preferred Full-Page Layout Configuration Style

```python
_PAGE_DIMENSIONS_MM = {
    ('a4', 'portrait'):   ('210mm', '297mm'),
    ('a4', 'landscape'):  ('297mm', '210mm'),
}

def _get_page_dimensions_style(self):
    self.ensure_one()
    fmt = self.template_id.page_format or 'a4'
    ori = self.template_id.page_orientation or 'portrait'
    w, h = self._PAGE_DIMENSIONS_MM.get((fmt, ori), ('210mm', '297mm'))
    return f'width: {w}; height: {h};'

```

```xml
<div t-attf-style="position: fixed; top: 0; left: 0; #{o._get_page_dimensions_style()} z-index: 0;">
    <img t-attf-src="#{o._get_background_image_uri()}" style="width: 100%; height: 100%;"/>
</div>
<div style="position: relative; z-index: 1;">
    </div>

```

* **Structural Blueprint Rules**:
1. Set `position: fixed` explicitly on a parent wrapper `<div>` utilizing strict `mm` values; do not apply it directly to the child `<img>` element.
2. The parent element enclosing the printable data flow must not contain an `overflow: hidden` block rule.
3. Ensure background binary read tasks are cleanly formatted using valid Data URI wrappers (e.g., `data:image/png;base64,...`).



---

## Deprecated Syntax Lookup Matrix

| Obsolete Framework Pattern | Required Replacement Native to Odoo 18 |
| --- | --- |
| `<tree>` | `<list>` (Use `editable="top"` for inline grids) |
| `attrs="..."` or `states="..."` | Inline expressions (`invisible="x == y"`, `readonly="z"`) |
| `invisible="1"` on column fields | `column_invisible="True"` or `column_invisible="condition"` |
| `/** @odoo-module */` comment block | **Removed**. File locations in manifests specify module scopes automatically |
| `owl="1"` declaration on templates | **Removed**. All asset QWeb engines execute via native OWL 2 |
| `odoo.define()` / `require()` | Native JavaScript `import` / `export` syntaxes |
| `name_get()` method | Computed properties mapped to `display_name` |
| `widget="color_picker"` | `widget="color"` (Renders true RGB color palettes) |
| `Registries.Component.extend()` | Class extensions or core framework `patch()` integrations |
| `models.load_models()` (POS) | Native v18 reactive model loading/services hooks |
| `this._super(...)` | Native JavaScript standard OOP call: `super.methodName(...)` |

```

```