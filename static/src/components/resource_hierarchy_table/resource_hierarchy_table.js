import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { ResourceNotesDialog } from "./resource_notes_dialog";
import { ResourceLinkButtons } from "@aps_sis/components/resource_link_buttons/resource_link_buttons";

const STORAGE_KEY = "aps_resource_hierarchy_table";
const COL_WIDTH = 120; // px per leaf column

export class ResourceHierarchyTable extends Component {
    static template = "aps_sis.ResourceHierarchyTable";
    static components = { ResourceLinkButtons };
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
        // Embedded mode props (used when hosted inside another component)
        embedded: { type: Boolean, optional: true },
        fixedCategoryId: { type: Number, optional: true },
        storageKeySuffix: { type: String, optional: true },
        // When set, activeTagIds are read from this storage key (shared with another instance)
        sharedTagStorageKey: { type: String, optional: true },
        // Student mode: show notes dialog instead of navigating to form
        studentMode: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this._embedded = !!this.props.embedded;
        this._studentMode = !!(
            this.props.studentMode ||
            this.props.action?.context?.student_mode
        );

        const saved = this._loadStorage();
        // If sharedTagStorageKey is set, load activeTagIds from the shared key
        const sharedTagIds = this.props.sharedTagStorageKey
            ? this._loadStorageByKey(this.props.sharedTagStorageKey).activeTagIds || []
            : null;
        const ctxSubject = this.props.action?.context?.default_subject_id || false;

        // Per-node expand overrides: IDs whose children are force-shown
        // beyond the global cap, or force-collapsed below it.
        this._expanded = new Set(saved.expanded || []);
        this._collapsed = new Set(saved.collapsed || []);
        // Per-node minimized: cell shown at narrow width with hidden text.
        this._minimized = new Set(saved.minimized || []);

        this.state = useState({
            loading: true,
            subjects: [],
            selectedSubjectId: ctxSubject || saved.selectedSubjectId || false,
            hierarchyData: [],
            zoom: saved.zoom || 1,
            scrollLeft: saved.scrollLeft || 0,
            maxVisibleDepth: saved.maxVisibleDepth ?? Infinity,
            globalMaxDepth: 0,
            // Tag overlay
            hierarchyTags: [],
            activeTagIds: new Set(sharedTagIds !== null ? sharedTagIds : (saved.activeTagIds || [])),
            // Supporting resource link buttons in cells
            showLinks: saved.showLinks || false,
        });

        this.scrollRef = { el: null };

        // Touch-focus: on touch devices the first tap reveals the
        // per-cell action buttons; tapping again acts normally.
        this._touchFocusedCellId = null;
        this._onDocumentTouch = this._onDocumentTouch.bind(this);
        document.addEventListener("touchstart", this._onDocumentTouch, true);

        onWillUnmount(() => {
            document.removeEventListener("touchstart", this._onDocumentTouch, true);
        });

        onWillStart(async () => {
            const promises = [this._loadHierarchyTags()];
            if (!this._embedded) {
                promises.push(this._loadSubjects());
            }
            await Promise.all(promises);
            await this._loadHierarchy();
        });

        onMounted(() => {
            this._bindScrollRef();
            this._restoreScroll();
            if (this._embedded) {
                this._setupStickyScrollbar();
            }
        });

