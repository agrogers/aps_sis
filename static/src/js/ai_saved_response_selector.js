import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * AiSavedResponseSelector
 *
 * A simple <select> widget bound to the `ai_selected_response_key` Char field.
 * It reads the companion `ai_saved_responses` Json field from the same record
 * and renders one <option> per saved response.
 *
 * Selecting a response immediately calls action_ai_load_response server-side
 * and reloads the form record so the written fields appear without a manual
 * "Load" button.
 */
class AiSavedResponseSelector extends Component {
    static template = "aps_sis.AiSavedResponseSelector";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

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

    /**
     * Handle <select> change:
     * 1. Write the key to the Char field and save the record so the server
     *    can read the correct key.
     * 2. Call action_ai_load_response server-side to populate the AI fields.
     * 3. Reload the form record so the written values appear immediately.
     */
    async onChange(ev) {
        const key = ev.target.value;
        await this.props.record.update({ [this.props.name]: key || false });
        if (!key) return;

        // Persist the key before calling the server method.
        await this.props.record.save();

        const result = await this.orm.call(
            this.props.record.resModel,
            "action_ai_load_response",
            [[this.props.record.resId]],
        );

        // Reload the record so server-written fields (ai_feedback, ai_score,
        // etc.) are reflected in the form without a manual page refresh.
        await this.props.record.model.root.load();

        // Show the success notification returned by the server action.
        if (result && result.params) {
            this.notification.add(result.params.message, {
                title: result.params.title,
                type: result.params.type || "success",
            });
        }
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
