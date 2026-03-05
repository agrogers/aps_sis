import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

/**
 * BreadcrumbField — renders the ``display_name_breadcrumb`` JSON field as a
 * row of clickable pills separated by 🢒 arrows.
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
