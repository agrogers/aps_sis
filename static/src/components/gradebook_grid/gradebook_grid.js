import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

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
            allColumns: [],              // full column defs before visibility filter
            summary: null,
            gridInitialized: false,
            error: null,
            columnFilters: {},
            showColumnPicker: false,     // toggle column visibility dropdown
            columnPrefs: {},             // { [colId]: visible }
        });

        this._grid = null;
        this._dataView = null;
        this._columnDefs = [];
        this._rowsCache = [];

        onWillStart(async () => {
            await this._loadCategories();
            this._restoreFilterState();
        });

        onMounted(() => {
            // Grid is initialized on-demand after data loads
        });

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

    // ------------------------------------------------------------------ //
    // Data loading
    // ------------------------------------------------------------------ //

    // ------------------------------------------------------------------ //
    // Filter state persistence (localStorage)
    // ------------------------------------------------------------------ //

    _FILTER_STORAGE_KEY() { return "aps_gradebook_filter_state"; }

    _saveFilterState() {
        const state = {
            categoryId: this.state.selectedCategoryId,
            resourceId: this.state.selectedResourceId,
            studentId: this.state.selectedStudentId,
        };
        try {
            localStorage.setItem(this._FILTER_STORAGE_KEY(), JSON.stringify(state));
        } catch (e) {
            // localStorage may be unavailable
        }
    }

    _restoreFilterState() {
        try {
            const raw = localStorage.getItem(this._FILTER_STORAGE_KEY());
            if (!raw) return;
            const saved = JSON.parse(raw);
            if (saved.categoryId) {
                this.state.selectedCategoryId = saved.categoryId;
                // Categories are already loaded — now load resources
                this._loadResourcesForCategory(saved.categoryId);
            }
        } catch (e) {
            // ignore
        }
    }

    async _loadResourcesForCategory(catId) {
        try {
            const resources = await this.orm.call(
                "aps.resource.submission",
                "get_gradebook_resources",
                [catId]
            );
            this.state.resources = resources || [];
            // If we also have a saved resource, select it and load grid data
            const raw = localStorage.getItem(this._FILTER_STORAGE_KEY());
            if (raw) {
                const saved = JSON.parse(raw);
                if (saved.resourceId && resources.find((r) => r.id === saved.resourceId)) {
                    this.state.selectedResourceId = saved.resourceId;
                    if (saved.studentId) {
                        this.state.selectedStudentId = saved.studentId;
                    }
                    await this._loadGridData();
                }
            }
        } catch (err) {
            this.state.error = "Failed to load resources.";
        }
    }

    async _loadCategories() {
        try {
            const categories = await this.orm.call(
                "aps.resource.submission",
                "get_gradebook_categories",
                []
            );
            this.state.categories = categories || [];
        } catch (err) {
            this.state.error = "Failed to load categories.";
        }
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

        if (!catId) {
            return;
        }

        try {
            const resources = await this.orm.call(
                "aps.resource.submission",
                "get_gradebook_resources",
                [catId]
            );
            this.state.resources = resources || [];
        } catch (err) {
            this.state.error = "Failed to load resources.";
        }
    }

    async onChangeResource(ev) {
        const resId = ev.target.value ? parseInt(ev.target.value) : false;
        this.state.selectedResourceId = resId;
        this._destroyGrid();
        this._saveFilterState();
        if (!resId) {
            return;
        }
        await this._loadGridData();
    }

    async onChangeStudent(ev) {
        const stuId = ev.target.value ? parseInt(ev.target.value) : false;
        this.state.selectedStudentId = stuId;
        this._saveFilterState();
        if (!this.state.selectedResourceId) {
            return;
        }
        await this._loadGridData();
    }

    async _loadGridData() {
        this.state.gridLoading = true;
        this.state.error = null;

        try {
            const [data, savedPrefs] = await Promise.all([
                this.orm.call(
                    "aps.resource.submission",
                    "get_gradebook_grid_data",
                    [
                        this.state.selectedCategoryId,
                        this.state.selectedResourceId,
                        this.state.selectedStudentId || false,
                    ]
                ),
                this.orm.call(
                    "aps.resource.submission",
                    "load_gradebook_column_prefs",
                    [],
                ),
            ]);

            this._rowsCache = data.rows || [];
            this._columnDefs = data.columns || [];
            this.state.summary = data.summary || null;
            this.state.students = data.students || [];

            // Keep the full column list (server reordered per saved prefs)
            this.state.allColumns = [...this._columnDefs];

            // Build columnPrefs map: merge server prefs (for hidden cols) with visible default
            const prefs = {};
            // Default: all visible
            for (const col of this._columnDefs) {
                prefs[col.id] = true;
            }
            // Override with saved visibility
            if (savedPrefs && savedPrefs.length) {
                for (const p of savedPrefs) {
                    if (p.id in prefs) {
                        prefs[p.id] = p.visible !== false;
                    }
                }
            }
            this.state.columnPrefs = prefs;

            // Build initial SlickGrid columns with visibility applied
            const visibleDefs = this._columnDefs.filter(
                (c) => prefs[c.id] !== false
            );
            const slickColumns = this._buildColumns(visibleDefs);
            this.state.columns = slickColumns;

            // Wait for DOM then initialize grid
            await this._initGrid(slickColumns, this._rowsCache);
        } catch (err) {
            this.state.error = "Failed to load grid data: " + (err.message || err);
        } finally {
            this.state.gridLoading = false;
        }
    }

    // ------------------------------------------------------------------ //
    // SlickGrid initialization
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
            };

            // Custom editor for score column (float input)
            if (col.id === "score") {
                slickCol.editor = this._getScoreEditor();
            }

            // Formatter for result_percent column
            if (col.id === "result_percent") {
                slickCol.formatter = (row, cell, value) => {
                    if (value === null || value === undefined) return "";
                    const color = value >= 50 ? "#28a745" : value >= 30 ? "#ffc107" : "#dc3545";
                    return `<div style="display:flex;align-items:center;gap:6px;">
                        <div style="flex:1;height:16px;background:#e9ecef;border-radius:8px;overflow:hidden;">
                            <div style="height:100%;width:${Math.min(value, 100)}%;background:${color};border-radius:8px;transition:width 0.3s;"></div>
                        </div>
                        <span style="font-weight:600;font-size:13px;color:#495057;min-width:38px;text-align:right;">${value}%</span>
                    </div>`;
                };
            }

            return slickCol;
        });
    }

    _getScoreEditor() {
        // Return a custom editor class for SlickGrid
        return class ScoreEditor {
            constructor(args) {
                this.args = args;
                this.init();
            }

            init() {
                const container = this.args.container;
                this.$input = document.createElement("input");
                this.$input.type = "number";
                this.$input.step = "0.01";
                this.$input.min = "0";
                this.$input.style.width = "100%";
                this.$input.style.height = "100%";
                this.$input.style.border = "0";
                this.$input.style.padding = "0 6px";
                this.$input.style.outline = "none";
                this.$input.style.fontSize = "14px";
                this.$input.style.boxSizing = "border-box";
                this.$input.value = this.args.item.score;

                container.appendChild(this.$input);

                this.$input.focus();
                this.$input.select();

                this.$input.addEventListener("keydown", (e) => {
                    if (e.key === "Enter") {
                        this.args.grid.getEditorLock().commitCurrentEdit();
                        // Move down on Enter
                        const row = this.args.row;
                        if (row < this.args.grid.getDataLength() - 1) {
                            this.args.grid.navigateToRow(row + 1);
                        }
                    }
                    if (e.key === "Tab") {
                        this.args.grid.getEditorLock().commitCurrentEdit();
                    }
                });
            }

            destroy() {
                if (this.$input && this.$input.parentNode) {
                    this.$input.parentNode.removeChild(this.$input);
                }
            }

            focus() {
                if (this.$input) {
                    this.$input.focus();
                    this.$input.select();
                }
            }

            loadValue(item) {
                this.defaultValue = item[this.args.column.field];
                if (this.$input) {
                    this.$input.value = this.defaultValue;
                }
            }

            serializeValue() {
                const val = this.$input ? parseFloat(this.$input.value) : this.defaultValue;
                return isNaN(val) ? 0 : val;
            }

            applyValue(item, state) {
                item.score = state;
            }

            isValueChanged() {
                const current = this.serializeValue();
                return current !== this.defaultValue;
            }

            validate() {
                const val = this.serializeValue();
                if (isNaN(val) || val < 0) {
                    return { valid: false, msg: "Score must be a positive number." };
                }
                return { valid: true, msg: null };
            }
        };
    }

    async _initGrid(columns, rows) {
        // Wait a tick for DOM to render
        await new Promise((r) => setTimeout(r, 50));

        const container = this.gridContainerRef.el;
        if (!container) {
            return;
        }

        // Build data
        const data = rows.map((r, idx) => ({ ...r, _idx: idx }));

        // Create DataView
        const dataView = new Slick.Data.DataView();
        this._dataView = dataView;

        dataView.beginUpdate();
        dataView.setItems(data, "id");
        dataView.endUpdate();

        // Row-level metadata for parent (non-leaf) row styling
        dataView.getItemMetadata = (row) => {
            const item = dataView.getItem(row);
            if (item && item.has_child_resources) {
                return { cssClasses: 'aps-gradebook-row-noncontributing' };
            }
            return null;
        };

        // Wire DataView changes to grid re-render (needed for filtering)
        dataView.onRowCountChanged.subscribe(() => {
            grid.updateRowCount();
            grid.render();
        });
        dataView.onRowsChanged.subscribe((e, args) => {
            grid.invalidateRows(args.rows);
            grid.render();
        });

        // Create grid with explicit initialization so we can subscribe to
        // header row events before the grid renders them
        const grid = new Slick.Grid(container, dataView, columns, {
            enableCellNavigation: true,
            editable: true,
            enableColumnReorder: true,
            autoEdit: true,
            enableTextSelectionOnCells: true,
            fullWidthRows: true,
            forceFitColumns: false,
            syncColumnCellResize: true,
            cellHighlightCssClass: "slick-cell-highlighted",
            showHeaderRow: true,
            headerRowHeight: 32,
            explicitInitialization: true,
        });

        this._grid = grid;

        // Cell selection model
        const cellSelectionModel = new Slick.CellSelectionModel();
        grid.setSelectionModel(cellSelectionModel);

        // --- Column header row filter inputs ---
        const columnFilters = this.state.columnFilters;

        grid.onHeaderRowCellRendered.subscribe((e, args) => {
            // Don't add filters to the score column — users edit inline
            if (args.column.id === "score") {
                args.node.innerHTML =
                    `<span style="color:#6c757d;font-size:11px;font-style:italic;">type score</span>`;
                return;
            }
            // Skip result_percent column too
            if (args.column.id === "result_percent") {
                return;
            }
            args.node.innerHTML = "";
            const inputElm = document.createElement("input");
            inputElm.className = "form-control form-control-sm";
            inputElm.style.height = "100%";
            inputElm.style.border = "0";
            inputElm.style.borderRadius = "0";
            inputElm.style.fontSize = "12px";
            inputElm.style.padding = "0 4px";
            inputElm.style.background = "transparent";
            inputElm.placeholder = "🔎";
            inputElm.dataset.columnid = args.column.id;
            inputElm.value = columnFilters[args.column.id] || "";
            args.node.appendChild(inputElm);
        });

        // Wire up filter input events on the header row
        const headerRowElm = grid.getHeaderRow();
        const filterHandler = (e) => {
            const input = e.target;
            const colId = input.dataset.columnid;
            if (colId) {
                columnFilters[colId] = input.value || "";
                dataView.refresh();
            }
        };
        headerRowElm.addEventListener("change", filterHandler);
        headerRowElm.addEventListener("keyup", filterHandler);

        // DataView filter function
        dataView.setFilter((item) => {
            for (const colId in columnFilters) {
                const filterVal = columnFilters[colId];
                if (!filterVal) continue;

                const col = grid.getColumns().find((c) => c.id === colId);
                if (!col) continue;

                const field = col.field || colId;
                const itemVal = item[field];
                if (itemVal == null) return false;

                const strVal = String(itemVal).toLowerCase();
                if (strVal.indexOf(filterVal.toLowerCase()) === -1) {
                    return false;
                }
            }
            return true;
        });

        // Now initialize the grid so it renders with all plugins/subscribers active
        grid.init();

        // --- Column reorder: persist new order ---
        grid.onColumnsReordered.subscribe(() => {
            const newCols = grid.getColumns();
            this._syncColumnPrefsFromGrid(newCols);
            this._saveColumnPrefs();
            // Re-apply auto resize after reorder
            setTimeout(() => {
                this._autoResizeColumns(grid, grid.getColumns(), container);
            }, 50);
        });

        // --- Before Edit: lock only by column def + finalised state ---
        grid.onBeforeEditCell.subscribe((e, args) => {
            const column = args.column;
            const item = args.item;

            // Lock by column definition
            if (!column.editable) {
                return false;
            }

            // Lock only when state is "complete" (finalised)
            if (item.state === "complete") {
                return false;
            }

            return true;
        });

        // --- Cell Change: save immediately ---
        grid.onCellChange.subscribe(async (e, args) => {
            const item = args.item;
            const field = args.column.field;
            const newValue = args.item[field];

            if (field !== "score") return;

            const submissionId = item.submission_id || item.id;
            if (!submissionId) return;

            try {
                const result = await this.orm.call(
                    "aps.resource.submission",
                    "write_gradebook_score",
                    [submissionId, newValue],
                    { resource_id: this.state.selectedResourceId || false },
                );

                // Apply all returned rows — update items in-place then refresh
                // only the readonly (parent) cells so the active editor is not killed.
                if (result.rows) {
                    const cols = grid.getColumns();
                    const scoreColIdx = cols.findIndex((c) => c.id === "score");
                    const percentColIdx = cols.findIndex((c) => c.id === "result_percent");
                    const outOfColIdx = cols.findIndex((c) => c.id === "out_of_marks");

                    for (const updated of result.rows) {
                        const rowItem = dataView.getItemById(updated.submission_id || updated.id);
                        if (!rowItem) continue;

                        rowItem.score = updated.score;
                        rowItem.result_percent = updated.result_percent;
                        rowItem.out_of_marks = updated.out_of_marks;
                        rowItem.state = updated.state;
                        rowItem.is_locked = updated.is_locked;
                        rowItem.has_child_resources = updated.has_child_resources;

                        // Only updateCell for readonly parent rows (has children)
                        // so the active editor on leaf rows is never disturbed
                        if (!rowItem.has_child_resources) continue;

                        const rowIdx = dataView.getRowById(updated.submission_id || updated.id);
                        if (rowIdx === undefined) continue;

                        if (scoreColIdx !== -1) {
                            grid.updateCell(rowIdx, scoreColIdx);
                        }
                        if (percentColIdx !== -1) {
                            grid.updateCell(rowIdx, percentColIdx);
                        }
                        if (outOfColIdx !== -1) {
                            grid.updateCell(rowIdx, outOfColIdx);
                        }
                    }
                } else if (result.updated_row) {
                    // Fallback — single row only
                    const updated = result.updated_row;
                    const rowItem = dataView.getItemById(submissionId);
                    if (rowItem) {
                        rowItem.score = updated.score;
                        rowItem.result_percent = updated.result_percent;
                        rowItem.state = updated.state;
                        rowItem.is_locked = updated.is_locked;
                        rowItem.has_child_resources = updated.has_child_resources;
                        dataView.updateItem(submissionId, rowItem);
                    }
                }

                // Update summary
                if (result.summary) {
                    this.state.summary = result.summary;
                }

            } catch (err) {
                console.error("Failed to save score:", err);
                // Revert the cell
                dataView.updateItem(submissionId, item);
            }
        });

        // --- Sort handler ---
        grid.onSort.subscribe((e, args) => {
            const colId = args.sortCol.id;
            const sortDir = args.sortAsc ? 1 : -1;

            dataView.sort((a, b) => {
                let aVal = a[colId];
                let bVal = b[colId];
                if (typeof aVal === "string") {
                    aVal = aVal.toLowerCase();
                    bVal = (bVal || "").toLowerCase();
                }
                if (aVal === bVal) return 0;
                return aVal > bVal ? sortDir : -sortDir;
            });
            grid.invalidate();
            grid.render();
        });

        // --- Resize handler ---
        this._resizeGrid();
        this._resizeObserver = new ResizeObserver(() => this._resizeGrid());
        this._resizeObserver.observe(container);

        // Auto-resize columns to fill width
        setTimeout(() => {
            this._autoResizeColumns(grid, columns, container);
        }, 100);

        this.state.gridInitialized = true;
    }

    _autoResizeColumns(grid, columns, container) {
        if (!container || !grid) return;
        const totalWidth = container.clientWidth;
        if (totalWidth <= 0) return;

        const fixedCols = columns.filter((c) => c.id !== "result_percent");
        const percentCol = columns.find((c) => c.id === "result_percent");

        let usedWidth = 0;
        fixedCols.forEach((c) => {
            usedWidth += c.width || 150;
        });

        // Account for grid border/padding
        const available = totalWidth - usedWidth - 20;
        if (percentCol && available > 60) {
            percentCol.width = available;
            grid.setColumns(columns);
        }
    }

    _resizeGrid() {
        if (this._grid && this.gridContainerRef.el) {
            this._grid.resizeCanvas();
        }
    }

    _destroyGrid() {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this._grid) {
            this._grid.destroy();
            this._grid = null;
        }
        if (this._dataView) {
            this._dataView = null;
        }
        this.state.gridInitialized = false;
    }

    // ------------------------------------------------------------------ //
    // Summary helpers
    // ------------------------------------------------------------------ //

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

    _formatFloat(val) {
        if (val === null || val === undefined) return "0";
        return parseFloat(val).toFixed(2);
    }

    // ------------------------------------------------------------------ //
    // Column visibility picker
    // ------------------------------------------------------------------ //

    get columnPickerItems() {
        // Return all known columns with their visibility state
        return this.state.allColumns.map((col) => ({
            id: col.id,
            name: col.name,
            visible: this.state.columnPrefs[col.id] !== false,
            locked: col.locked || false,
        }));
    }

    toggleColumnPicker() {
        this.state.showColumnPicker = !this.state.showColumnPicker;
        if (this.state.showColumnPicker) {
            this._addClickAwayListener();
        } else {
            this._removeClickAwayListener();
        }
    }

    closeColumnPicker() {
        this.state.showColumnPicker = false;
        this._removeClickAwayListener();
    }

    onToggleColumn(ev) {
        const colId = ev.target.dataset.colid;
        if (!colId) return;

        const newVisible = ev.target.checked;
        this.state.columnPrefs[colId] = newVisible;
        this._applyColumnVisibility();
        this._saveColumnPrefs();
    }

    _applyColumnVisibility() {
        if (!this._grid) return;

        // Start from the full known column list, not just what's currently on the grid
        const visibleCols = this.state.allColumns.filter(
            (c) => this.state.columnPrefs[c.id] !== false
        );
        // Build SlickGrid column objects for the visible set
        const slickCols = this._buildColumns(visibleCols);
        this._grid.setColumns(slickCols);
        this._grid.invalidate();
        this._grid.render();

        // Update state.columns for template
        this.state.columns = slickCols;

        // Re-auto-resize
        setTimeout(() => {
            this._autoResizeColumns(this._grid, slickCols, this.gridContainerRef.el);
        }, 50);
    }

    _syncColumnPrefsFromGrid(gridCols) {
        // Preserve existing visibility for all known columns,
        // updating only the order-implied ones from grid columns
        const prefs = { ...this.state.columnPrefs };
        const seen = new Set();
        for (const col of gridCols) {
            prefs[col.id] = this.state.columnPrefs[col.id] !== false;
            seen.add(col.id);
        }
        // Keep hidden column prefs intact
        for (const col of this.state.allColumns) {
            if (!seen.has(col.id) && this.state.columnPrefs[col.id] === false) {
                prefs[col.id] = false;
            }
        }
        this.state.columnPrefs = prefs;
    }

    async _saveColumnPrefs() {
        // Build the pref list in current grid order
        const cols = this._grid ? this._grid.getColumns() : this.state.columns;
        const prefList = cols.map((c) => ({
            id: c.id,
            visible: this.state.columnPrefs[c.id] !== false,
        }));
        // Include any hidden columns at the end
        for (const col of this.state.allColumns) {
            if (!prefList.find((p) => p.id === col.id)) {
                prefList.push({ id: col.id, visible: false });
            }
        }
        try {
            await this.orm.call(
                "aps.resource.submission",
                "save_gradebook_column_prefs",
                [],
                { column_prefs: prefList },
            );
        } catch (err) {
            console.error("GradebookGrid: failed to save column prefs", err);
        }
    }
}

// Register the client action
registry.category("actions").add("aps_gradebook_grid", GradebookGrid);