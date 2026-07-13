import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount, useRef, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { ImageViewerDialog } from "@aui_enhancements/js/image_viewer_dialog";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";

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
        // expandedIds may be an array (reactive) or a Set
        const ids = this.props.expandedIds;
        return ids.has
            ? ids.has(this.props.node.id)
            : ids.includes(this.props.node.id);
    }

    get isActive() {
        // Highlight this node if the active section belongs to it
        // (i.e., the active section is in this node's subtree)
        const highlightIds = this.props.node.highlightIds;
        if (highlightIds && this.props.activeSectionId) {
            // highlightIds may be a Set or an array (JSON-serialized)
            const check = highlightIds.has
                ? highlightIds.has(this.props.activeSectionId)
                : highlightIds.includes(this.props.activeSectionId);
            if (check) return true;
        }
        const sectionId = this.props.node.sectionId || this.props.node.id;
        return sectionId === this.props.activeSectionId;
    }

    get hasChildren() {
        return this.props.node.has_children;
    }

    get indentStyle() {
        return `padding-left: ${this.props.depth * 20}px`;
    }

    get avgColor() {
        return getColorForPercent(this.props.node.avgWeightedResult || 0);
    }

    onToggleClick(ev) {
        ev.stopPropagation();
        this.props.onToggle(this.props.node.id);
    }

    onNodeClick(ev) {
        ev.preventDefault();
        const sectionId = this.props.node.sectionId || this.props.node.id;
        this.props.onNavigate(sectionId);
    }
}
CourseExplorerTreeNode.components = { CourseExplorerTreeNode };

// ─── Main course explorer client-action component ─────────────────────

