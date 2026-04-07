import { Component, useState, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { ResourceNotesDialog } from "./resource_notes_dialog";

const STORAGE_KEY = "aps_resource_hierarchy_table";
const COL_WIDTH = 120; // px per leaf column

export class ResourceHierarchyTable extends Component {
    static template = "aps_sis.ResourceHierarchyTable";
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
            activeTagIds: new Set(saved.activeTagIds || []),
        });

        this.scrollRef = { el: null };

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
        });

        onPatched(() => {
            this._bindScrollRef();
        });
    }

    // ── LocalStorage persistence ─────────────────────────────────────

    _loadStorage() {
        try {
            const key = STORAGE_KEY + (this.props.storageKeySuffix || "");
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

        const walk = (node, depth) => {
            const isLeaf = !node.children || !node.children.length;
            rows[depth].push({
                id: node.id,
                name: node.name,
                colspan: node.colspan,
                rowspan: isLeaf ? maxDepth - depth + 1 : 1,
                depth: depth,
                tag_ids: node.tag_ids || [],
                hasHiddenChildren: !!node._hasHiddenChildren,
                hasVisibleChildren: !isLeaf,
                minimized: !!node._minimized,
            });
            if (!isLeaf) {
                for (const child of node.children) {
                    walk(child, depth + 1);
                }
            }
        };

        for (const root of roots) {
            walk(root, 0);
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

    openResource(id, name) {
        if (this._studentMode) {
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
        return `rht_cell rht_depth_${d}`;
    }

    /**
     * If any active tag matches the cell, return an inline style
     * with the 45-degree stripe background.  First matching tag wins.
     */
    getCellStyle(cell) {
        if (!cell.tag_ids || !cell.tag_ids.length) return "";
        for (const tag of this.state.hierarchyTags) {
            if (tag.color_hex && this.state.activeTagIds.has(tag.id) && cell.tag_ids.includes(tag.id)) {
                return `background: ${this._tagStripeStyle(tag.color_hex)} !important;`;
            }
        }
        return "";
    }

    getGroupStyle(group) {
        return this._subjectColorVars(group.color);
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
