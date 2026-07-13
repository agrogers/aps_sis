import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount, useRef, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { ImageViewerDialog } from "@aui_enhancements/js/image_viewer_dialog";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";

const STORAGE_KEY = "aps_course_explorer";
const DEBUG_STORAGE_KEY = "aps_course_explorer_debug";
const DEBUG_URL_PARAM = "ce_debug";

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
        // Show light gray when quizzes exist but none have been scored yet
        if (!this.props.node.avgWeightedResult) return '#d3d3d3';
        return getColorForPercent(this.props.node.avgWeightedResult);
    }

    get allQuizzesSubmitted() {
        return this.props.node.allQuizzesSubmitted !== false;
    }

    get gradientId() {
        return 'quiz-grad-' + this.props.node.id;
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
        this._instanceId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
        this._debugEnabled = this._isDebugEnabled();
        this._patchCount = 0;

        this._boundOnScroll = this._onScroll.bind(this);
        this._boundOnScrollDetect = this._onScrollDetect.bind(this);
        this._boundOnContentClick = this._onContentClick.bind(this);
        this._boundWindowError = this._onWindowError.bind(this);
        this._boundWindowRejection = this._onUnhandledRejection.bind(this);
        this._mathRenderVersion = 0;
        this._lastRenderedMathVersion = -1;
        this._renderMathRaf = 0;
        this._loadDataRequestId = 0;
        this._lastTooltipVersion = -1;

        this._installInsertBeforeProbe();
        window.addEventListener("error", this._boundWindowError);
        window.addEventListener("unhandledrejection", this._boundWindowRejection);

        const saved = this._loadStorage();
        this._debug("setup", { saved });

        this.state = useState({
            loading: false,
            subjectCategories: [],
            selectedCategoryId: saved.selectedCategoryId || false,
            tree: [],
            contentSections: [],
            contentVersion: 0,
            activeSectionId: saved.activeSectionId || 0,
            sidebarCollapsed: saved.sidebarCollapsed || false,
            isManager: false,
        });

        // Expanded node IDs tracked reactively as an array (for OWL reactivity)
        this.state.expandedNodeIds = saved.expandedNodeIds || [];
        this._expandedIds = new Set(saved.expandedNodeIds || []);
        // Debounce timer for scroll persistence
        this._scrollTimer = null;
        // IntersectionObserver reference
        this._observer = null;

        onWillStart(async () => {
            this._debug("onWillStart:start", this._stateSnapshot());
            this.state.isManager = await user.hasGroup("aps_sis.group_aps_manager");
            await this._loadSubjectCategories();
            await this._loadData();
            this._debug("onWillStart:done", this._stateSnapshot());
        });

        onMounted(() => {
            this._debug("onMounted", this._stateSnapshot());
            this._restoreScroll();
            this._setupScrollObserver();
            this._setupScrollListener();
            this._setupImageClickHandler();
            this._renderMathIfNeeded();
            this._setupTooltips();
        });

        onPatched(() => {
            this._patchCount += 1;
            if (this._shouldLogPatch()) {
                this._debug("onPatched", {
                    patchCount: this._patchCount,
                    ...this._stateSnapshot(),
                });
            }
            this._renderMathIfNeeded();
            this._setupTooltipsIfNeeded();
        });

        onWillUnmount(() => {
            this._debug("onWillUnmount", this._stateSnapshot());
            if (this._scrollTimer) {
                clearTimeout(this._scrollTimer);
            }
            if (this._renderMathRaf) {
                cancelAnimationFrame(this._renderMathRaf);
                this._renderMathRaf = 0;
            }
            const el = this.contentRef.el;
            if (el) {
                el.removeEventListener("scroll", this._boundOnScroll);
                el.removeEventListener("scroll", this._boundOnScrollDetect);
                el.removeEventListener("click", this._boundOnContentClick);
            }
            window.removeEventListener("error", this._boundWindowError);
            window.removeEventListener("unhandledrejection", this._boundWindowRejection);
        });
    }

    _isDebugEnabled() {
        try {
            const stored = String(localStorage.getItem(DEBUG_STORAGE_KEY) || "").toLowerCase();
            if (["1", "true", "on", "yes"].includes(stored)) {
                return true;
            }
        } catch {
            // Ignore localStorage access errors.
        }
        try {
            const params = new URLSearchParams(window.location.search);
            const value = String(params.get(DEBUG_URL_PARAM) || "").toLowerCase();
            return ["1", "true", "on", "yes"].includes(value);
        } catch {
            return false;
        }
    }

    _debug(event, data = {}) {
        if (!this._debugEnabled) return;
        console.log(`[CourseExplorer ${this._instanceId}] ${event}`, data);
    }

    _shouldLogPatch() {
        return this._patchCount <= 10 || this._patchCount % 25 === 0;
    }

    _stateSnapshot() {
        return {
            selectedCategoryId: this.state.selectedCategoryId,
            loading: this.state.loading,
            treeCount: this.state.tree.length,
            sectionCount: this.state.contentSections.length,
            activeSectionId: this.state.activeSectionId,
            contentVersion: this.state.contentVersion,
            mathRenderVersion: this._mathRenderVersion,
            lastRenderedMathVersion: this._lastRenderedMathVersion,
        };
    }

    _onWindowError(ev) {
        const message = ev?.message || "";
        if (message.includes("insertBefore") || message.includes("OwlError")) {
            this._debug("window.error", {
                message,
                filename: ev?.filename,
                lineno: ev?.lineno,
                colno: ev?.colno,
                stack: ev?.error?.stack,
                ...this._stateSnapshot(),
            });
        }
    }

    _onUnhandledRejection(ev) {
        const reason = ev?.reason;
        const message = reason?.message || String(reason || "");
        const causeMessage = reason?.cause?.message || String(reason?.cause || "");
        if (
            message.includes("insertBefore") ||
            message.includes("OwlError") ||
            causeMessage.includes("insertBefore") ||
            causeMessage.includes("OwlError")
        ) {
            this._debug("window.unhandledrejection", {
                message,
                causeMessage,
                stack: reason?.stack,
                causeStack: reason?.cause?.stack,
                reason,
                ...this._stateSnapshot(),
            });
        }
    }

    _installInsertBeforeProbe() {
        if (!this._debugEnabled) {
            return;
        }
        if (window.__ceInsertBeforeProbeInstalled) {
            return;
        }
        const original = Node.prototype.insertBefore;
        const describeNode = (node) => {
            if (!node) return null;
            return {
                nodeType: node.nodeType,
                nodeName: node.nodeName,
                id: node.id || null,
                className: node.className || null,
                childNodes: node.childNodes ? node.childNodes.length : null,
            };
        };

        Node.prototype.insertBefore = function (newNode, referenceNode) {
            try {
                return original.call(this, newNode, referenceNode);
            } catch (err) {
                const message = err?.message || String(err || "");
                if (
                    message.includes("insertBefore") ||
                    message.includes("not a child") ||
                    message.includes("child of this node")
                ) {
                    console.error("[CourseExplorer insertBefore probe]", {
                        message,
                        errorStack: err?.stack,
                        parent: describeNode(this),
                        reference: describeNode(referenceNode),
                        newNode: describeNode(newNode),
                        referenceIsChild: referenceNode
                            ? Array.from(this.childNodes || []).includes(referenceNode)
                            : null,
                        patchStack: new Error("insertBefore probe stack").stack,
                    });
                }
                throw err;
            }
        };

        window.__ceInsertBeforeProbeInstalled = true;
        window.__ceInsertBeforeProbeOriginal = original;
        this._debug("insertBeforeProbe:installed", {});
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
        try {
            const bodies = Array.from(el.querySelectorAll(".ce_section_body"));
            const options = {
                delimiters: [
                    { left: "$$", right: "$$", display: true },
                    { left: "$", right: "$", display: false },
                    { left: "\\(", right: "\\)", display: false },
                    { left: "\\[", right: "\\]", display: true },
                ],
                throwOnError: false,
                ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
                ignoredClasses: ["katex", "katex-html"],
            };
            bodies.forEach((body) => {
                window.renderMathInElement(body, options);
            });
            this._debug("renderMath:done", {
                ...this._stateSnapshot(),
                bodyCount: bodies.length,
            });
        } catch (err) {
            this._debug("renderMath:error", {
                message: err?.message,
                stack: err?.stack,
                ...this._stateSnapshot(),
            });
        }
    }

    _renderMathIfNeeded() {
        if (this._lastRenderedMathVersion === this._mathRenderVersion) {
            return;
        }
        if (this._renderMathRaf) {
            cancelAnimationFrame(this._renderMathRaf);
            this._renderMathRaf = 0;
        }
        const targetVersion = this._mathRenderVersion;
        this._renderMathRaf = requestAnimationFrame(() => {
            this._renderMathRaf = 0;
            if (this._lastRenderedMathVersion === targetVersion) {
                return;
            }
            this._lastRenderedMathVersion = targetVersion;
            this._debug("renderMath:schedule", { targetVersion });
            this._renderMath();
        });
    }

    // ── Data loading ─────────────────────────────────────────────────

    async _loadSubjectCategories() {
        this.state.subjectCategories = await this.orm.call(
            "aps.resources",
            "get_course_explorer_subject_categories",
            [],
        );
        this._debug("loadSubjectCategories", {
            count: this.state.subjectCategories.length,
        });
    }

    async _loadData() {
        const requestId = ++this._loadDataRequestId;
        this._debug("loadData:start", this._stateSnapshot());
        // Don't load data if no subject category is selected
        if (!this.state.selectedCategoryId) {
            this.state.tree = [];
            this.state.contentSections = [];
            this.state.activeSectionId = 0;
            this.state.contentVersion++;
            this._debug("loadData:skip-no-category", this._stateSnapshot());
            return;
        }
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "aps.resources",
                "get_course_explorer_data",
                [this.state.selectedCategoryId],
            );
            if (requestId !== this._loadDataRequestId) {
                this._debug("loadData:stale-result-ignored", { requestId });
                return;
            }
            this.state.tree = result.tree || [];
            // Wrap HTML content in Markup so t-out renders it as HTML
            this.state.contentSections = (result.contentSections || []).map((sec) => ({
                ...sec,
                html: sec.html ? markup(sec.html) : "",
            }));
            if (this._debugEnabled) {
                const ids = this.state.contentSections.map((s) => s.id);
                const duplicateIds = ids.filter((id, idx) => ids.indexOf(id) !== idx);
                if (duplicateIds.length) {
                    this._debug("loadData:duplicate-section-ids", {
                        duplicateIds,
                        total: ids.length,
                    });
                }
            }
            this.state.contentVersion++;
            this._mathRenderVersion++;
            this.state.activeSectionId = 0;
            this._debug("loadData:received", {
                requestId,
                treeCount: this.state.tree.length,
                sectionCount: this.state.contentSections.length,
                contentVersion: this.state.contentVersion,
                mathRenderVersion: this._mathRenderVersion,
            });
            // Fetch student progress data
            await this._loadProgressData(requestId);
        } catch (err) {
            console.error("CourseExplorer: failed to load data", err);
            this._debug("loadData:error", {
                requestId,
                message: err?.message,
                stack: err?.stack,
            });
            this.state.tree = [];
            this.state.contentSections = [];
        } finally {
            if (requestId === this._loadDataRequestId) {
                this.state.loading = false;
                this._debug("loadData:done", this._stateSnapshot());
            } else {
                this._debug("loadData:done-stale-skip", { requestId });
            }
        }
    }

    async _loadProgressData(requestId = this._loadDataRequestId) {
        try {
            // Current user's partner ID is available directly from the user service
            const partnerId = user.partnerId;
            if (!partnerId) return;
            const progressData = await this.orm.call(
                "aps.resources",
                "get_course_explorer_progress",
                [partnerId],
            );
            if (requestId !== this._loadDataRequestId) {
                this._debug("loadProgressData:stale-result-ignored", { requestId });
                return;
            }
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
            this._debug("loadProgressData:done", {
                sectionCount: this.state.contentSections.length,
            });
        } catch (err) {
            console.error("CourseExplorer: failed to load progress", err);
            this._debug("loadProgressData:error", {
                message: err?.message,
                stack: err?.stack,
            });
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
        this._debug("onCategoryChange", {
            selectedCategoryId: this.state.selectedCategoryId,
        });
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
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        this.state.activeSectionId = sectionId;
        this._saveStorage();
        this._scrollToTarget(target);
    }

    scrollToQuiz(ev, sectionId) {
        ev.preventDefault();
        const el = this.contentRef.el;
        if (!el) return;
        const target = el.querySelector(`#ce-quiz-${sectionId}`);
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        this._scrollToTarget(target);
    }

    _scrollToTarget(target) {
        let lastHeight = target.offsetHeight;
        let stableCount = 0;
        let disconnected = false;
        function doScroll() {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        const observer = new ResizeObserver(() => {
            const newHeight = target.offsetHeight;
            if (newHeight !== lastHeight) {
                lastHeight = newHeight;
                stableCount = 0;
                doScroll();
            } else {
                stableCount++;
                if (stableCount >= 5 && !disconnected) {
                    disconnected = true;
                    observer.disconnect();
                    cleanup();
                }
            }
        });
        observer.observe(target);

        // Also re-scroll when any lazy image inside the target loads
        const images = target.querySelectorAll("img[loading='lazy']");
        const onImageLoad = () => doScroll();
        images.forEach((img) => {
            if (!img.complete) {
                img.addEventListener("load", onImageLoad, { once: true });
            }
        });

        function cleanup() {
            images.forEach((img) => img.removeEventListener("load", onImageLoad));
        }
        setTimeout(() => {
            if (!disconnected) {
                disconnected = true;
                observer.disconnect();
                cleanup();
            }
        }, 10000);
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
        el.removeEventListener("scroll", this._boundOnScroll);
        el.addEventListener("scroll", this._boundOnScroll, { passive: true });
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
        el.removeEventListener("scroll", this._boundOnScrollDetect);
        el.addEventListener("scroll", this._boundOnScrollDetect, {
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
        // Account for scroll-margin-top (16px) on .ce_content_section:
        // scrollIntoView positions the section at scrollTop = offsetTop - 16,
        // so we need tolerance >= 16 to detect the correctly-scrolled section.
        const scrollTop = el.scrollTop;
        let bestId = null;

        for (const s of sections) {
            if (s.offsetTop <= scrollTop + 20) {
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
        el.removeEventListener("click", this._boundOnContentClick);
        el.addEventListener("click", this._boundOnContentClick);
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

    get visibleContentSections() {
        return this.state.contentSections.filter((section) => section.visible);
    }

    // ── Heading level classes ────────────────────────────────────────

    _setupTooltipsIfNeeded() {
        if (this._lastTooltipVersion === this.state.contentVersion) {
            return;
        }
        this._lastTooltipVersion = this.state.contentVersion;
        this._setupTooltips();
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