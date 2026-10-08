import { onMounted } from "@odoo/owl";
import { user } from "@web/core/user";
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

const STORAGE_KEY = "aps_resource_print_options";
const WIZARD_MODEL = "aps.resource.print.wizard";
const PREFERENCE_FIELDS = [
    "include_basic",
    "include_notes",
    "include_question",
    "include_model_answer",
    "include_lesson_plan",
    "include_assigned_students",
    "title_mode",
    "include_images",
    "page_breaks",
];

class ResourcePrintWizardController extends FormController {
    setup() {
        super.setup();
        this.user = user;
        onMounted(async () => this._restoreOptions());
    }

    _storageKey() {
        return `${STORAGE_KEY}_${this.user.userId}`;
    }

    async _restoreOptions() {
        if (this.model.root.resModel !== WIZARD_MODEL) {
            return;
        }
        try {
            const saved = JSON.parse(window.localStorage.getItem(this._storageKey()) || "{}");
            const values = Object.fromEntries(
                PREFERENCE_FIELDS
                    .filter((fieldName) => Object.hasOwn(saved, fieldName))
                    .map((fieldName) => [fieldName, saved[fieldName]])
            );
            if (Object.keys(values).length) {
                await this.model.root.update(values);
            }
        } catch {
            // Ignore unavailable or malformed browser-local preferences.
        }
    }

    async beforeExecuteActionButton(clickParams) {
        if (
            this.model.root.resModel === WIZARD_MODEL
            && clickParams.name === "action_print_report"
        ) {
            const values = Object.fromEntries(
                PREFERENCE_FIELDS.map((fieldName) => [fieldName, this.model.root.data[fieldName]])
            );
            try {
                window.localStorage.setItem(this._storageKey(), JSON.stringify(values));
            } catch {
                // Printing remains available if browser storage is disabled.
            }
        }
        return super.beforeExecuteActionButton(clickParams);
    }
}

registry.category("views").add("aps_resource_print_wizard_form", {
    ...formView,
    Controller: ResourcePrintWizardController,
});