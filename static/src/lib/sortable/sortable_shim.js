// SlickGrid checks `Sortable` as a bare identifier.
// SortableJS sets window.Sortable via UMD, but Odoo's strict-mode bundling
// prevents bare identifiers from resolving to globals. This shim bridges the gap.
var Sortable = window.Sortable;