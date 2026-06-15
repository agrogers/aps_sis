import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { getColorForPercent } from "../../js/utils/color_utils";

const SENTINEL_ZERO = -0.01;

export class GradebookGrid extends Component {
    static template = "aps_sis.GradebookGrid";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.gridContainerRef = useRef("gridContainer");
        this.filterBarRef = useRef("filterBar");
        this.columnPickerRef = useRef("columnPicker");

        this.state = useState({
            loading: true,
            gridLoading: false,
            categories: [],
            resources: [],
            students: [],
            selectedCategoryId: false,
            selectedResourceId: false,
            selectedStudentId: false,
            rows: [],
            columns: [],
            allColumns: [],
            summary: null,
            gridInitialized: false,
            error: null,
            columnFilters: {},
            showColumnPicker: false,
            columnPrefs: {},
        });

        this._gridBundle = null;
        this._gridGeneration = 0;   // incremented on each _destroyGrid; _initGrid bails if stale
        this._columnDefs = [];
        this._rowsCache = [];

        onWillStart(async () => {
            await this._loadCategories();
            this._restoreFilterState();
        });

        onMounted(() => {});

        onWillUnmount(() => {
            this._destroyGrid();
            this._removeClickAwayListener();
        });
    }

    _addClickAwayListener() {
        this._removeClickAwayListener();
        this._clickAwayHandler = (ev) => {
            const picker = this.columnPickerRef?.el;
            if (picker && !picker.contains(ev.target) && this.state.showColumnPicker) {
                this.state.showColumnPicker = false;
            }
        };
        document.addEventListener("mousedown", this._clickAwayHandler);
    }

    _removeClickAwayListener() {
        if (this._clickAwayHandler) {
            document.removeEventListener("mousedown", this._clickAwayHandler);
            this._clickAwayHandler = null;
        }
    }

    _FILTER_STORAGE_KEY() { return "aps_gradebook_filter_state"; }

    _saveFilterState() {
        const state = { categoryId: this.state.selectedCategoryId, resourceId: this.state.selectedResourceId, studentId: this.state.selectedStudentId };
        try { localStorage.setItem(this._FILTER_STORAGE_KEY(), JSON.stringify(state)); } catch (e) {}
    }

    _restoreFilterState() {
        try {
            const raw = localStorage.getItem(this._FILTER_STORAGE_KEY());
            if (!raw) return;
            const saved = JSON.parse(raw);
            if (saved.categoryId) {
                this.state.selectedCategoryId = saved.categoryId;
                this._loadResourcesForCategory(saved.categoryId);
            }
        } catch (e) {}
    }

    async _loadResourcesForCategory(catId) {
        try {
            const resources = await this.orm.call("aps.resource.submission", "get_gradebook_resources", [catId]);
            this.state.resources = resources || [];
            const raw = localStorage.getItem(this._FILTER_STORAGE_KEY());
            if (raw) {
                const saved = JSON.parse(raw);
                if (saved.resourceId && resources.find((r) => r.id === saved.resourceId)) {
                    this.state.selectedResourceId = saved.resourceId;
                    if (saved.studentId) this.state.selectedStudentId = saved.studentId;
                    await this._loadGridData();
                }
            }
        } catch (err) { this.state.error = "Failed to load resources."; }
    }

    async _loadCategories() {
        try {
            const categories = await this.orm.call("aps.resource.submission", "get_gradebook_categories", []);
            this.state.categories = categories || [];
        } catch (err) { this.state.error = "Failed to load categories."; }
    }

    async onChangeCategory(ev) {
        const catId = ev.target.value ? parseInt(ev.target.value) : false;
        this.state.selectedCategoryId = catId;
        this.state.selectedResourceId = false;
        this.state.resources = [];
        this.state.students = [];
        this.state.selectedStudentId = false;
        this._destroyGrid();
        this._saveFilterState();
        if (!catId) return;
        try {
            const resources = await this.orm.call("aps.resource.submission", "get_gradebook_resources", [catId]);
            this.state.resources = resources || [];
        } catch (err) { this.state.error = "Failed to load resources."; }
    }

    async onChangeResource(ev) {
        const resId = ev.target.value ? parseInt(ev.target.value) : false;
        this.state.selectedResourceId = resId;
        this._destroyGrid();
        this._saveFilterState();
        if (!resId) return;
        await this._loadGridData();
    }

    async onChangeStudent(ev) {
        const stuId = ev.target.value ? parseInt(ev.target.value) : false;
        this.state.selectedStudentId = stuId;
        this._destroyGrid();
        this._saveFilterState();
        if (!this.state.selectedResourceId) return;
        await this._loadGridData();
    }

    async _loadGridData() {
        this.state.gridLoading = true;
        this.state.error = null;
        try {
            const [data, savedPrefs] = await Promise.all([
                this.orm.call("aps.resource.submission", "get_gradebook_grid_data", [this.state.selectedCategoryId, this.state.selectedResourceId, this.state.selectedStudentId || false]),
                this.orm.call("aps.resource.submission", "load_gradebook_column_prefs", []),
            ]);
            this._rowsCache = data.rows || [];
            this._columnDefs = data.columns || [];
            this.state.summary = data.summary || null;
            this.state.students = data.students || [];
            this.state.allColumns = [...this._columnDefs];
            const prefs = {};
            for (const col of this._columnDefs) prefs[col.id] = true;
            if (savedPrefs && savedPrefs.length) {
                for (const p of savedPrefs) { if (p.id in prefs) prefs[p.id] = p.visible !== false; }
            }
            this.state.columnPrefs = prefs;
            const visibleDefs = this._columnDefs.filter((c) => prefs[c.id] !== false);
            const slickColumns = this._buildColumns(visibleDefs);
            this.state.columns = slickColumns;
            await this._initGrid(slickColumns, this._rowsCache);
        } catch (err) { this.state.error = "Failed to load grid data: " + (err.message || err); }
        finally { this.state.gridLoading = false; }
    }

    // ------------------------------------------------------------------ //
    // Slickgrid-Universal initialization
    // ------------------------------------------------------------------ //

    _buildColumns(columnDefs) {
        return columnDefs.map((col) => {
            const slickCol = {
                id: col.id,
                name: col.name,
                field: col.field,
                width: col.width || 150,
                sortable: col.sortable || false,
                editable: col.editable || false,
                locked: col.locked || false,
                cssClass: col.cssClass || "",
                filterable: col.id !== "score" && col.id !== "result_percent",
            };
            if (col.id === "score") {
                slickCol.editor = {
                    model: Slicker.Editors.float,
                    decimal: 2,
                    minValue: 0,
                    maxValue: 9999,
                };
                // Also set editorClass directly to ensure the grid can resolve the editor.
                // The GridBundle's loadSlickGridEditors() normally sets this via
                // spread ({ ...column, editorClass: column.editor?.model }), but
                // during initial grid creation the property can be lost in the
                // internal column processing pipeline.
                slickCol.editorClass = Slicker.Editors.float;
            }
            if (col.id === "result_percent") {
                slickCol.formatter = (row, cell, value) => {
                    if (value === null || value === undefined) return "";
                    const color = getColorForPercent(value);
                    const textColor = value < 50 ? "#fff" : "#1a1a1a";
                    return `<div style="display:flex;align-items:center;gap:6px;background:${color};padding:2px 8px;border-radius:4px;height:100%;"><span style="font-weight:700;font-size:13px;color:${textColor};min-width:38px;text-align:right;">${value}%</span></div>`;
                };
            }
            return slickCol;
        });
    }

    async _initGrid(columns, rows) {
        const gen = this._gridGeneration;
        await new Promise((r) => setTimeout(r, 50));
        // If _destroyGrid was called while we were waiting, bail out
        if (gen !== this._gridGeneration) return;
        const container = this.gridContainerRef.el;
        if (!container) return;
        const data = rows.map((r, idx) => ({ ...r, _idx: idx }));

        const gridBundle = new Slicker.GridBundle(container, columns, {
            enableCellNavigation: true,
            editable: true,
            enableColumnReorder: true,
            autoEdit: true,
            enableTextSelectionOnCells: true,
            fullWidthRows: true,
            forceFitColumns: false,
            syncColumnCellResize: true,
            showHeaderRow: true,
            enableFiltering: true,
            headerRowHeight: 32,
        }, data);

        this._gridBundle = gridBundle;
        const grid = gridBundle.slickGrid;
        const dataView = gridBundle.dataView;

        dataView.getItemMetadata = (row) => {
            const item = dataView.getItem(row);
            if (item?.has_child_resources) return { cssClasses: 'aps-gradebook-row-noncontributing' };
            return null;
        };

        grid.onColumnsReordered.subscribe(() => {
            const newCols = grid.getColumns();
            this._syncColumnPrefsFromGrid(newCols);
            this._saveColumnPrefs();
            setTimeout(() => this._autoResizeColumns(grid, newCols, container), 50);
        });

        // ------------------------------------------------------------------ //
        // Debounced batch save: collect edits for 500 ms then send them all
        // to the server in a single call.  While a save is in-flight we also
        // track "dirty" rows so the response never overwrites a value the
        // user just typed.
        // ------------------------------------------------------------------ //
        const comp = this;   // capture component reference for use inside
        const dirtySubmissionIds = new Set();
        let pendingEdits = [];   // [{ submissionId, score }]
        let saveTimer = null;
        let saveInFlight = false;

        function scheduleSave() {
            clearTimeout(saveTimer);
            saveTimer = setTimeout(flushEdits, 500);
        }

        async function flushEdits() {
            if (saveInFlight || pendingEdits.length === 0) return;
            saveInFlight = true;
            const edits = pendingEdits.splice(0);   // take all pending
            for (const e of edits) dirtySubmissionIds.add(e.submissionId);
            try {
                const result = await comp.orm.call(
                    "aps.resource.submission",
                    "write_gradebook_scores",
                    [edits],
                    { resource_id: comp.state.selectedResourceId || false },
                );
                if (result.rows) {
                    const cols = grid.getColumns();
                    const si = cols.findIndex((c) => c.id === "score");
                    const pi = cols.findIndex((c) => c.id === "result_percent");
                    const oi = cols.findIndex((c) => c.id === "out_of_marks");
                    for (const upd of result.rows) {
                        const updId = upd.submission_id || upd.id;
                        if (dirtySubmissionIds.has(updId)) continue;
                        const ri = dataView.getItemById(updId);
                        if (!ri) continue;
                        Object.assign(ri, { score: upd.score, result_percent: upd.result_percent, out_of_marks: upd.out_of_marks, state: upd.state, is_locked: upd.is_locked, has_child_resources: upd.has_child_resources });
                        if (si !== -1) grid.updateCell(ri._idx, si);
                        if (pi !== -1) grid.updateCell(ri._idx, pi);
                        if (oi !== -1) grid.updateCell(ri._idx, oi);
                    }
                }
                if (result.summary) comp.state.summary = result.summary;
            } catch (err) {
                console.error("Failed to save scores:", err);
            } finally {
                for (const e of edits) dirtySubmissionIds.delete(e.submissionId);
                saveInFlight = false;
                // If more edits arrived while we were saving, flush again
                if (pendingEdits.length > 0) scheduleSave();
            }
        }

        grid.onBeforeEditCell.subscribe((e, args) => {
            if (!args.column.editable || args.item.state === "complete" || args.item.has_child_resources) return false;
            // Mark this row as dirty immediately so that any in-flight or
            // pending backend response will not overwrite the cell the user
            // is about to edit.
            const sid = args.item.submission_id || args.item.id;
            if (sid) dirtySubmissionIds.add(sid);
            return true;
        });

        grid.onCellChange.subscribe((e, args) => {
            const item = args.item;
            const field = args.column.field;
            const newValue = item[field];
            if (field !== "score") return;
            const submissionId = item.submission_id || item.id;
            if (!submissionId) return;
            // Queue this edit — don't save immediately
            pendingEdits.push({ submission_id: submissionId, score: newValue });
            scheduleSave();
        });

        this._resizeObserver = new ResizeObserver(() => { if (grid) grid.resizeCanvas(); });
        this._resizeObserver.observe(container);
        setTimeout(() => this._autoResizeColumns(grid, columns, container), 100);
        this.state.gridInitialized = true;
    }

    _autoResizeColumns(grid, columns, container) {
        if (!container || !grid) return;
        const tw = container.clientWidth;
        if (tw <= 0) return;
        const fixed = columns.filter((c) => c.id !== "result_percent");
        const pc = columns.find((c) => c.id === "result_percent");
        let used = 0;
        fixed.forEach((c) => used += c.width || 150);
        const avail = tw - used - 20;
        if (pc && avail > 60) { pc.width = avail; grid.setColumns(columns); }
    }

    _destroyGrid() {
        this._gridGeneration++;   // invalidate any in-flight _initGrid
        if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
        if (this._gridBundle) {
            try { this._gridBundle.dispose(); } catch (e) { /* bundle may be partially init */ }
            this._gridBundle = null;
        }
        // Remove leftover .slickgrid-container so the next GridBundle constructor
        // doesn't bail out early (it checks for existing .slickgrid-container).
        // We call dispose() (no arg) above — it cleans up SlickGrid internals
        // without detaching the parent container from the DOM.
        const container = this.gridContainerRef?.el;
        if (container) {
            container.querySelectorAll(".slickgrid-container").forEach((el) => el.remove());
            container.classList.remove("grid-pane");
        }
        this.state.gridInitialized = false;
    }

    get summaryItems() {
        const s = this.state.summary;
        if (!s) return [];
        return [
            { label: "Total Students", value: s.row_count },
            { label: "Total Score", value: this._formatFloat(s.total_score) },
            { label: "Total Out Of", value: this._formatFloat(s.total_out_of) },
            { label: "Average %", value: s.average_percent + "%" },
        ];
    }

    _formatFloat(val) { return (val == null) ? "0" : parseFloat(val).toFixed(2); }

    get columnPickerItems() {
        return this.state.allColumns.map((col) => ({
            id: col.id, name: col.name, visible: this.state.columnPrefs[col.id] !== false, locked: col.locked || false,
        }));
    }

    toggleColumnPicker() {
        this.state.showColumnPicker = !this.state.showColumnPicker;
        if (this.state.showColumnPicker) this._addClickAwayListener();
        else this._removeClickAwayListener();
    }

    closeColumnPicker() {
        this.state.showColumnPicker = false;
        this._removeClickAwayListener();
    }

    onToggleColumn(ev) {
        const colId = ev.target.dataset.colid;
        if (!colId) return;
        this.state.columnPrefs[colId] = ev.target.checked;
        this._applyColumnVisibility();
        this._saveColumnPrefs();
    }

    _applyColumnVisibility() {
        if (!this._gridBundle?.slickGrid) return;
        const grid = this._gridBundle.slickGrid;
        const visibleCols = this.state.allColumns.filter((c) => this.state.columnPrefs[c.id] !== false);
        const slickCols = this._buildColumns(visibleCols);
        grid.setColumns(slickCols);
        grid.invalidate();
        grid.render();
        this.state.columns = slickCols;
        setTimeout(() => this._autoResizeColumns(grid, slickCols, this.gridContainerRef.el), 50);
    }

    _syncColumnPrefsFromGrid(gridCols) {
        const prefs = { ...this.state.columnPrefs };
        const seen = new Set();
        for (const col of gridCols) { prefs[col.id] = this.state.columnPrefs[col.id] !== false; seen.add(col.id); }
        for (const col of this.state.allColumns) { if (!seen.has(col.id) && this.state.columnPrefs[col.id] === false) prefs[col.id] = false; }
        this.state.columnPrefs = prefs;
    }

    async _saveColumnPrefs() {
        const grid = this._gridBundle?.slickGrid;
        const cols = grid ? grid.getColumns() : this.state.columns;
        const prefList = cols.map((c) => ({ id: c.id, visible: this.state.columnPrefs[c.id] !== false }));
        for (const col of this.state.allColumns) { if (!prefList.find((p) => p.id === col.id)) prefList.push({ id: col.id, visible: false }); }
        try {
            await this.orm.call("aps.resource.submission", "save_gradebook_column_prefs", [], { column_prefs: prefList });
        } catch (err) { console.error("GradebookGrid: failed to save column prefs", err); }
    }
}

registry.category("actions").add("aps_gradebook_grid", GradebookGrid);