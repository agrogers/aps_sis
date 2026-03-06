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
            siblings: [],
            loading: false,
            // Children dropdown (on the final badge)
            childrenDropdownOpen: false,
            children: [],
            childrenLoading: false,
            // Whether the current resource has children
            hasChildren: false,
            // Which arrow indices have siblings available (object: {index: boolean})
            arrowHasSiblings: {},
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
     * Handle click on an arrow between breadcrumb pills.
     * Opens a dropdown showing sibling resources at that position.
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
        this.state.siblings = [];

        try {
            const results = await this.orm.searchRead(
                "aps.resources",
                [["parent_ids", "in", [parentId]]],
                ["id", "name", "sequence"],
                { order: "sequence asc, name asc" }
            );
            // Exclude the resource at this arrow position from siblings list
            const excludeId = breadcrumbs[arrowIndex].id;
            this.state.siblings = results.filter((r) => r.id !== excludeId);
        } catch (error) {
            console.error("BreadcrumbField: failed to load sibling resources", error);
            this.state.siblings = [];
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Handle click on a sibling item in the dropdown.
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
        this.state.children = [];

        try {
            const results = await this.orm.searchRead(
                "aps.resources",
                [["parent_ids", "in", [currentId]]],
                ["id", "name", "sequence"],
                { order: "sequence asc, name asc" }
            );
            // Exclude the current resource from the children list
            this.state.children = results.filter((r) => r.id !== currentId);
        } catch (error) {
            console.error("BreadcrumbField: failed to load child resources", error);
            this.state.children = [];
        } finally {
            this.state.childrenLoading = false;
        }
    }

    /**
     * Handle click on a child item in the dropdown.
     * @param {MouseEvent} ev
     */
    onChildClick(ev) {
        const id = parseInt(ev.currentTarget.dataset.resId, 10);
        if (id) {
            this.state.childrenDropdownOpen = false;
            this.openResource(id);
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
