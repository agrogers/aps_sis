import { registry } from "@web/core/registry";
import { Component, useState, useRef, onMounted, onWillUnmount, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

/**
 * BreadcrumbField — renders the ``display_name_breadcrumb`` JSON field as a
 * row of clickable pills separated by arrows.
 *
 * Each arrow between pills is clickable and opens a dropdown showing sibling
 * resources (all children of the parent at that position).  This allows quick
 * navigation to any sibling at any level of the hierarchy.
 *
 * Dropdowns load the immediate children and prefetch one level ahead. Further
 * levels are prefetched when their parent is expanded. Each item shows its
 * resource-type icon.
 *
 * Usage in a view:
 *   <field name="display_name_breadcrumb" widget="breadcrumb_pills"
 *          options="{'size': '1.4em'}"/>
 *
 * Options:
 *   size  — any valid CSS font-size value (default: "1em").  Controls the
 *           overall text size of the breadcrumb row so it can be used in
 *           both ribbon headers and compact list cells.
 */
export class BreadcrumbField extends Component {
    static template = "aps_sis.BreadcrumbField";
    static props = {
        ...standardFieldProps,
        size: { type: String, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this._dropdownRequestId = 0;
        this._dropdownPendingLoads = new Map();

        this.state = useState({
            dropdownOpenIndex: null,  // Which arrow index has the dropdown open (null = none)
            loading: false,
            // Children dropdown (on the final badge)
            childrenDropdownOpen: false,
            childrenLoading: false,
            // Whether the current resource has children
            hasChildren: false,
            // Which arrow indices have siblings available (object: {index: boolean})
            arrowHasSiblings: {},
            // Loaded children keyed by parent ID for the open dropdown.
            siblingsTree: null,
            childrenTree: null,
            // Plain objects used for OWL reactivity, keyed by resource ID.
            dropdownExpandedIds: {},
            dropdownLoadingIds: {},
        });

        this.rootRef = useRef("widgetRoot");

        // Check for children and sibling availability on mount
        onWillStart(async () => {
            await Promise.all([
                this._checkHasChildren(),
                this._checkArrowSiblings(),
            ]);
        });

        // Re-check when props change (different record)
        onWillUpdateProps(async (nextProps) => {
            if (nextProps.record !== this.props.record) {
                this._closeDropdowns();
                await Promise.all([
                    this._checkHasChildren(nextProps),
                    this._checkArrowSiblings(nextProps),
                ]);
            }
        });

        // Close dropdown when the user clicks anywhere outside the widget.
        this._onWindowClick = this._onWindowClick.bind(this);
        onMounted(() => {
            window.addEventListener("click", this._onWindowClick);
        });
        onWillUnmount(() => {
            window.removeEventListener("click", this._onWindowClick);
        });
    }

    /** Parsed breadcrumb array: [{id, label}, ...] */
    get breadcrumbs() {
        const value = this.props.record.data[this.props.name];
        if (!value) return [];
        if (typeof value === "string") {
            try {
                return JSON.parse(value);
            } catch {
                return [];
            }
        }
        return Array.isArray(value) ? value : [];
    }

    /**
     * Check if the current resource has any children.
     * @param {Object} props - Optional props to use (for onWillUpdateProps)
     */
    async _checkHasChildren(props = null) {
        const propsToUse = props || this.props;
        const value = propsToUse.record.data[propsToUse.name];
        let breadcrumbs = [];
        
        if (value) {
            if (typeof value === "string") {
                try {
                    breadcrumbs = JSON.parse(value);
                } catch {
                    breadcrumbs = [];
                }
            } else if (Array.isArray(value)) {
                breadcrumbs = value;
            }
        }
        
        if (breadcrumbs.length === 0) {
            this.state.hasChildren = false;
            return;
        }
        
        const currentId = breadcrumbs[breadcrumbs.length - 1].id;
        if (!currentId) {
            this.state.hasChildren = false;
            return;
        }

        try {
            const count = await this.orm.searchCount(
                "aps.resources",
                [["parent_ids", "in", [currentId]]]
            );
            this.state.hasChildren = count > 0;
        } catch (error) {
            console.error("BreadcrumbField: failed to check for children", error);
            this.state.hasChildren = false;
        }
    }

    /**
     * Check which arrows have siblings available.
     * An arrow at index i shows siblings (children of breadcrumbs[i-1]).
     * We show the outline icon if there's more than 1 child (i.e., siblings exist).
     * @param {Object} props - Optional props to use (for onWillUpdateProps)
     */
    async _checkArrowSiblings(props = null) {
        const propsToUse = props || this.props;
        const value = propsToUse.record.data[propsToUse.name];
        let breadcrumbs = [];
        
        if (value) {
            if (typeof value === "string") {
                try {
                    breadcrumbs = JSON.parse(value);
                } catch {
                    breadcrumbs = [];
                }
            } else if (Array.isArray(value)) {
                breadcrumbs = value;
            }
        }
        
        // For each arrow position (indices 1 to length-1), check if parent has >1 child
        const arrowHasSiblings = {};
        const checkPromises = [];
        
        for (let i = 1; i < breadcrumbs.length; i++) {
            const parentIndex = i - 1;
            const parentId = breadcrumbs[parentIndex].id;
            const currentAtArrow = breadcrumbs[i].id;
            
            if (parentId) {
                checkPromises.push(
                    this.orm.searchCount(
                        "aps.resources",
                        [["parent_ids", "in", [parentId]]]
                    ).then((count) => {
                        // Has siblings if count > 1 (more than just the current resource)
                        arrowHasSiblings[i] = count > 1;
                    }).catch(() => {
                        arrowHasSiblings[i] = false;
                    })
                );
            } else {
                arrowHasSiblings[i] = false;
            }
        }
        
        await Promise.all(checkPromises);
        this.state.arrowHasSiblings = arrowHasSiblings;
    }

    /**
     * Open the aps.resources form for the given record id.
     * @param {number} id
     */
    openResource(id) {
        if (!id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resources",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /**
     * Handle click on an ancestor breadcrumb pill.
     * @param {MouseEvent} ev
     */
    onAncestorClick(ev) {
        const id = parseInt(ev.currentTarget.dataset.resId, 10);
        if (id) {
            this.openResource(id);
        }
    }

    /** Fetch children for one or more resource IDs in one ORM request. */
    async _fetchChildren(parentIds) {
        const ids = Array.isArray(parentIds) ? parentIds : [parentIds];
        if (!ids.length) return [];
        return this.orm.searchRead(
            "aps.resources",
            [["parent_ids", "in", ids]],
            ["id", "name", "type_id", "child_count", "parent_ids"],
            { order: "sequence asc, name asc" }
        );
    }

    _loadDropdownChildren(parentIds, treeName, requestId) {
        const tree = this.state[treeName];
        if (!tree || requestId !== this._dropdownRequestId) {
            return Promise.resolve();
        }

        const missingParentIds = [];
        const pendingPromises = new Set();
        for (const parentId of new Set(parentIds)) {
            if (Object.prototype.hasOwnProperty.call(tree, parentId)) continue;
            const pending = this._dropdownPendingLoads.get(parentId);
            if (pending) {
                pendingPromises.add(pending);
            } else {
                missingParentIds.push(parentId);
            }
        }

        const loads = [...pendingPromises];
        if (missingParentIds.length) {
            loads.push(
                this._fetchAndStoreDropdownChildren(
                    missingParentIds, treeName, requestId
                )
            );
        }
        return Promise.all(loads);
    }

    _fetchAndStoreDropdownChildren(parentIds, treeName, requestId) {
        const loadingIds = { ...this.state.dropdownLoadingIds };
        for (const parentId of parentIds) {
            loadingIds[parentId] = true;
        }
        this.state.dropdownLoadingIds = loadingIds;

        const parentIdSet = new Set(parentIds);
        const fetchPromise = this._fetchChildren(parentIds);
        let loadPromise;
        loadPromise = fetchPromise.then((records) => {
            if (requestId !== this._dropdownRequestId) return;
            const currentTree = this.state[treeName];
            if (!currentTree) return;

            const nextTree = { ...currentTree };
            for (const parentId of parentIds) {
                nextTree[parentId] = [];
            }

            const seenIds = new Set(Object.keys(nextTree).map(Number));
            for (const children of Object.values(nextTree)) {
                for (const child of children) {
                    seenIds.add(child.id);
                }
            }

            for (const record of records) {
                if (seenIds.has(record.id)) continue;
                const recordParentIds = Array.isArray(record.parent_ids)
                    ? record.parent_ids
                    : [];
                const assignedParentId = recordParentIds.find(
                    (parentId) => parentIdSet.has(parentId)
                );
                if (assignedParentId === undefined) continue;

                nextTree[assignedParentId] = [
                    ...(nextTree[assignedParentId] || []),
                    record,
                ];
                seenIds.add(record.id);
            }

            this.state[treeName] = nextTree;
        }).finally(() => {
            if (requestId === this._dropdownRequestId) {
                const currentLoadingIds = { ...this.state.dropdownLoadingIds };
                for (const parentId of parentIds) {
                    delete currentLoadingIds[parentId];
                }
                this.state.dropdownLoadingIds = currentLoadingIds;
            }
            for (const parentId of parentIds) {
                if (this._dropdownPendingLoads.get(parentId) === loadPromise) {
                    this._dropdownPendingLoads.delete(parentId);
                }
            }
        });

        for (const parentId of parentIds) {
            this._dropdownPendingLoads.set(parentId, loadPromise);
        }
        return loadPromise;
    }

    _prefetchDropdownChildren(parentIds, treeName, requestId) {
        const tree = this.state[treeName];
        if (!tree || requestId !== this._dropdownRequestId) return;

        const ids = [...new Set(parentIds)].filter(
            (parentId) => !Object.prototype.hasOwnProperty.call(tree, parentId)
        );
        if (!ids.length) return;

        this._loadDropdownChildren(ids, treeName, requestId).catch((error) => {
            console.error("BreadcrumbField: failed to prefetch child resources", error);
        });
    }

    /**
     * Build a flat, depth-annotated list of loaded dropdown items. Items whose
     * sub-tree is expanded are followed by its loaded children.
     *
     * @param {Object} tree          - { [parentId]: [records] }
     * @param {number} parentId      - root whose children to render first
     * @param {Object} expandedIds   - { [id]: true } for expanded items
     * @param {number|null} excludeId - optional ID to skip at root level
     * @param {number} depth         - current nesting depth (0 = top level)
     * @returns {Array}
     */
    _buildDropdownItems(
        tree, parentId, expandedIds, excludeId = null, depth = 0, ancestorIds = null
    ) {
        const children = tree[parentId] || [];
        const result = [];
        const ancestors = ancestorIds || new Set([parentId]);

        for (const item of children) {
            if (item.id === excludeId || ancestors.has(item.id)) continue;

            const itemChildrenLoaded = Object.prototype.hasOwnProperty.call(tree, item.id);
            const itemChildren = tree[item.id] || [];
            const hasChildren = itemChildrenLoaded
                ? itemChildren.length > 0
                : item.child_count > 0;
            const isExpanded = !!expandedIds[item.id];

            result.push({
                id: item.id,
                name: item.name,
                type_id: item.type_id,
                // type_id from RPC is [id, display_name] when set, else false.
                icon_url: item.type_id
                    ? `/web/image/aps.resources/${item.id}/type_icon`
                    : null,
                hasChildren,
                isExpanded,
                isLoading: !!this.state.dropdownLoadingIds[item.id],
                depth,
            });

            if (isExpanded && hasChildren) {
                const childAncestors = new Set(ancestors);
                childAncestors.add(item.id);
                result.push(
                    ...this._buildDropdownItems(
                        tree, item.id, expandedIds, null, depth + 1, childAncestors
                    )
                );
            }
        }

        return result;
    }

    /**
     * Flat, depth-annotated list of visible items for the sibling dropdown.
     * Computed from the children loaded so far.
     */
    get siblingDropdownItems() {
        const { dropdownOpenIndex, siblingsTree, dropdownExpandedIds } = this.state;
        if (dropdownOpenIndex === null || !siblingsTree) return [];

        const breadcrumbs = this.breadcrumbs;
        const parentId = breadcrumbs[dropdownOpenIndex - 1]?.id;
        const excludeId = breadcrumbs[dropdownOpenIndex]?.id;

        if (!parentId) return [];
        return this._buildDropdownItems(
            siblingsTree, parentId, dropdownExpandedIds, excludeId
        );
    }

    /**
     * Flat, depth-annotated list of visible items for the children dropdown.
     * Computed from the children loaded so far.
     */
    get childrenDropdownItems() {
        const { childrenTree, dropdownExpandedIds } = this.state;
        if (!childrenTree) return [];

        const breadcrumbs = this.breadcrumbs;
        const currentId = breadcrumbs[breadcrumbs.length - 1]?.id;

        if (!currentId) return [];
        return this._buildDropdownItems(childrenTree, currentId, dropdownExpandedIds);
    }

    /**
     * Handle click on an arrow between breadcrumb pills.
     * Opens a dropdown showing sibling resources at that position. The
     * immediate level is loaded first, then its children are prefetched.
     * @param {MouseEvent} ev
     */
    async onArrowClick(ev) {
        const arrowIndex = parseInt(ev.currentTarget.dataset.arrowIndex, 10);

        // Don't open dropdown if no siblings exist at this position
        if (!this.state.arrowHasSiblings[arrowIndex]) {
            return;
        }

        // If clicking the same arrow that's already open, close it
        if (this.state.dropdownOpenIndex === arrowIndex) {
            this._closeDropdowns();
            return;
        }

        // The parent is the breadcrumb at arrowIndex - 1
        const breadcrumbs = this.breadcrumbs;
        const parentIndex = arrowIndex - 1;

        if (parentIndex < 0 || parentIndex >= breadcrumbs.length) {
            return;
        }

        const parentId = breadcrumbs[parentIndex].id;
        if (!parentId) {
            return;
        }

        const requestId = ++this._dropdownRequestId;
        this._dropdownPendingLoads.clear();
        this.state.childrenDropdownOpen = false;
        this.state.childrenLoading = false;
        this.state.dropdownOpenIndex = arrowIndex;
        this.state.loading = true;
        this.state.siblingsTree = {};
        this.state.childrenTree = null;
        this.state.dropdownExpandedIds = {};
        this.state.dropdownLoadingIds = {};

        try {
            await this._loadDropdownChildren([parentId], "siblingsTree", requestId);
            if (requestId !== this._dropdownRequestId) return;
            const children = this.state.siblingsTree[parentId] || [];
            this._prefetchDropdownChildren(
                children.filter((child) => child.child_count > 0)
                    .map((child) => child.id),
                "siblingsTree",
                requestId
            );
        } catch (error) {
            console.error("BreadcrumbField: failed to load sibling resources", error);
            if (requestId === this._dropdownRequestId) {
                this.state.siblingsTree = { [parentId]: [] };
            }
        } finally {
            if (requestId === this._dropdownRequestId) {
                this.state.loading = false;
            }
        }
    }

    /**
     * Handle click on a sibling item in the dropdown — navigate to it.
     * @param {MouseEvent} ev
     */
    onSiblingClick(ev) {
        const id = parseInt(ev.currentTarget.dataset.resId, 10);
        if (id) {
            this._closeDropdowns();
            this.openResource(id);
        }
    }

    /**
     * Handle click on the current (final) breadcrumb pill.
     * Opens a dropdown showing child resources. The immediate level is loaded
     * first, then its children are prefetched.
     * @param {MouseEvent} ev
     */
    async onCurrentClick(ev) {
        // Toggle children dropdown
        if (this.state.childrenDropdownOpen) {
            this._closeDropdowns();
            return;
        }

        const breadcrumbs = this.breadcrumbs;
        if (breadcrumbs.length === 0) return;

        const currentId = breadcrumbs[breadcrumbs.length - 1].id;
        if (!currentId) return;

        const requestId = ++this._dropdownRequestId;
        this._dropdownPendingLoads.clear();
        this.state.dropdownOpenIndex = null;
        this.state.loading = false;
        this.state.siblingsTree = null;
        this.state.childrenDropdownOpen = true;
        this.state.childrenLoading = true;
        this.state.childrenTree = {};
        this.state.dropdownExpandedIds = {};
        this.state.dropdownLoadingIds = {};

        try {
            await this._loadDropdownChildren([currentId], "childrenTree", requestId);
            if (requestId !== this._dropdownRequestId) return;
            const children = this.state.childrenTree[currentId] || [];
            this._prefetchDropdownChildren(
                children.filter((child) => child.child_count > 0)
                    .map((child) => child.id),
                "childrenTree",
                requestId
            );
        } catch (error) {
            console.error("BreadcrumbField: failed to load child resources", error);
            if (requestId === this._dropdownRequestId) {
                this.state.childrenTree = { [currentId]: [] };
            }
        } finally {
            if (requestId === this._dropdownRequestId) {
                this.state.childrenLoading = false;
            }
        }
    }

    /**
     * Handle click on a child item in the dropdown — navigate to it.
     * @param {MouseEvent} ev
     */
    onChildClick(ev) {
        const id = parseInt(ev.currentTarget.dataset.resId, 10);
        if (id) {
            this._closeDropdowns();
            this.openResource(id);
        }
    }

    /**
     * Toggle the in-dropdown expansion of an item that has children.
     * Uses prefetched children when available and starts prefetching one level
     * deeper after the branch opens.
     * Uses object spread to replace the state property so OWL reactivity
     * reliably detects the change.
     * @param {MouseEvent} ev
     */
    async onExpandDropdownItem(ev) {
        const itemId = parseInt(ev.currentTarget.dataset.itemId, 10);
        const current = this.state.dropdownExpandedIds;
        if (current[itemId]) {
            const next = { ...current };
            delete next[itemId];
            this.state.dropdownExpandedIds = next;
            return;
        }

        const treeName = this.state.childrenDropdownOpen ? "childrenTree" : "siblingsTree";
        const tree = this.state[treeName];
        if (!tree) return;

        this.state.dropdownExpandedIds = { ...current, [itemId]: true };
        const requestId = this._dropdownRequestId;
        try {
            await this._loadDropdownChildren([itemId], treeName, requestId);
            if (requestId !== this._dropdownRequestId) return;
            const children = this.state[treeName][itemId] || [];
            this._prefetchDropdownChildren(
                children.filter((child) => child.child_count > 0)
                    .map((child) => child.id),
                treeName,
                requestId
            );
        } catch (error) {
            console.error(`BreadcrumbField: failed to load children for resource ${itemId}`, error);
            if (requestId === this._dropdownRequestId) {
                const expandedIds = { ...this.state.dropdownExpandedIds };
                delete expandedIds[itemId];
                this.state.dropdownExpandedIds = expandedIds;
            }
        } finally {
            if (requestId === this._dropdownRequestId) {
                const loadingIds = { ...this.state.dropdownLoadingIds };
                delete loadingIds[itemId];
                this.state.dropdownLoadingIds = loadingIds;
            }
        }
    }

    _closeDropdowns() {
        this._dropdownRequestId++;
        this.state.dropdownOpenIndex = null;
        this.state.loading = false;
        this.state.childrenDropdownOpen = false;
        this.state.childrenLoading = false;
        this.state.siblingsTree = null;
        this.state.childrenTree = null;
        this.state.dropdownExpandedIds = {};
        this.state.dropdownLoadingIds = {};
        this._dropdownPendingLoads.clear();
    }

    /** Close the dropdown when a click occurs outside the widget. */
    _onWindowClick(ev) {
        if (this.state.dropdownOpenIndex === null && !this.state.childrenDropdownOpen) return;
        const el = this.rootRef.el;
        if (el && !el.contains(ev.target)) {
            this._closeDropdowns();
        }
    }
}

export const breadcrumbField = {
    component: BreadcrumbField,
    supportedTypes: ["json"],
    supportedOptions: [
        {
            label: "Size",
            name: "size",
            type: "string",
            default: "1em",
            help: "CSS font-size value that controls the overall size of the breadcrumb pills.",
        },
    ],
    extractProps({ options }) {
        return {
            size: options.size || "1em",
        };
    },
};

registry.category("fields").add("breadcrumb_pills", breadcrumbField);
