import { Component, onWillUpdateProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

export class SelectableKanbanRecord extends KanbanRecord {
    static template = "aps_sis.SelectableKanbanRecord";
    static props = [
        ...KanbanRecord.props,
        "isSelected",
        "toggleSelection",
    ];
}

export class SelectableKanbanRenderer extends KanbanRenderer {
    static template = "aps_sis.SelectableKanbanRenderer";
    static components = {
        ...KanbanRenderer.components,
        KanbanRecord: SelectableKanbanRecord,
    };
    static props = [...KanbanRenderer.props, "parentRecord"];

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state.selectedIds = [];
        this.state.busy = false;
        onWillUpdateProps((nextProps) => {
            if (nextProps.list !== this.props.list || nextProps.archInfo !== this.props.archInfo) {
                this.clearSelection();
            }
        });
    }

    get selectedCount() {
        return this.state.selectedIds.length;
    }

    get visibleRecords() {
        if (!this.rootRef.el) {
            return [];
        }
        const renderedDatapointIds = new Set(
            [...this.rootRef.el.querySelectorAll(".o_kanban_record[data-id]")]
                .map((card) => card.dataset.id)
        );
        return this.getLoadedRecords()
            .filter((record) => renderedDatapointIds.has(String(record.id)) && record.resId);
    }

    get visibleRecordIds() {
        return this.visibleRecords.map((record) => record.resId);
    }

    isSelected(record) {
        return this.state.selectedIds.includes(record.id);
    }

    toggleSelection(record) {
        if (this.state.busy || !record.resId) {
            return;
        }
        this.state.selectedIds = this.state.selectedIds.includes(record.id)
            ? this.state.selectedIds.filter((id) => id !== record.id)
            : [...this.state.selectedIds, record.id];
    }

    selectAllVisible() {
        if (this.state.busy) {
            return;
        }
        this.state.selectedIds = this.visibleRecords.map((record) => record.id);
    }

    clearSelection() {
        this.state.selectedIds = [];
    }

    stopEvent(event) {
        event.stopPropagation();
    }

    getSelectedRecords() {
        const selected = new Set(this.state.selectedIds);
        return this.visibleRecords.filter((record) => selected.has(record.id));
    }

    getLoadedRecords() {
        const records = [];
        const addRecords = (list) => {
            records.push(...(list.records || []));
            for (const group of list.groups || []) {
                addRecords(group.list);
            }
        };
        addRecords(this.props.list);
        return records;
    }

    deleteSelected() {
        const records = this.getSelectedRecords();
        if (!records.length || this.state.busy) {
            return;
        }
        const count = records.length;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete selected records"),
            body: count === 1
                ? _t("Delete this record? This cannot be undone.")
                : _t("Delete %s selected records? This cannot be undone.", count),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            cancelLabel: _t("Cancel"),
            cancel: () => {},
            confirm: () => this.deleteRecords(records),
        });
    }

    async deleteRecords(records) {
        if (await this.props.parentRecord.isDirty()) {
            this.notification.add(
                _t("Save or discard the form changes before deleting selected records."),
                { type: "warning" }
            );
            return false;
        }
        const ids = records.map((record) => record.resId);
        this.state.busy = true;
        try {
            await this.orm.unlink(this.props.list.resModel, ids, {
                context: this.props.parentRecord.context,
            });
            await this.props.parentRecord.load();
            this.clearSelection();
        } catch (error) {
            this.notification.add(error.message || _t("The selected records could not be deleted."), {
                type: "danger",
            });
            return false;
        } finally {
            this.state.busy = false;
        }
    }
}

export class SelectableX2ManyField extends X2ManyField {
    static template = "aps_sis.SelectableX2ManyField";
    static components = {
        ...X2ManyField.components,
        SelectableKanbanRenderer,
    };

    get rendererProps() {
        const props = super.rendererProps;
        if (this.props.viewMode === "kanban") {
            props.parentRecord = this.props.record;
        }
        return props;
    }
}

export const selectableKanbanField = {
    ...x2ManyField,
    component: SelectableX2ManyField,
    displayName: _t("Selectable kanban"),
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...x2ManyField.extractProps(fieldInfo, dynamicInfo),
    }),
};

registry.category("fields").add("selectable_kanban", selectableKanbanField);