export class CourseExplorer extends Component {
    static template = "aps_sis.CourseExplorer";
    static components = { CourseExplorerTreeNode, PercentPie };
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        className: { type: String, optional: true },
        updateActionState: { type: Function, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.contentRef = useRef("contentPane");

        const saved = this._loadStorage();

        this.state = useState({
            loading: false,
            subjectCategories: [],
            selectedCategoryId: saved.selectedCategoryId || false,
            tree: [],
            contentSections: [],
            activeSectionId: saved.activeSectionId || 0,
            sidebarCollapsed: saved.sidebarCollapsed || false,
        });

        // Expanded node IDs tracked reactively as an array (for OWL reactivity)
        this.state.expandedNodeIds = saved.expandedNodeIds || [];
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
            this._setupScrollObserver();
            this._setupScrollListener();
            this._setupImageClickHandler();
            this._renderMath();
            this._addHeadingClasses();
            this._setupTooltips();
        });

        onPatched(() => {
            this._renderMath();
            this._addHeadingClasses();
            this._setupTooltips();
        });

        onWillUnmount(() => {
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

    _renderMath() {
        const el = this.contentRef.el;
        if (!el || !window.renderMathInElement) return;
        window.renderMathInElement(el, {
            delimiters: [
                { left: "$$", right: "$$", display: true },
                { left: "$", right: "$", display: false },
                { left: "\\(", right: "\\)", display: false },
                { left: "\\[", right: "\\]", display: true },
            ],
            throwOnError: false,
            ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
            ignoredClasses: ["katex", "katex-html"],
        });
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
            this.state.activeSectionId = 0;
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
            this.state.activeSectionId = 0;
            // Fetch student progress data
            await this._loadProgressData();
        } catch (err) {
            console.error("CourseExplorer: failed to load data", err);
            this.state.tree = [];
            this.state.contentSections = [];
        } finally {
            this.state.loading = false;
        }
    }

    async _loadProgressData() {
        try {
            // Current user's partner ID is available directly from the user service
            const partnerId = user.partnerId;
            if (!partnerId) return;
            const progressData = await this.orm.call(
                "aps.resources",
                "get_course_explorer_progress",
                [partnerId],
            );
            // Apply progress to tree nodes
            this._applyProgressToTree(this.state.tree, progressData);
            // Apply progress to content sections (hasCheckbox for visible sections)
            this.state.contentSections = this.state.contentSections.map((sec) => {
                const pd = progressData[sec.id];
                return {
                    ...sec,
                    hasCheckbox: !sec.headingOnly && sec.visible && !!pd,
                    checked: pd ? pd.submissionState === "submitted" : false,
                    progress: pd ? pd.progress : 0,
                };
            });
            this._forceTreeUpdate();
        } catch (err) {
            console.error("CourseExplorer: failed to load progress", err);
        }
    }

    _applyProgressToTree(nodes, progressData) {
        for (const node of nodes) {
            const pd = progressData[node.id];
            if (pd) {
                node.progress = pd.progress || 0;
                node.submissionState = pd.submissionState || null;
            } else {
                node.progress = 0;
                node.submissionState = null;
            }
            if (node.children) {
                this._applyProgressToTree(node.children, progressData);
            }
        }
    }

    async onToggleCompletion(resourceId) {
        try {
            const result = await this.orm.call(
                "aps.resources",
                "toggle_resource_completion",
                [resourceId],
            );
            if (result.error) {
                console.error("CourseExplorer: toggle failed", result.error);
                return;
            }
            // Update the content section
            this.state.contentSections = this.state.contentSections.map((sec) => {
                if (sec.id === resourceId) {
                    return {
                        ...sec,
                        checked: result.newState === "submitted",
                        progress: result.newProgress,
                    };
                }
                return sec;
            });
            // Update tree node progress
            this._updateTreeNodeProgress(this.state.tree, resourceId, result.newProgress, result.newState);
            // Update parent progress
            if (result.parentUpdates) {
                for (const [parentId, update] of Object.entries(result.parentUpdates)) {
                    this._updateTreeNodeProgress(this.state.tree, parseInt(parentId), update.progress, null);
                }
            }
            this._forceTreeUpdate();
        } catch (err) {
            console.error("CourseExplorer: toggle completion failed", err);
        }
    }

    _updateTreeNodeProgress(nodes, resourceId, progress, state) {
        for (const node of nodes) {
            if (node.id === resourceId) {
                node.progress = progress;
                if (state !== null) node.submissionState = state;
                return true;
            }
            if (node.children && this._updateTreeNodeProgress(node.children, resourceId, progress, state)) {
                return true;
            }
        }
        return false;
    }

    // ── User actions ─────────────────────────────────────────────────

    async onCategoryChange(ev) {
        const val = ev.target.value;
        this.state.selectedCategoryId = val ? parseInt(val, 10) : false;
        this._expandedIds.clear();
        this.state.expandedNodeIds = [];
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
        // Sync reactive state with the Set
        this.state.expandedNodeIds = [...this._expandedIds];
        this._saveStorage();
    }

    expandAll() {
        this._collectAllIds(this.state.tree);
        this.state.expandedNodeIds = [...this._expandedIds];
        this._saveStorage();
    }

    collapseAll() {
        this._expandedIds.clear();
        this.state.expandedNodeIds = [];
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

    scrollToSection(sectionId) {
        if (!sectionId) return;
        const el = this.contentRef.el;
        if (!el) return;
        const target = el.querySelector(`#ce-section-${sectionId}`);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
            this.state.activeSectionId = sectionId;
            this._saveStorage();
        }
    }

    scrollToQuiz(ev, sectionId) {
        ev.preventDefault();
        const el = this.contentRef.el;
        if (!el) return;
        const target = el.querySelector(`#ce-quiz-${sectionId}`);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    get isApsManager() {
        return user.hasGroup("aps_sis.group_aps_manager");
    }

    async openResource(ev, resourceId) {
        ev.preventDefault();
        ev.stopPropagation();
        try {
            const result = await this.orm.call(
                "aps.resources",
                "get_formview_action",
                [resourceId],
            );
            if (result) {
                this.action.doAction(result);
            }
        } catch (err) {
            console.error("CourseExplorer: failed to open resource", err);
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

    _setupScrollObserver() {
        const el = this.contentRef.el;
        if (!el) return;

        // Use a scroll listener to find which section is closest to the
        // top of the viewport. More reliable than IntersectionObserver
        // for large sections.
        el.addEventListener("scroll", this._onScrollDetect.bind(this), {
            passive: true,
        });
    }

    _onScrollDetect() {
        const el = this.contentRef.el;
        if (!el) return;
        const sections = el.querySelectorAll(".ce_content_section");
        if (!sections.length) return;

        // Find the last section whose top is at or above the current
        // scroll position — that's the section whose sticky heading
        // is visible at the top of the viewport.
        const scrollTop = el.scrollTop;
        let bestId = null;

        for (const s of sections) {
            if (s.offsetTop <= scrollTop + 2) {
                bestId = parseInt(s.dataset.resourceId, 10);
            }
        }

        if (bestId && bestId !== this.state.activeSectionId) {
            this.state.activeSectionId = bestId;
            this._highlightTreeNode(bestId);
            this._saveStorage();
        }
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

    // ── Image viewer ────────────────────────────────────────────────

    _setupImageClickHandler() {
        const el = this.contentRef.el;
        if (!el) return;
        el.addEventListener("click", this._onContentClick.bind(this));
    }

    _onContentClick(ev) {
        const img = ev.target.closest(".ce_section_body img");
        if (!img) return;
        ev.preventDefault();
        ev.stopPropagation();
        const src = img.getAttribute("src") || img.src;
        if (!src) return;

        // Resolve the clicked image URL to absolute
        let absoluteSrc = src;
        try {
            absoluteSrc = new URL(src, window.location.href).href;
        } catch {
            // Keep original if URL parsing fails.
        }

        // Collect ALL images from the content pane in document order,
        // excluding images inside page-ref links (same logic as the
        // standard image_viewer_button service).
        const embeddedImages = [];
        let clickedIndex = 0;
        const el = this.contentRef.el;
        if (el) {
            const allImgs = Array.from(el.querySelectorAll(".ce_section_body img")).filter(
                (i) => (i.getAttribute("src") || i.src)
            );
            allImgs.forEach((i, idx) => {
                const imgSrc = i.getAttribute("src") || i.src || "";
                let absUrl = imgSrc;
                try {
                    absUrl = new URL(imgSrc, window.location.href).href;
                } catch {
                    // Keep original.
                }
                embeddedImages.push(absUrl);
                if (i === img) {
                    clickedIndex = idx;
                }
            });
        }

        const hasMultiple = embeddedImages.length > 1;
        this.dialog.add(ImageViewerDialog, {
            imageConfig: {
                directUrl: absoluteSrc,
                imageUrl: absoluteSrc,
                embeddedImages: hasMultiple ? embeddedImages : [],
                pageNumber: hasMultiple ? clickedIndex + 1 : 1,
            },
        });
    }

    // ── Quiz submission ─────────────────────────────────────────────

    async openQuizSubmission(ev, quizId) {
        ev.preventDefault();
        ev.stopPropagation();
        try {
            const result = await this.orm.call(
                "aps.resources",
                "action_get_or_create_submission",
                [quizId],
            );
            if (result) {
                this.action.doAction(result);
            }
        } catch (err) {
            console.error("CourseExplorer: failed to open quiz submission", err);
        }
    }

    // ── Overall course progress ──────────────────────────────────────

    _collectTreeValues(nodes, field) {
        const values = [];
        for (const node of nodes) {
            const val = node[field];
            if (typeof val === "number") {
                values.push(val);
            }
            if (node.children && node.children.length) {
                values.push(...this._collectTreeValues(node.children, field));
            }
        }
        return values;
    }

    get overallProgress() {
        const values = this._collectTreeValues(this.state.tree, "progress");
        if (!values.length) return 0;
        return Math.round(values.reduce((a, b) => a + b, 0) / values.length);
    }

    get overallAvgScore() {
        const values = this._collectTreeValues(this.state.tree, "avgWeightedResult")
            .filter((v) => v > 0);
        if (!values.length) return 0;
        return Math.round(values.reduce((a, b) => a + b, 0) / values.length);
    }

    get overallColor() {
        return getColorForPercent(this.overallAvgScore);
    }

    // ── Heading level classes ────────────────────────────────────────

    _addHeadingClasses() {
        const el = this.contentRef.el;
        if (!el) return;
        el.querySelectorAll(
            ".ce_section_body h1, .ce_section_body h2, .ce_section_body h3, .ce_section_body h4, .ce_section_body h5, .ce_section_body h6"
        ).forEach((h) => {
            const level = parseInt(h.tagName[1], 10);
            if (level && !h.classList.contains(`l${level}`)) {
                h.classList.add(`l${level}`);
            }
        });
    }

    _setupTooltips() {
        const el = this.contentRef.el;
        if (!el) return;
        const treeControls = document.querySelector(".ce_tree_controls");
        const cells = [];
        if (treeControls) {
            cells.push(...treeControls.querySelectorAll(".ce_progress_cell"));
        }
        if (el) {
            cells.push(...el.querySelectorAll(".ce_progress_cell"));
        }
        cells.forEach((cell) => {
            const tooltip = cell.querySelector(".ce_progress_tooltip");
            if (!tooltip) return;
            cell.addEventListener("mouseenter", () => {
                const rect = cell.getBoundingClientRect();
                tooltip.style.left = `${rect.right - 160}px`;
                tooltip.style.top = `${rect.top - 8}px`;
            });
        });
    }

    // ── Rendering helpers ────────────────────────────────────────────

    getTreeVersion() {
        return this.state._treeVersion || 0;
    }
}

registry.category("actions").add("course_explorer", CourseExplorer);