        onPatched(() => {
            this._bindScrollRef();
            if (this._embedded) {
                this._setupStickyScrollbar();
            }
        });
    }

    // ── Sticky mirror scrollbar (embedded mode) ───────────────────────

    _setupStickyScrollbar() {
        const rootEl = document.querySelector(".rht_embedded");
        const scrollEl = rootEl && rootEl.querySelector(".rht_scroll_container");
        if (!rootEl || !scrollEl) return;

        // Remove old bar if already present
        const old = rootEl.querySelector(".rht_sticky_bar");
        if (old) old.remove();

        const bar = document.createElement("div");
        bar.className = "rht_sticky_bar";

        const phantom = document.createElement("div");
        // scrollWidth is the unscaled layout width; multiply by zoom for visual width.
        const phantomWidth = Math.round(scrollEl.scrollWidth * (this.state.zoom || 1));
        phantom.style.cssText = `height:1px;width:${phantomWidth}px;`;
        bar.appendChild(phantom);
        rootEl.appendChild(bar);

        // Bidirectional sync without re-entry
        let syncing = false;
        bar.addEventListener("scroll", () => {
            if (syncing) return;
            syncing = true;
            scrollEl.scrollLeft = bar.scrollLeft;
            syncing = false;
        });
        scrollEl.addEventListener("scroll", () => {
            if (syncing) return;
            syncing = true;
            bar.scrollLeft = scrollEl.scrollLeft;
            syncing = false;
        });
    }

    // ── LocalStorage persistence ─────────────────────────────────────

    _loadStorage() {
        try {
            const key = STORAGE_KEY + (this.props.storageKeySuffix || "");
            return this._loadStorageByKey(key);
        } catch {
            return {};
        }
    }

    _loadStorageByKey(key) {
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return {};
            const data = JSON.parse(raw);
            if (data.maxVisibleDepth === null || data.maxVisibleDepth === undefined) {
                data.maxVisibleDepth = Infinity;
            }
            return data;
        } catch {
            return {};
        }
    }

    _saveStorage() {
        const el = this.scrollRef.el;
        const data = {
            zoom: this.state.zoom,
            scrollLeft: el ? el.scrollLeft : this.state.scrollLeft,
            selectedSubjectId: this.state.selectedSubjectId,
            maxVisibleDepth: this.state.maxVisibleDepth === Infinity ? null : this.state.maxVisibleDepth,
            expanded: [...this._expanded],
            collapsed: [...this._collapsed],
            minimized: [...this._minimized],
            activeTagIds: [...this.state.activeTagIds],
            showLinks: this.state.showLinks,
        };
        try {
            const key = STORAGE_KEY + (this.props.storageKeySuffix || "");
            localStorage.setItem(key, JSON.stringify(data));
        } catch { /* quota exceeded */ }
    }

    _bindScrollRef() {
        const el = document.querySelector(".rht_scroll_container");
        if (el && el !== this.scrollRef.el) {
            this.scrollRef.el = el;
            el.addEventListener("scroll", () => {
                this.state.scrollLeft = el.scrollLeft;
                this._saveStorage();
            });
        }
    }

    _restoreScroll() {
        const el = this.scrollRef.el;
        if (el && this.state.scrollLeft) {
            el.scrollLeft = this.state.scrollLeft;
        }
    }

    // ── Data loading ─────────────────────────────────────────────────

    async _loadSubjects() {
        this.state.subjects = await this.orm.call(
            "aps.resources",
            "get_hierarchy_subjects",
            [],
        );
    }

    async _loadHierarchyTags() {
        this.state.hierarchyTags = await this.orm.call(
            "aps.resources",
            "get_hierarchy_tags",
            [],
        );
    }

    async _loadHierarchy() {
        this.state.loading = true;
        const subjectId = this.state.selectedSubjectId || false;
        const categoryId = this._embedded ? (this.props.fixedCategoryId || false) : false;
        this._rawData = await this.orm.call(
            "aps.resources",
            "get_hierarchy_table_data",
            [subjectId],
            { category_id: categoryId },
        );
        this.state.globalMaxDepth = Math.max(0, ...this._rawData.map((g) => g.max_depth));
        if (this.state.maxVisibleDepth === Infinity) {
            this.state.maxVisibleDepth = this.state.globalMaxDepth;
        }
        this._rebuildRows();
        this.state.loading = false;
    }

    _rebuildRows() {
        const cap = this.state.maxVisibleDepth;
        this.state.hierarchyData = (this._rawData || []).map((group) => {
            const trimmed = this._trimTree(group.roots, 0, cap);
            const depth = this._treeDepth(trimmed);
            return {
                ...group,
                roots: trimmed,
                rows: this._buildRows(trimmed, depth),
                total_cols: trimmed.reduce((s, n) => s + n.colspan, 0),
            };
        });
    }

    /** Measure actual depth of the (possibly locally-expanded) tree. */
    _treeDepth(nodes) {
        if (!nodes || !nodes.length) return 0;
        let mx = 0;
        for (const n of nodes) {
            if (n.children && n.children.length) {
                mx = Math.max(mx, 1 + this._treeDepth(n.children));
            }
        }
        return mx;
    }

    /**
     * Return a deep copy of the tree trimmed at maxDepth,
     * but allow per-node expand/collapse overrides.
     */
    _trimTree(nodes, currentDepth, maxDepth) {
        return nodes.map((node) => {
            const hasKids = node.children && node.children.length;

            // Per-node minimize override: collapse to narrow cell, hide all children
            if (this._minimized.has(node.id)) {
                return { ...node, children: [], colspan: 1, _hasHiddenChildren: hasKids, _minimized: true };
            }

            // Per-node collapse override: force this node to be a leaf
            if (this._collapsed.has(node.id) && hasKids) {
                return { ...node, children: [], colspan: 1, _hasHiddenChildren: true };
            }

            // Per-node expand override: show children even past cap
            const forceExpand = this._expanded.has(node.id);

            if (!forceExpand && (currentDepth >= maxDepth || !hasKids)) {
                return {
                    ...node,
                    children: [],
                    colspan: 1,
                    _hasHiddenChildren: hasKids,
                };
            }
            const children = this._trimTree(node.children, currentDepth + 1, forceExpand ? Infinity : maxDepth);
            const colspan = children.reduce((s, c) => s + c.colspan, 0);
            return { ...node, children, colspan, _hasHiddenChildren: false };
        });
    }

    /**
     * Flatten the tree into an array of row-arrays suitable for
     * rendering as ``<tr>`` / ``<td>`` with colspan and rowspan.
     */
    _buildRows(roots, maxDepth) {
        const rows = [];
        for (let i = 0; i <= maxDepth; i++) {
            rows.push([]);
        }

        const walk = (node, depth, rootIndex) => {
            const isLeaf = !node.children || !node.children.length;
            rows[depth].push({
                id: node.id,
                name: node.name,
                colspan: node.colspan,
                rowspan: isLeaf ? maxDepth - depth + 1 : 1,
                depth: depth,
                rootIndex: rootIndex,
                tag_ids: node.tag_ids || [],
                has_notes: node.has_notes || 'no',
                hasHiddenChildren: !!node._hasHiddenChildren,
                hasVisibleChildren: !isLeaf,
                minimized: !!node._minimized,
                links: node.links || [],
            });
            if (!isLeaf) {
                for (const child of node.children) {
                    walk(child, depth + 1, rootIndex);
                }
            }
        };

        for (let i = 0; i < roots.length; i++) {
            walk(roots[i], 0, i);
        }

        return rows.filter((r) => r.length > 0);
    }

    // ── User actions ─────────────────────────────────────────────────

    async onSubjectChange(ev) {
        const val = ev.target.value;
        this.state.selectedSubjectId = val ? parseInt(val, 10) : false;
        this._saveStorage();
        await this._loadHierarchy();
    }

    zoomIn() {
        this.state.zoom = Math.min(2, +(this.state.zoom + 0.1).toFixed(2));
        this._saveStorage();
    }

    zoomOut() {
        this.state.zoom = Math.max(0.3, +(this.state.zoom - 0.1).toFixed(2));
        this._saveStorage();
    }

    zoomReset() {
        this.state.zoom = 1;
        this._saveStorage();
    }

    depthDecrease() {
        if (this.state.maxVisibleDepth > 0) {
            this.state.maxVisibleDepth--;
            // Clear per-node overrides on global depth change
            this._expanded.clear();
            this._collapsed.clear();
            this._rebuildRows();
            this._saveStorage();
        }
    }

    depthIncrease() {
        if (this.state.maxVisibleDepth < this.state.globalMaxDepth) {
            this.state.maxVisibleDepth++;
            this._expanded.clear();
            this._collapsed.clear();
            this._rebuildRows();
            this._saveStorage();
        }
    }

    // ── Per-cell expand / collapse ───────────────────────────────────

    cellExpand(ev, cellId) {
        ev.stopPropagation();
        this._collapsed.delete(cellId);
        this._expanded.add(cellId);
        this._rebuildRows();
        this._saveStorage();
    }

    cellCollapse(ev, cellId) {
        ev.stopPropagation();
        this._expanded.delete(cellId);
        this._collapsed.add(cellId);
        this._rebuildRows();
        this._saveStorage();
    }

    // ── Per-cell minimize (narrow width, hide text) ──────────────────

    cellToggleMinimize(ev, cellId) {
        ev.stopPropagation();
        if (this._minimized.has(cellId)) {
            this._minimized.delete(cellId);
        } else {
            this._minimized.add(cellId);
        }
        this._rebuildRows();
        this._saveStorage();
    }

    // ── Supporting resource links toggle ────────────────────────────

    toggleShowLinks() {
        this.state.showLinks = !this.state.showLinks;
        this._saveStorage();
    }

    // ── Tag overlay toggle ───────────────────────────────────────────

    toggleTag(tagId) {
        const s = this.state.activeTagIds;
        if (s.has(tagId)) {
            s.delete(tagId);
        } else {
            s.add(tagId);
        }
        // Force reactivity by reassigning
        this.state.activeTagIds = new Set(s);
        this._saveStorage();
    }

    isTagActive(tagId) {
        return this.state.activeTagIds.has(tagId);
    }

    get zoomStyle() {
        return `transform: scale(${this.state.zoom}); transform-origin: top left;`;
    }

    /**
     * Handle cell click. On touch devices the first tap only reveals
     * the overlay buttons (expand / collapse / minimize); a second
     * tap fires the normal openResource action.
     */
    onCellClick(ev, id, name, hasNotes) {
        // Detect touch: the click was preceded by a touchstart.
        const isTouch = ev.sourceCapabilities
            ? ev.sourceCapabilities.firesTouchEvents
            : ("ontouchstart" in window);
        if (isTouch) {
            // If button already has focus on this cell, proceed normally.
            if (this._touchFocusedCellId === id) {
                this._clearTouchFocus();
                this.openResource(id, name, hasNotes);
                return;
            }
            // First tap — just reveal buttons.
            this._setTouchFocus(id);
            return;
        }
        this.openResource(id, name, hasNotes);
    }

    /** Set touch-focus on a cell (shows its overlay buttons). */
    _setTouchFocus(cellId) {
        this._touchFocusedCellId = cellId;
        // Add class to the matching <td> elements.
        this._applyTouchFocusClass();
    }

    /** Clear any active touch-focus. */
    _clearTouchFocus() {
        this._touchFocusedCellId = null;
        document.querySelectorAll(".rht_cell_touch_focus").forEach((el) => {
            el.classList.remove("rht_cell_touch_focus");
        });
    }

    /** Apply the focus CSS class to the currently focused cell <td>. */
    _applyTouchFocusClass() {
        // Remove from all first.
        document.querySelectorAll(".rht_cell_touch_focus").forEach((el) => {
            el.classList.remove("rht_cell_touch_focus");
        });
        if (this._touchFocusedCellId == null) return;
        // Find the <td> by data attribute.
        document.querySelectorAll(`[data-cell-id="${this._touchFocusedCellId}"]`).forEach((el) => {
            el.classList.add("rht_cell_touch_focus");
        });
    }

    /** Dismiss touch-focus when tapping outside the focused cell. */
    _onDocumentTouch(ev) {
        if (this._touchFocusedCellId == null) return;
        const focusedEl = document.querySelector(".rht_cell_touch_focus");
        if (focusedEl && focusedEl.contains(ev.target)) return;
        this._clearTouchFocus();
    }

    openResource(id, name, hasNotes) {
        if (this._studentMode) {
            if (!hasNotes || hasNotes === 'no') {
                return;
            }
            this.dialogService.add(ResourceNotesDialog, {
                resourceId: id,
                resourceName: name || "",
            });
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resources",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Open a notes dialog for a supporting-resource link. */
    onNotesClick(linkData) {
        if (!linkData) return;
        this.dialogService.add(ResourceNotesDialog, {
            resourceId: linkData.id,
            resourceName: linkData.name || "",
        });
    }

    /** Student-mode: open (or create) the latest submission for a quiz resource. */
    async onQuizClick(linkData) {
        if (!linkData?.id) return;
        const action = await this.orm.call(
            "aps.resources",
            "action_get_or_create_submission",
            [linkData.id],
        );
        this.actionService.doAction(action);
    }

    /**
     * Link interceptor passed to ResourceLinkButtons.
     * Returns true if the click was handled (skipping default behaviour).
     */
    interceptLink(linkData) {
        if (
            this._studentMode &&
            linkData?.type_name &&
            linkData.type_name.toLowerCase().includes("quiz")
        ) {
            this.onQuizClick(linkData);
            return true;
        }
        return false;
    }

    // ── Color helpers ────────────────────────────────────────────────

    _hexToRgb(hex) {
        hex = hex.replace(/^#/, "");
        if (hex.length === 3) {
            hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
        }
        const num = parseInt(hex, 16);
        return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
    }

    _lighten({ r, g, b }, amount) {
        return {
            r: Math.round(r + (255 - r) * amount),
            g: Math.round(g + (255 - g) * amount),
            b: Math.round(b + (255 - b) * amount),
        };
    }

    _rgbStr({ r, g, b }) {
        return `rgb(${r}, ${g}, ${b})`;
    }

    _subjectColorVars(color) {
        const DEFAULT = "#714B67";
        const base = this._hexToRgb(color || DEFAULT);
        return [
            `--rht-border-0: ${this._rgbStr(base)}`,
            `--rht-bg-0: ${this._rgbStr(this._lighten(base, 0.88))}`,
            `--rht-bg-0-hover: ${this._rgbStr(this._lighten(base, 0.82))}`,
            `--rht-border-1: ${this._rgbStr(this._lighten(base, 0.35))}`,
            `--rht-bg-1: ${this._rgbStr(this._lighten(base, 0.93))}`,
            `--rht-bg-1-hover: ${this._rgbStr(this._lighten(base, 0.87))}`,
            `--rht-border-2: ${this._rgbStr(this._lighten(base, 0.50))}`,
            `--rht-bg-2: ${this._rgbStr(this._lighten(base, 0.96))}`,
            `--rht-bg-2-hover: ${this._rgbStr(this._lighten(base, 0.91))}`,
            `--rht-border-3: ${this._rgbStr(this._lighten(base, 0.65))}`,
            `--rht-bg-3: #fff`,
            `--rht-bg-3-hover: ${this._rgbStr(this._lighten(base, 0.96))}`,
            `--rht-header: ${this._rgbStr(base)}`,
        ].join("; ");
    }

    /**
     * Build a 45-degree repeating-linear-gradient stripe background
     * for a cell that matches an active tag.
     */
    _tagStripeStyle(tagColorHex) {
        const base = this._hexToRgb(tagColorHex);
        const c1 = this._rgbStr(this._lighten(base, 0.75));
        const c2 = this._rgbStr(this._lighten(base, 0.85));
        return `repeating-linear-gradient(45deg, ${c1}, ${c1} 6px, ${c2} 6px, ${c2} 12px)`;
    }

    // ── Rendering helpers ────────────────────────────────────────────

    getCellClass(cell) {
        const d = Math.min(cell.depth, 3);
        const parity = ((cell.rootIndex ?? 0) % 2 === 0) ? 'even' : 'odd';
        const noNotes = this._studentMode && (!cell.has_notes || cell.has_notes === 'no');
        return `rht_cell rht_depth_${d} rht_root_${parity}${noNotes ? ' rht_cell_no_notes' : ''}`;
    }

    /**
     * Build cell inline style respecting tag color_applies_to_fill / color_applies_to_border.
     * Multiple active tags can match: first fill-tag wins for background,
     * first border-tag wins for border.  Both are resolved independently.
     */
    getCellStyle(cell) {
        if (!cell.tag_ids || !cell.tag_ids.length) return "";
        let fillStyle = "";
        let borderStyle = "";
        for (const tag of this.state.hierarchyTags) {
            if (!tag.color_hex) continue;
            if (!this.state.activeTagIds.has(tag.id)) continue;
            if (!cell.tag_ids.includes(tag.id)) continue;
            if (!fillStyle && tag.color_applies_to_fill) {
                fillStyle = `background: ${this._tagStripeStyle(tag.color_hex)} !important;`;
            }
            if (!borderStyle && tag.color_applies_to_border) {
                borderStyle = `border-color: ${tag.color_hex} !important;`;
            }
            if (fillStyle && borderStyle) break;
        }
        return fillStyle + borderStyle;
    }

    /**
     * Return inline style for the tag chip label in the toolbar.
     * Active chips get the stripe fill when color_applies_to_fill is set,
     * or a colored border when color_applies_to_border is set.
     */
    getTagChipStyle(tag) {
        const parts = [];
        if (tag.color_hex && tag.color_applies_to_border) {
            parts.push(`border-color: ${tag.color_hex} !important`);
        }
        if (tag.color_hex && tag.color_applies_to_fill && this.state.activeTagIds.has(tag.id)) {
            parts.push(`background: ${this._tagStripeStyle(tag.color_hex)} !important`);
        }
        return parts.join("; ");
    }

    getGroupStyle(group) {
        return "";
    }

    getSubjectIcon(group) {
        return group.icon ? `data:image/png;base64,${group.icon}` : "";
    }

    getTableStyle(group) {
        const width = group.total_cols * COL_WIDTH;
        return `width: ${width}px; table-layout: fixed;`;
        return `width: fit-content; table-layout: fixed;`;
    }
}

registry.category("actions").add("aps_resource_hierarchy_table", ResourceHierarchyTable);
