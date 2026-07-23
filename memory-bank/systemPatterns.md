# System Patterns — APEX

## Architecture Patterns

### OWL 2 Client Actions
```
registry.category("actions").add("tag_name", ComponentClass)
```
- Components use `setup()` with lifecycle hooks (`onWillStart`, `onMounted`, `onPatched`, `onWillUnmount`)
- State managed via `useState()` from `@odoo/owl`
- RPC calls via `useService("orm")` → `orm.call(model, method, args, kwargs)`
- Templates reference `this.state` and `this.props` directly

### Recursive Tree Components
- Self-referential: `ComponentClass.components = { ComponentClass }`
- Props passed down: `node`, `depth`, `expandedIds`, callbacks
- Expanded state tracked in parent (not reactive Set, trigger re-render via version counter)

### Content Rendering
- HTML from Python wrapped in `markup()` from `@odoo/owl`
- Template uses `t-out="section.html"` for safe HTML rendering
- `t-esc` for escaped text, `t-out` for raw HTML

### Data Flow (Course Explorer)
```
User selects category
  → JS calls orm.call("aps.resources", "get_course_explorer_data", [categoryId])
  → Python builds tree (depth-first, sequence-sorted) + resolves notes
  → Returns { tree: [...], contentSections: [...] }
  → JS wraps HTML in markup(), stores in state
  → OWL renders tree nodes + content sections
```

### Persistence Pattern
- localStorage key: `aps_course_explorer`
- Saves: expandedNodeIds, selectedCategoryId, activeSectionId, sidebarCollapsed, scrollPosition
- Loaded on setup(), saved on state changes (debounced for scroll)

### Scroll Sync Pattern
- IntersectionObserver on content sections with `rootMargin: "-10% 0px -70% 0px"`
- Updates `activeSectionId` → highlights tree node
- Tree node click → `element.scrollIntoView({ behavior: "smooth" })`

## Coding Conventions

### Python
- Methods decorated with `@api.model` for class-level, `self.ensure_one()` for record-level
- HTML fields: use `Markup()` wrapper when building custom HTML strings
- Domain filters: `[('field', '=', value)]` format

### JavaScript
- No `odoo.define()` / `require()` — native ES module imports
- No `@odoo-module` comment tags
- `import { markup } from "@odoo/owl"` for HTML safety

### XML Templates
- `<list>` not `<tree>` (deprecated)
- Inline conditions: `invisible="condition"` (not `attrs=`)
- `t-key` required on `t-foreach` loops