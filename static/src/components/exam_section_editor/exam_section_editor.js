import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { Dialog } from "@web/core/dialog/dialog";

const MIN_SIZE = 8;

export class ExamSectionPagePicker extends Component {
    static template = "aps_sis.ExamSectionPagePicker";
    static components = { Dialog };
    static props = {
        documentType: { type: String },
        pages: { type: Array },
        close: { type: Function },
        onSelect: { type: Function },
    };

    selectPage(page) {
        this.props.onSelect(page);
        this.props.close();
    }
}

export class ExamSectionRegionEditor extends Component {
    static template = "aps_sis.ExamSectionRegionEditor";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.state = useState({
            data: null,
            selected: null,
            draft: null,
            edits: {},
            additions: [],
            saving: false,
        });
        onWillStart(async () => {
            const sectionId = this.props.action?.params?.section_id;
            await this.loadSection(sectionId);
        });
    }

    async loadSection(sectionId) {
        this.state.data = await this.orm.call(
            "aps.exam.paper.section", "get_region_editor_data", [[sectionId]]
        );
        this.state.selected = null;
        this.state.draft = null;
        this.state.edits = {};
        this.state.additions = [];
    }

    get regions() {
        if (!this.state.data) {
            return [];
        }
        return [
            ...(this.state.data.regions.question || []),
            ...(this.state.data.regions.mark_scheme || []),
            ...this.state.additions,
        ];
    }

    regionsFor(documentType) {
        if (!this.state.data) {
            return [];
        }
        const detected = this.state.data.regions[documentType] || [];
        return [
            ...detected,
            ...this.state.additions.filter((region) => region.document_type === documentType),
        ];
    }

    addPage(documentType) {
        this.dialog.add(ExamSectionPagePicker, {
            documentType,
            pages: this.state.data?.pages?.[documentType] || [],
            onSelect: (page) => this.stagePage(documentType, page),
        });
    }

    async navigateTo(section) {
        if (!section || this.state.saving) {
            return;
        }
        this._stashDraft();
        if (this.state.additions.length || Object.keys(this.state.edits).length) {
            const confirmed = window.confirm("Discard unsaved region changes?");
            if (!confirmed) {
                return;
            }
        }
        await this.loadSection(section.id);
    }

    stagePage(documentType, page) {
        const addition = {
            ...page,
            index: null,
            local_id: `new-${documentType}-${Date.now()}-${this.state.additions.length}`,
            document_type: documentType,
            label: this.state.data.label,
            region: { ...page.default_region },
            is_new: true,
        };
        this.state.additions.push(addition);
        this.selectRegion(addition);
    }

    selectRegion(region) {
        this._stashDraft();
        this.state.selected = region;
        const key = this._regionKey(region);
        this.state.draft = this.state.edits[key]
            ? { ...this.state.edits[key] }
            : { ...region.region };
    }

    _regionKey(region) {
        return region.is_new
            ? `${region.document_type}:${region.local_id}`
            : `${region.document_type}:${region.index}`;
    }

    _stashDraft() {
        if (this.state.selected && this.state.draft) {
            this.state.edits[this._regionKey(this.state.selected)] = {
                ...this.state.draft,
            };
        }
    }

    styleFor(region) {
        const bounds = region.region;
        return `left:${bounds.x1}px;top:${bounds.y1}px;width:${bounds.x2 - bounds.x1}px;height:${bounds.y2 - bounds.y1}px;`;
    }

    previewStyle(region) {
        return `width:250px;height:250px;`;
    }

    previewImageStyle(region) {
        const bounds = region.region;
        const width = Math.max(1, bounds.x2 - bounds.x1);
        const height = Math.max(1, bounds.y2 - bounds.y1);
        const scale = Math.min(250 / width, 250 / height);
        const offsetX = (250 - width * scale) / 2;
        const offsetY = (250 - height * scale) / 2;
        return `width:${region.width * scale}px;height:${region.height * scale}px;left:${offsetX - bounds.x1 * scale}px;top:${offsetY - bounds.y1 * scale}px;`;
    }

    draftStyle() {
        const region = this.state.selected;
        if (!region || !this.state.draft) return "";
        const bounds = this.state.draft;
        return `left:${(bounds.x1 / region.width) * 100}%;top:${(bounds.y1 / region.height) * 100}%;width:${((bounds.x2 - bounds.x1) / region.width) * 100}%;height:${((bounds.y2 - bounds.y1) / region.height) * 100}%;`;
    }

    startDrag(event, side) {
        event.preventDefault();
        event.stopPropagation();
        const image = event.currentTarget.closest(".o_exam_region_image_wrap").querySelector("img");
        this.dragging = { side, image, pointerId: event.pointerId };
        event.currentTarget.setPointerCapture?.(event.pointerId);
        this._move = (moveEvent) => this.resize(moveEvent);
        this._up = () => this.stopDrag();
        window.addEventListener("pointermove", this._move);
        window.addEventListener("pointerup", this._up, { once: true });
    }

    resize(event) {
        const dragging = this.dragging;
        const draft = this.state.draft;
        if (!dragging || !draft) return;
        const rect = dragging.image.getBoundingClientRect();
        const region = this.state.selected;
        const scaleX = region.width / rect.width;
        const scaleY = region.height / rect.height;
        const x = Math.round(Math.max(0, Math.min(region.width, (event.clientX - rect.left) * scaleX)));
        const y = Math.round(Math.max(0, Math.min(region.height, (event.clientY - rect.top) * scaleY)));
        if (dragging.side === "left") draft.x1 = Math.min(x, draft.x2 - MIN_SIZE);
        if (dragging.side === "right") draft.x2 = Math.max(x, draft.x1 + MIN_SIZE);
        if (dragging.side === "top") draft.y1 = Math.min(y, draft.y2 - MIN_SIZE);
        if (dragging.side === "bottom") draft.y2 = Math.max(y, draft.y1 + MIN_SIZE);
    }

    stopDrag() {
        if (this._move) window.removeEventListener("pointermove", this._move);
        this.dragging = null;
    }

    async save() {
        if (!this.state.data || (!this.state.selected && !this.state.additions.length && !Object.keys(this.state.edits).length)) return;
        this._stashDraft();
        this.state.saving = true;
        try {
            const changes = Object.entries(this.state.edits);
            const edits = changes
                .filter(([key]) => !key.includes(":new-"))
                .map(([key, bounds]) => {
                    const separator = key.indexOf(":");
                    const documentType = key.slice(0, separator);
                    const index = key.slice(separator + 1);
                    return { document_type: documentType, index: Number(index), bounds };
                });
            const additions = this.state.additions.map((region) => ({
                document_type: region.document_type,
                page_number: region.page_number,
                bounds: this.state.edits[this._regionKey(region)] || region.region,
            }));
            await this.orm.call(
                "aps.exam.paper.section", "save_region_editor_changes",
                [[this.state.data.id], edits, additions]
            );
            this.notification.add("Region saved.", { type: "success" });
            this.close();
        } finally {
            this.state.saving = false;
        }
    }

    cancel() {
        this.close();
    }

    close() {
        const controller = this.action.currentController;
        if (controller?.config?.historyBack) {
            controller.config.historyBack();
        } else {
            window.history.back();
        }
    }
}

registry.category("actions").add("aps_exam_section_region_editor", ExamSectionRegionEditor);
