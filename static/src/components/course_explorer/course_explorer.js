import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount, useRef, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "aps_course_explorer";

// ─── Recursive tree node sub-component ────────────────────────────────

export class CourseExplorerTreeNode extends Component {
    static template = "aps_sis.CourseExplorerTreeNode";
    static props = {
        node: { type: Object },
        activeSectionId: { type: Number, optional: true },
        depth: { type: Number },
        expandedIds: { type: Object },
        onToggle: { type: Function },
        onNavigate: { type: Function },
    };
    static components = {}; // self-referential; set after class def

    get isExpanded() {
        return this.props.expandedIds.has(this.props.node.id);
    }

    get isActive() {
        return this.props.node.id === this.props.activeSectionId;
    }

    get hasChildren() {
        return this.props.node.has_children;
    }

    get indentStyle() {
        return `padding-left: ${this.props.depth * 20}px`;
    }

    onToggleClick(ev) {
        ev.stopPropagation();
        this.props.onToggle(this.props.node.id);
    }

    onNodeClick(ev) {
        ev.preventDefault();
        this.props.onNavigate(this.props.node.id);
    }
}
CourseExplorerTreeNode.components = { CourseExplorerTreeNode };

// ─── Main course explorer client-action component ─────────────────────

export class CourseExplorer extends Component {
    static template = "aps_sis.CourseExplorer";
    static components = { CourseExplorerTreeNode };
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.contentRef = useRef("contentPane");

        const saved = this._loadStorage();

        this.state = useState({
            loading: false,
            subjectCategories: [],
            selectedCategoryId: saved.selectedCategoryId || false,
            tree: [],
            contentSections: [],
            activeSectionId: saved.activeSectionId || false,
            sidebarCollapsed: saved.sidebarCollapsed || false,
        });

        // Expanded node IDs tracked as a plain Set (not reactive)
        this._expandedIds = new Set(saved.expandedNodeIds || []);
        // Debounce timer for scroll persistence
        this._scrollTimer = null;
        // IntersectionObserver reference
        this._observer = null;

        onWillStart(async () => {
            await this._loadSubjectCategories();
            await this._loadData();
        });

        onMounted(() => {
            this._restoreScroll();
            this._setupIntersectionObserver();
            this._setupScrollListener();
        });

        onPatched(() => {
            // Re-observe sections after data changes (e.g. category filter)
            this._observeSections();
        });

