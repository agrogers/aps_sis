import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { markup } from "@odoo/owl";

export class ResourceNotesDialog extends Component {
    static template = "aps_sis.ResourceNotesDialog";
    static components = { Dialog };
    static props = {
        resourceId: { type: Number },
        resourceName: { type: String },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            notes: "",
        });

        onWillStart(async () => {
            const [data] = await this.orm.read(
                "aps.resources",
                [this.props.resourceId],
                ["notes"],
            );
            this.state.notes = data?.notes || "";
            this.state.loading = false;
        });
    }

    get notesMarkup() {
        return this.state.notes ? markup(this.state.notes) : "";
    }
}
