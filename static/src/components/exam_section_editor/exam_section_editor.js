import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
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
            savingLabel: false,
        });
        this.savedLabel = "";
        this.labelSaveTimer = null;
        onWillStart(async () => {
            const sectionId = this.props.action?.params?.section_id;
            await this.loadSection(sectionId);
        });
        onWillUnmount(() => window.clearTimeout(this.labelSaveTimer));
    }

    async loadSection(sectionId) {
        this.state.data = await this.orm.call(
            "aps.exam.paper.section", "get_region_editor_data", [[sectionId]]
        );
        this.savedLabel = this.state.data.label || "";
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
        if (!(await this._save()) || !(await this._saveLabel())) {
            return;
        }
        await this.loadSection(section.id);
    }

    async stagePage(documentType, page) {
        if (!(await this._saveLabel())) {
            return;
        }
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
        await this._save();
    }

    selectRegion(region) {
        if (this.state.saving) {
            return;
        }
        this._stashDraft();
        this.state.selected = region;
        const key = this._regionKey(region);
        this.state.draft = this.state.edits[key]
            ? { ...this.state.edits[key] }
            : { ...region.region };
        requestAnimationFrame(() => this._scrollSelectedRegionIntoView());
    }

    _scrollSelectedRegionIntoView() {
        const overlay = document.querySelector(".o_exam_region_overlay");
        const preview = overlay?.closest(".o_exam_region_editor_page");
        if (!overlay || !preview) {
            return;
        }
        const overlayRect = overlay.getBoundingClientRect();
        const previewRect = preview.getBoundingClientRect();
        const verticalOffset = overlayRect.top - previewRect.top
            - (preview.clientHeight - overlayRect.height) / 2;
        const horizontalOffset = overlayRect.left - previewRect.left
            - (preview.clientWidth - overlayRect.width) / 2;
        preview.scrollTo({
            top: preview.scrollTop + verticalOffset,
            left: preview.scrollLeft + horizontalOffset,
            behavior: "smooth",
        });
    }

    _regionKey(region) {
        return region.is_new
            ? `${region.document_type}:${region.local_id}`
            : `${region.document_type}:${region.index}`;
    }

    _stashDraft() {
        if (this.state.selected && this.state.draft) {
            const key = this._regionKey(this.state.selected);
            const original = this.state.selected.region;
            const boundsChanged = ["x1", "y1", "x2", "y2"].some(
                (bound) => this.state.draft[bound] !== original[bound]
            );
            if (boundsChanged) {
                this.state.edits[key] = { ...this.state.draft };
            } else {
                delete this.state.edits[key];
            }
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
        this._stashDraft();
        this._save();
    }

    onLabelInput(event) {
        this.state.data.label = event.target.value;
        window.clearTimeout(this.labelSaveTimer);
        this.labelSaveTimer = window.setTimeout(() => this._saveLabel(), 400);
    }

    async _saveLabel() {
        window.clearTimeout(this.labelSaveTimer);
        this.labelSaveTimer = null;
        if (!this.state.data) {
            return true;
        }
        const label = (this.state.data.label || "").trim();
        if (!label) {
            this.state.data.label = this.savedLabel;
            this.notification.add("Section name cannot be empty.", { type: "warning" });
            return false;
        }
        if (label === this.savedLabel) {
            this.state.data.label = label;
            return true;
        }
        if (this.labelSavePromise) {
            await this.labelSavePromise;
            if ((this.state.data?.label || "").trim() !== this.savedLabel) {
                return this._saveLabel();
            }
            return true;
        }

        this.state.savingLabel = true;
        const previousLabel = this.savedLabel;
        this.labelSavePromise = this.orm.call(
            "aps.exam.paper.section", "write",
            [[this.state.data.id], { display_label: label }]
        );
        try {
            await this.labelSavePromise;
            this.savedLabel = label;
            if ((this.state.data.label || "").trim() === label) {
                this.state.data.label = label;
            }
        } catch {
            if ((this.state.data?.label || "").trim() === label) {
                this.state.data.label = previousLabel;
            }
            this.notification.add("Unable to save the section name.", { type: "danger" });
            return false;
        } finally {
            this.labelSavePromise = null;
            this.state.savingLabel = false;
        }
        if ((this.state.data?.label || "").trim() !== this.savedLabel) {
            return this._saveLabel();
        }
        return true;
    }

    async _save() {
        if (!this.state.data) {
            return true;
        }
        this._stashDraft();
        const changes = Object.entries(this.state.edits);
        const additions = this.state.additions.map((region) => ({
            region,
            document_type: region.document_type,
            page_number: region.page_number,
            bounds: this.state.edits[this._regionKey(region)] || region.region,
        }));
        if (!changes.length && !additions.length) {
            return true;
        }

        const selectedLocalId = this.state.selected?.is_new
            ? this.state.selected.local_id
            : false;
        const edits = changes
            .filter(([key]) => !key.includes(":new-"))
            .map(([key, bounds]) => {
                const separator = key.indexOf(":");
                const documentType = key.slice(0, separator);
                const index = key.slice(separator + 1);
                return { document_type: documentType, index: Number(index), bounds };
            });
        const addedRegions = additions.map(({ document_type, page_number, bounds }) => ({
            document_type,
            page_number,
            bounds,
        }));

        this.state.saving = true;
        try {
            await this.orm.call(
                "aps.exam.paper.section", "save_region_editor_changes",
                [[this.state.data.id], edits, addedRegions]
            );

            for (const [key, bounds] of changes) {
                if (key.includes(":new-")) {
                    continue;
                }
                const separator = key.indexOf(":");
                const documentType = key.slice(0, separator);
                const index = Number(key.slice(separator + 1));
                const region = this.state.data.regions[documentType].find(
                    (item) => item.index === index
                );
                if (region) {
                    region.region = { ...bounds };
                }
            }

            for (const addition of additions) {
                const regions = this.state.data.regions[addition.document_type];
                const savedRegion = {
                    ...addition.region,
                    index: regions.length,
                    is_new: false,
                    region: { ...addition.bounds },
                };
                delete savedRegion.local_id;
                regions.push(savedRegion);
                if (selectedLocalId === addition.region.local_id) {
                    this.state.selected = savedRegion;
                }
            }
            this.state.edits = {};
            this.state.additions = [];
            if (this.state.selected) {
                this.state.draft = { ...this.state.selected.region };
            }
            return true;
        } catch {
            this.notification.add("Unable to save crop changes.", { type: "danger" });
            return false;
        } finally {
            this.state.saving = false;
        }
    }

    async removeRegion(event, region) {
        event.stopPropagation();
        if (this.state.saving || !(await this._saveLabel())) {
            return;
        }
        if (!window.confirm(`Remove this image from ${this.state.data.label}?`)) return;
        if (region.is_new) {
            const key = this._regionKey(region);
            const index = this.state.additions.indexOf(region);
            if (index !== -1) {
                this.state.additions.splice(index, 1);
            }
            delete this.state.edits[key];
            if (this.state.selected === region) {
                this.state.selected = null;
                this.state.draft = null;
            }
            return;
        }
        await this.orm.call(
            "aps.exam.paper.section", "remove_region_editor_region",
            [[this.state.data.id], region.document_type, region.index]
        );
        await this.loadSection(this.state.data.id);
    }

    async close() {
        this._stashDraft();
        if (!(await this._save()) || !(await this._saveLabel())) {
            return;
        }
        const controller = this.action.currentController;
        if (controller?.config?.historyBack) {
            controller.config.historyBack();
        } else {
            window.history.back();
        }
    }
}

registry.category("actions").add("aps_exam_section_region_editor", ExamSectionRegionEditor);