        onWillUnmount(() => {
            if (this._observer) {
                this._observer.disconnect();
                this._observer = null;
            }
            if (this._scrollTimer) {
                clearTimeout(this._scrollTimer);
            }
        });
    }

    // ── LocalStorage helpers ─────────────────────────────────────────

    _loadStorage() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch {
            return {};
        }
    }

    _saveStorage() {
        try {
            const data = {
                expandedNodeIds: [...this._expandedIds],
                selectedCategoryId: this.state.selectedCategoryId,
                activeSectionId: this.state.activeSectionId,
                sidebarCollapsed: this.state.sidebarCollapsed,
                scrollPosition: this.contentRef.el
                    ? this.contentRef.el.scrollTop
                    : 0,
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch {
            /* quota exceeded */
        }
    }

    _restoreScroll() {
        const el = this.contentRef.el;
        if (!el) return;
        const saved = this._loadStorage();
        if (saved.scrollPosition) {
            // Use rAF to ensure DOM is ready
            requestAnimationFrame(() => {
                el.scrollTop = saved.scrollPosition;
            });
        }
    }

    // ── Data loading ─────────────────────────────────────────────────

    async _loadSubjectCategories() {
        this.state.subjectCategories = await this.orm.call(
            "aps.resources",
            "get_course_explorer_subject_categories",
            [],
        );
    }

    async _loadData() {
        // Don't load data if no subject category is selected
        if (!this.state.selectedCategoryId) {
            this.state.tree = [];
            this.state.contentSections = [];
            this.state.activeSectionId = false;
            return;
        }
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "aps.resources",
                "get_course_explorer_data",
                [this.state.selectedCategoryId],
            );
            this.state.tree = result.tree || [];
            // Wrap HTML content in Markup so t-out renders it as HTML
            this.state.contentSections = (result.contentSections || []).map((sec) => ({
                ...sec,
                html: sec.html ? markup(sec.html) : "",
            }));
            this.state.activeSectionId = false;
        } catch (err) {
            console.error("CourseExplorer: failed to load data", err);
            this.state.tree = [];
            this.state.contentSections = [];
        } finally {
            this.state.loading = false;
        }
    }

    // ── User actions ─────────────────────────────────────────────────

    async onCategoryChange(ev) {
        const val = ev.target.value;
        this.state.selectedCategoryId = val ? parseInt(val, 10) : false;
        this._expandedIds.clear();
        this._saveStorage();
        await this._loadData();
        this._restoreScroll();
    }

    toggleSidebar() {
        this.state.sidebarCollapsed = !this.state.sidebarCollapsed;
        this._saveStorage();
    }

    toggleNode(nodeId) {
        if (this._expandedIds.has(nodeId)) {
            this._expandedIds.delete(nodeId);
        } else {
            this._expandedIds.add(nodeId);
        }
        // Trigger re-render by reassigning a reference (Set is not reactive)
        this._forceTreeUpdate();
        this._saveStorage();
    }

    expandAll() {
        this._collectAllIds(this.state.tree);
        this._forceTreeUpdate();
        this._saveStorage();
    }

    collapseAll() {
        this._expandedIds.clear();
        this._forceTreeUpdate();
        this._saveStorage();
    }

    _collectAllIds(nodes) {
        for (const n of nodes) {
            if (n.has_children) {
                this._expandedIds.add(n.id);
                this._collectAllIds(n.children);
            }
        }
    }

    /** Force tree re-render by toggling a dummy flag. */
    _forceTreeUpdate() {
        this.state._treeVersion = (this.state._treeVersion || 0) + 1;
    }

    scrollToSection(resourceId) {
        const el = this.contentRef.el;
        if (!el) return;
        const target = el.querySelector(`#ce-section-${resourceId}`);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
            this.state.activeSectionId = resourceId;
            this._saveStorage();
        }
    }

    // ── Scroll sync ──────────────────────────────────────────────────

    _setupScrollListener() {
        const el = this.contentRef.el;
        if (!el) return;
        el.addEventListener("scroll", this._onScroll.bind(this), { passive: true });
    }

    _onScroll() {
        // Debounce save to localStorage
        if (this._scrollTimer) clearTimeout(this._scrollTimer);
        this._scrollTimer = setTimeout(() => {
            this._saveStorage();
        }, 200);
    }

    _setupIntersectionObserver() {
        const el = this.contentRef.el;
        if (!el) return;

        this._observer = new IntersectionObserver(
            (entries) => {
                // Find the most visible section at the top
                let bestEntry = null;
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        if (
                            !bestEntry ||
                            entry.boundingClientRect.top <
                                bestEntry.boundingClientRect.top
                        ) {
                            bestEntry = entry;
                        }
                    }
                }
                if (bestEntry) {
                    const id = parseInt(bestEntry.target.dataset.resourceId, 10);
                    if (id && id !== this.state.activeSectionId) {
                        this.state.activeSectionId = id;
                        this._highlightTreeNode(id);
                        this._saveStorage();
                    }
                }
            },
            {
                root: el,
                rootMargin: "-10% 0px -70% 0px",
                threshold: 0,
            },
        );

        // Observe all section elements
        this._observeSections();
    }

    _observeSections() {
        if (!this._observer) return;
        this._observer.disconnect();
        const el = this.contentRef.el;
        if (!el) return;
        const sections = el.querySelectorAll(".ce_content_section");
        sections.forEach((s) => this._observer.observe(s));
    }

    /** Ensure the active tree node is visible (expand ancestors if needed). */
    _highlightTreeNode(resourceId) {
        // Find the tree node element and scroll it into view in the tree pane
        const treeEl = document.querySelector(".ce_tree_container");
        if (!treeEl) return;
        const nodeEl = treeEl.querySelector(`[data-node-id="${resourceId}"]`);
        if (nodeEl) {
            nodeEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    }

    // ── Rendering helpers ────────────────────────────────────────────

    getTreeVersion() {
        return this.state._treeVersion || 0;
    }
}

registry.category("actions").add("course_explorer", CourseExplorer);