import { registry } from "@web/core/registry";
import { Component, useState, useRef } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService, useExternalListener } from "@web/core/utils/hooks";

/**
 * BreadcrumbField — renders the ``display_name_breadcrumb`` JSON field as a
 * row of clickable pills separated by 🢒 arrows.
 *
 * The final (current) pill shows a caret indicator when sibling resources
 * exist under the same parent.  Clicking it opens a compact dropdown listing
 * those siblings so the user can jump to one directly.
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
            dropdownOpen: false,
            siblings: [],
            loading: false,
        });

        this.dropdownRef = useRef("siblingDropdown");

        // Close dropdown when the user clicks anywhere outside the widget.
        useExternalListener(window, "click", this._onWindowClick.bind(this));
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

    /** ID of the current (last) breadcrumb entry, or false. */
    get currentId() {
        const bc = this.breadcrumbs;
        return bc.length > 0 ? bc[bc.length - 1].id : false;
    }

    /**
     * ID of the immediate parent (second-to-last breadcrumb entry), or false.
     * When this is present the last pill can have siblings.
     */
    get parentId() {
        const bc = this.breadcrumbs;
        return bc.length > 1 ? bc[bc.length - 2].id : false;
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
     * Toggle the sibling dropdown.  Fetches siblings from the server the
     * first time (or whenever the dropdown is re-opened after being closed).
     * @param {MouseEvent} ev
     */
    async toggleSiblingDropdown(ev) {
        ev.stopPropagation();
        ev.preventDefault();

        if (this.state.dropdownOpen) {
            this.state.dropdownOpen = false;
            return;
        }

        const parentId = this.parentId;
        if (!parentId) return;

        this.state.dropdownOpen = true;
        this.state.loading = true;
        this.state.siblings = [];

        try {
            const results = await this.orm.searchRead(
                "aps.resources",
                [["parent_ids", "in", [parentId]]],
                ["id", "name", "sequence"],
                { order: "sequence asc, name asc" }
            );
            // Exclude the current resource from its own sibling list.
            const currentId = this.currentId;
            this.state.siblings = results.filter((r) => r.id !== currentId);
        } catch (error) {
            console.error("BreadcrumbField: failed to load sibling resources", error);
            this.state.siblings = [];
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Navigate to a sibling resource and close the dropdown.
     * @param {number} id
     */
    openSibling(id) {
        this.state.dropdownOpen = false;
        this.openResource(id);
    }

    /** Close the dropdown when a click occurs outside the widget. */
    _onWindowClick(ev) {
        if (!this.state.dropdownOpen) return;
        const el = this.dropdownRef.el;
        if (el && !el.contains(ev.target)) {
            this.state.dropdownOpen = false;
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
