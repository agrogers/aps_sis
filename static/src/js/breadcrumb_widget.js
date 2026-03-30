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
 * Dropdowns support multi-level drill-down: if any item in the dropdown itself
 * has children, a ▶ arrow appears next to it.  Clicking that arrow expands the
 * item's children inline (all levels are pre-fetched in a single BFS pass so
 * subsequent expansions are instant).  Each item shows its resource-type icon.
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
            // Pre-fetched descendant trees for the open dropdown.
            // Each tree is a plain object: { [parentId]: [childRecord, ...], ... }
            // where childRecord is { id, name, sequence, type_id, parent_ids }.
            siblingsTree: null,
            childrenTree: null,
            // Tracks which items are expanded inside the open dropdown.
            // Plain object used for OWL reactivity: { [id]: true }
            dropdownExpandedIds: {},
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

    /**
     * Fetch all descendants of a single root parent as a tree object.
     *
     * Uses a breadth-first loop so that ALL levels are retrieved in the
     * minimum number of ORM calls (one per depth level).  The result is a
     * plain object keyed by parent-ID whose values are arrays of child
     * records (each containing id, name, sequence, type_id, parent_ids).
     *
     * @param {number} rootParentId
     * @returns {Promise<Object>}  { [parentId]: [childRecord, ...], ... }
     */
    async _fetchDescendantTree(rootParentId) {
        const tree = { [rootParentId]: [] };
        let frontier = [rootParentId];
        const visited = new Set([rootParentId]);

        while (frontier.length > 0) {
            let records;
            try {
                records = await this.orm.searchRead(
                    "aps.resources",
                    [["parent_ids", "in", frontier]],
                    ["id", "name", "sequence", "type_id", "parent_ids"],
                    { order: "sequence asc, name asc" }
                );
            } catch (error) {
                console.error("BreadcrumbField: failed to fetch descendants", error);
                break;
            }

            const frontierSet = new Set(frontier);
            const nextFrontier = [];

            for (const rec of records) {
                if (visited.has(rec.id)) continue;
                visited.add(rec.id);

                // Assign the record to the first of its parent_ids that is in
                // the current frontier so we preserve tree structure correctly.
                const parentIds = Array.isArray(rec.parent_ids) ? rec.parent_ids : [];
                let assignedParent = null;
                for (const pid of parentIds) {
                    if (frontierSet.has(pid)) {
                        assignedParent = pid;
                        break;
                    }
                }

                if (assignedParent !== null) {
                    if (!tree[assignedParent]) tree[assignedParent] = [];
                    tree[assignedParent].push(rec);
                    tree[rec.id] = [];   // initialise children bucket
                    nextFrontier.push(rec.id);
                }
            }

            frontier = nextFrontier;
        }

        return tree;
    }

    /**
     * Build a flat, depth-annotated list of visible dropdown items from a
     * pre-fetched tree.  Items whose sub-tree is expanded are followed
     * immediately by their children (recursively).
     *
     * @param {Object} tree          - { [parentId]: [records] }
     * @param {number} parentId      - root whose children to render first
     * @param {Object} expandedIds   - { [id]: true } for expanded items
     * @param {number|null} excludeId - optional ID to skip at root level
     * @param {number} depth         - current nesting depth (0 = top level)
     * @returns {Array}
     */
    _buildDropdownItems(tree, parentId, expandedIds, excludeId = null, depth = 0) {
        const children = tree[parentId] || [];
        const result = [];

        for (const item of children) {
            if (item.id === excludeId) continue;

            const itemChildren = tree[item.id] || [];
            const hasChildren = itemChildren.length > 0;
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
                depth,
            });

            if (isExpanded && hasChildren) {
                result.push(
                    ...this._buildDropdownItems(
                        tree, item.id, expandedIds, null, depth + 1
                    )
                );
            }
        }

        return result;
    }

    /**
     * Flat, depth-annotated list of visible items for the sibling dropdown.
     * Computed from the pre-fetched tree so re-renders are instant once loaded.
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
     * Computed from the pre-fetched tree so re-renders are instant once loaded.
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
     * Opens a dropdown showing sibling resources at that position.
     * All descendants of the siblings are pre-fetched in a BFS pass so that
     * in-dropdown expansions are instant (no per-click round-trips).
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
            this.state.dropdownOpenIndex = null;
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

        // Close children dropdown when opening sibling dropdown
        this.state.childrenDropdownOpen = false;
        this.state.dropdownOpenIndex = arrowIndex;
        this.state.loading = true;
        this.state.siblingsTree = null;
        this.state.dropdownExpandedIds = {};

        try {
            this.state.siblingsTree = await this._fetchDescendantTree(parentId);
        } catch (error) {
            console.error("BreadcrumbField: failed to load sibling resources", error);
            this.state.siblingsTree = {};
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Handle click on a sibling item in the dropdown — navigate to it.
     * @param {MouseEvent} ev
     */
    onSiblingClick(ev) {
        const id = parseInt(ev.currentTarget.dataset.resId, 10);
        if (id) {
            this.state.dropdownOpenIndex = null;
            this.openResource(id);
        }
    }

    /**
     * Handle click on the current (final) breadcrumb pill.
     * Opens a dropdown showing child resources.
     * All descendants are pre-fetched in a BFS pass so that in-dropdown
     * expansions are instant (no per-click round-trips).
     * @param {MouseEvent} ev
     */
    async onCurrentClick(ev) {
        // Close sibling dropdowns first
        this.state.dropdownOpenIndex = null;

        // Toggle children dropdown
        if (this.state.childrenDropdownOpen) {
            this.state.childrenDropdownOpen = false;
            return;
        }

        const breadcrumbs = this.breadcrumbs;
        if (breadcrumbs.length === 0) return;

        const currentId = breadcrumbs[breadcrumbs.length - 1].id;
        if (!currentId) return;

        this.state.childrenDropdownOpen = true;
        this.state.childrenLoading = true;
        this.state.childrenTree = null;
        this.state.dropdownExpandedIds = {};

        try {
            this.state.childrenTree = await this._fetchDescendantTree(currentId);
        } catch (error) {
            console.error("BreadcrumbField: failed to load child resources", error);
            this.state.childrenTree = {};
        } finally {
            this.state.childrenLoading = false;
        }
    }

    /**
     * Handle click on a child item in the dropdown — navigate to it.
     * @param {MouseEvent} ev
     */
    onChildClick(ev) {
        const id = parseInt(ev.currentTarget.dataset.resId, 10);
        if (id) {
            this.state.childrenDropdownOpen = false;
            this.openResource(id);
        }
    }

    /**
     * Toggle the in-dropdown expansion of an item that has children.
     * No network round-trip — the full tree was pre-fetched on dropdown open.
     * Uses object spread to replace the state property so OWL reactivity
     * reliably detects the change.
     * @param {MouseEvent} ev
     */
    onExpandDropdownItem(ev) {
        const itemId = parseInt(ev.currentTarget.dataset.itemId, 10);
        const current = this.state.dropdownExpandedIds;
        if (current[itemId]) {
            // Remove by spreading and omitting this key
            const next = {};
            for (const key of Object.keys(current)) {
                if (parseInt(key, 10) !== itemId) next[key] = current[key];
            }
            this.state.dropdownExpandedIds = next;
        } else {
            this.state.dropdownExpandedIds = { ...current, [itemId]: true };
        }
    }

    /** Close the dropdown when a click occurs outside the widget. */
    _onWindowClick(ev) {
        if (this.state.dropdownOpenIndex === null && !this.state.childrenDropdownOpen) return;
        const el = this.rootRef.el;
        if (el && !el.contains(ev.target)) {
            this.state.dropdownOpenIndex = null;
            this.state.childrenDropdownOpen = false;
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
