import { Component, useState, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "aps_resource_hierarchy";

export class ResourceHierarchy extends Component {
    static template = "aps_sis.ResourceHierarchy";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        const saved = this._loadStorage();
        // Allow action context to pass a default subject
        const ctxSubject = this.props.action?.context?.default_subject_id || false;

        this.state = useState({
            loading: true,
            subjects: [],
            selectedSubjectId: ctxSubject || saved.selectedSubjectId || false,
            hierarchyData: [],
            zoom: saved.zoom || 1,
            scrollLeft: saved.scrollLeft || 0,
        });

        this.gridRef = { el: null };

        onWillStart(async () => {
            await this._loadSubjects();
            await this._loadHierarchy();
        });

        onMounted(() => {
            this._bindGridRef();
            this._restoreScroll();
            this._drawConnectors();
        });

        onPatched(() => {
            this._bindGridRef();
            this._drawConnectors();
        });
    }

    // ── Storage ──────────────────────────────────────────────────────

    _loadStorage() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch {
            return {};
        }
    }

    _saveStorage() {
        const el = this.gridRef.el;
        const data = {
            zoom: this.state.zoom,
            scrollLeft: el ? el.scrollLeft : this.state.scrollLeft,
            selectedSubjectId: this.state.selectedSubjectId,
        };
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch { /* quota exceeded */ }
    }

    _bindGridRef() {
        const el = document.querySelector(".rh_scroll_container");
        if (el && el !== this.gridRef.el) {
            this.gridRef.el = el;
            el.addEventListener("scroll", () => {
                this.state.scrollLeft = el.scrollLeft;
                this._saveStorage();
            });
        }
    }

    _restoreScroll() {
        const el = this.gridRef.el;
        if (el && this.state.scrollLeft) {
            el.scrollLeft = this.state.scrollLeft;
        }
    }

    _drawConnectors() {
        // Draw SVG lines connecting each child node to its parent nodes.
        // We find the center-bottom of each parent card and the center-top
        // of the child card, then draw a curved path between them.
        const root = document.querySelector(".rh_zoom_wrapper");
        if (!root) return;

        // Clear previous connector overlays
        root.querySelectorAll(".rh_connector_overlay").forEach((el) => el.remove());

        const svgs = root.querySelectorAll(".rh_connector_svg");
        for (const svg of svgs) {
            // Clear previous drawing
            svg.innerHTML = "";
            const nodeId = parseInt(svg.dataset.nodeId, 10);
            let parentIds;
            try {
                parentIds = JSON.parse(svg.dataset.parentIds || "[]");
            } catch {
                continue;
            }
            if (!parentIds.length) continue;

            // Find the child card element
            const childCard = svg.closest(".rh_node_wrapper")?.querySelector(".rh_node");
            if (!childCard) continue;

            const rootRect = root.getBoundingClientRect();

            for (const pid of parentIds) {
                const parentCard = root.querySelector(`.rh_node[data-resource-id="${pid}"]`);
                if (!parentCard) continue;

                const pRect = parentCard.getBoundingClientRect();
                const cRect = childCard.getBoundingClientRect();

                // Coordinates relative to the zoom wrapper
                const x1 = pRect.left + pRect.width / 2 - rootRect.left;
                const y1 = pRect.bottom - rootRect.top;
                const x2 = cRect.left + cRect.width / 2 - rootRect.left;
                const y2 = cRect.top - rootRect.top;

                // Position the SVG to cover the area between the points
                const minX = Math.min(x1, x2) - 4;
                const maxX = Math.max(x1, x2) + 4;
                const svgWidth = maxX - minX;
                const svgHeight = y2 - y1;

                if (svgHeight <= 0) continue;

                const ns = "http://www.w3.org/2000/svg";
                const svgEl = document.createElementNS(ns, "svg");
                svgEl.setAttribute("class", "rh_connector_overlay");
                svgEl.setAttribute("width", svgWidth);
                svgEl.setAttribute("height", svgHeight);
                svgEl.style.position = "absolute";
                svgEl.style.left = `${minX}px`;
                svgEl.style.top = `${y1}px`;
                svgEl.style.pointerEvents = "none";
                svgEl.style.overflow = "visible";

                const lx1 = x1 - minX;
                const lx2 = x2 - minX;
                const ly1 = 0;
                const ly2 = svgHeight;
                const cy = svgHeight / 2;

                const path = document.createElementNS(ns, "path");
                path.setAttribute("d", `M${lx1},${ly1} C${lx1},${cy} ${lx2},${cy} ${lx2},${ly2}`);
                path.setAttribute("class", "rh_connector_line");
                svgEl.appendChild(path);
                root.appendChild(svgEl);
            }
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

    async _loadHierarchy() {
        this.state.loading = true;
        const subjectId = this.state.selectedSubjectId || false;
        this.state.hierarchyData = await this.orm.call(
            "aps.resources",
            "get_hierarchy_data",
            [subjectId],
        );
        this.state.loading = false;
    }

    // ── Actions ──────────────────────────────────────────────────────

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

    get zoomStyle() {
        return `transform: scale(${this.state.zoom}); transform-origin: top left;`;
    }

    openResource(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resources",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ── Rendering helpers ────────────────────────────────────────────

    getLevelFontSize(levelIdx, totalLevels) {
        // Top levels get larger text, gradually shrinking
        const maxSize = 1.4;
        const minSize = 0.8;
        if (totalLevels <= 1) return `${maxSize}em`;
        const step = (maxSize - minSize) / (totalLevels - 1);
        return `${(maxSize - step * levelIdx).toFixed(2)}em`;
    }

    getLevelPadding(levelIdx) {
        // More vertical padding for top levels
        const base = Math.max(6, 24 - levelIdx * 4);
        return `${base}px 16px`;
    }

    getNodeStyle(node) {
        if (node.type_color) {
            return `border-left: 4px solid ${node.type_color};`;
        }
        return "";
    }

    toJSON(value) {
        return JSON.stringify(value);
    }
}

registry.category("actions").add("aps_resource_hierarchy", ResourceHierarchy);
