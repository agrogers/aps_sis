import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class UniformInfringementDialog extends Component {
    static template = "aps_sis.UniformInfringementDialog";
    static components = { Dialog };
    static props = {
        studentId: { type: Number },
        studentName: { type: String },
        date: { type: String },
        existingTypes: { type: Array, optional: true },
        existingRecords: { type: Array, optional: true },
        onSaved: { type: Function, optional: true },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        const existingRecords = this.props.existingRecords || [];
        const existingTypes = existingRecords.length
            ? existingRecords.map((record) => record.type)
            : (this.props.existingTypes || []);
        this.existingRecords = existingRecords;
        this.existingTypes = existingTypes;
        this.types = [
            ["top", "Top"],
            ["bottom", "Bottom"],
            ["shoes", "Shoes"],
            ["hair", "Hair"],
            ["skin", "Skin"],
            ["other", "Other"],
        ];
        this.state = useState({
            selected: new Set(existingTypes),
            comments: Object.fromEntries(existingRecords.map((record) => [record.type, record.comment || ""])),
            saving: false,
        });
    }

    isSelected(type) {
        return this.state.selected.has(type);
    }

    toggleType(type) {
        if (this.state.selected.has(type)) {
            this.state.selected.delete(type);
        } else {
            this.state.selected.add(type);
        }
    }

    updateComment(type, event) {
        this.state.comments[type] = event.target.value;
    }

    async save() {
        if (this.state.saving || (!this.state.selected.size && !this.existingRecords.length)) {
            return;
        }
        this.state.saving = true;
        try {
            const newValues = [...this.state.selected]
                .filter((type) => !this.existingTypes.includes(type))
                .map((type) => ({
                    date: this.props.date,
                    partner_id: this.props.studentId,
                    infringement_type: type,
                    comment: this.state.comments[type] || false,
                }));
            if (newValues.length) {
                await this.orm.create("apex.uniform.infringement", newValues);
            }
            for (const record of this.existingRecords) {
                if (this.state.selected.has(record.type)) {
                    await this.orm.write(
                        "apex.uniform.infringement",
                        [record.id],
                        { comment: this.state.comments[record.type] || false },
                    );
                } else {
                    await this.orm.unlink("apex.uniform.infringement", [record.id]);
                }
            }
            if (this.props.onSaved) {
                await this.props.onSaved();
            }
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }
}
