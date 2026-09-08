import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

const MIN_SIZE = 8;

export class ExamSectionRegionEditor extends Component {
    static template = "aps_sis.ExamSectionRegionEditor";
    static props = { action: { type: Object, optional: true } };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            data: null,
            selected: null,
            draft: null,
            edits: {},
            saving: false,
        });
        onWillStart(async () => {
            const sectionId = this.props.action?.params?.section_id;
            this.state.data = await this.orm.call(
                "aps.exam.paper.section", "get_region_editor_data", [[sectionId]]
            );
        });
    }

    get regions() {
        if (!this.state.data) {
            return [];
        }
        return [
            ...(this.state.data.regions.question || []),
            ...(this.state.data.regions.mark_scheme || []),
        ];
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
        return `${region.document_type}:${region.index}`;
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
        if (!this.state.selected || !this.state.draft) return;
        this._stashDraft();
        this.state.saving = true;
        try {
            const changes = Object.entries(this.state.edits);
            await Promise.all(changes.map(([key, bounds]) => {
                const [documentType, index] = key.split(":");
                return this.orm.call(
                    "aps.exam.paper.section", "save_region_editor_region",
                    [[this.state.data.id], documentType, Number(index), bounds]
                );
            }));
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
