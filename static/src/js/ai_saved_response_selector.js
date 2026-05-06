import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * AiSavedResponseSelector
 *
 * A simple <select> widget bound to the `ai_selected_response_key` Char field.
 * It reads the companion `ai_saved_responses` Json field from the same record
 * and renders one <option> per saved response.
 */
class AiSavedResponseSelector extends Component {
    static template = "aps_sis.AiSavedResponseSelector";
    static props = {
        ...standardFieldProps,
    };

    /** Parsed saved-responses dict from the sibling field. */
    get savedResponses() {
        const raw = this.props.record.data.ai_saved_responses;
        if (!raw || typeof raw !== "object") return {};
        return raw;
    }

    /** Sorted list of { key, name, saved_date, ai_model_name } for rendering. */
    get responseList() {
        const responses = this.savedResponses;
        return Object.entries(responses)
            .map(([key, entry]) => ({
                key,
                name: entry.name || key,
                // Display only YYYY-MM-DD HH:MM (drop seconds if present)
                saved_date: (entry.saved_date || "").substring(0, 16),
                ai_model_name: entry.ai_model_name || "",
            }))
            .sort((a, b) => b.saved_date.localeCompare(a.saved_date));
    }

    /** Currently selected key (value of the Char field). */
    get selectedKey() {
        return this.props.value || "";
    }

    /** Handle <select> change – write the chosen key back to the Char field. */
    onChange(ev) {
        const key = ev.target.value;
        this.props.update(key || false);
    }
}

export const aiSavedResponseSelector = {
    component: AiSavedResponseSelector,
    supportedTypes: ["char"],
    extractProps(params) {
        return {};
    },
};

registry.category("fields").add("ai_saved_response_selector", aiSavedResponseSelector);
