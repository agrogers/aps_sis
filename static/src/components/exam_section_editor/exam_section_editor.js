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
            exclusionRegions: [],
            zoneDraft: null,
            addingExclusionZone: false,
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
        this.state.exclusionRegions = [];
        this.state.zoneDraft = null;
        this.state.addingExclusionZone = false;
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
            page_id: page.id,
            index: null,
            local_id: `new-${documentType}-${Date.now()}-${this.state.additions.length}`,
            document_type: documentType,
            label: this.state.data.label,
            region: { ...page.default_region },
            exclusion_regions: (page.exclusion_regions || []).map((zone) => ({ ...zone })),
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
        this.state.exclusionRegions = (region.exclusion_regions || []).map((zone) => ({ ...zone }));
        this.state.zoneDraft = null;
        this.state.addingExclusionZone = false;
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

    exclusionStyle(zone) {
        const bounds = this.state.zoneDraft?.id === zone.id ? this.state.zoneDraft : zone;
        const region = this.state.selected;
        if (!region || !bounds) return "";
        return `left:${(bounds.x1 / region.width) * 100}%;top:${(bounds.y1 / region.height) * 100}%;width:${((bounds.x2 - bounds.x1) / region.width) * 100}%;height:${((bounds.y2 - bounds.y1) / region.height) * 100}%;`;
    }

    zoneDraftStyle() {
        return this.exclusionStyle(this.state.zoneDraft || {});
    }

    toggleAddExclusionZone() {
        if (this.state.saving || !this.state.selected) return;
        this.state.addingExclusionZone = !this.state.addingExclusionZone;
        this.state.zoneDraft = null;
    }

    startDrag(event, side) {
        event.preventDefault();
        event.stopPropagation();
        const image = event.currentTarget.closest(".o_exam_region_image_wrap").querySelector("img");
        this.dragging = { kind: "section", side, image, pointerId: event.pointerId };
        event.currentTarget.setPointerCapture?.(event.pointerId);
        this._move = (moveEvent) => this.resize(moveEvent);
        this._up = () => this.stopDrag();
        window.addEventListener("pointermove", this._move);
        window.addEventListener("pointerup", this._up, { once: true });
    }

    startZoneDrag(event, zone, side) {
        event.preventDefault();
        event.stopPropagation();
        if (this.state.saving) return;
        const image = event.currentTarget.closest(".o_exam_region_image_wrap").querySelector("img");
        const point = this._pagePoint(event, image, this.state.selected);
        this.state.zoneDraft = { ...zone };
        this.dragging = {
            kind: "zone",
            zoneId: zone.id,
            side,
            image,
            origin: { ...zone },
            startPoint: point,
        };
        event.currentTarget.setPointerCapture?.(event.pointerId);
        this._move = (moveEvent) => this.resize(moveEvent);
        this._up = () => this.stopDrag();
        window.addEventListener("pointermove", this._move);
        window.addEventListener("pointerup", this._up, { once: true });
    }

    startExclusionDraw(event) {
        if (!this.state.addingExclusionZone || this.state.saving) return;
        event.preventDefault();
        const image = event.currentTarget.querySelector("img");
        const point = this._pagePoint(event, image, this.state.selected);
        this.state.zoneDraft = {
            id: "draft-zone",
            x1: point.x,
            y1: point.y,
            x2: point.x,
            y2: point.y,
        };
        this.dragging = {
            kind: "new-zone",
            image,
            startPoint: point,
        };
        event.currentTarget.setPointerCapture?.(event.pointerId);
        this._move = (moveEvent) => this.resize(moveEvent);
        this._up = () => this.stopDrag();
        window.addEventListener("pointermove", this._move);
        window.addEventListener("pointerup", this._up, { once: true });
    }

    _pagePoint(event, image, page) {
        const rect = image.getBoundingClientRect();
        return {
            x: Math.round(Math.max(0, Math.min(page.width, (event.clientX - rect.left) * page.width / rect.width))),
            y: Math.round(Math.max(0, Math.min(page.height, (event.clientY - rect.top) * page.height / rect.height))),
        };
    }

    resize(event) {
        const dragging = this.dragging;
        const region = this.state.selected;
        if (!dragging || !region) return;
        const point = this._pagePoint(event, dragging.image, region);
        if (dragging.kind === "new-zone") {
            const start = dragging.startPoint;
            this.state.zoneDraft.x1 = Math.min(start.x, point.x);
            this.state.zoneDraft.y1 = Math.min(start.y, point.y);
            this.state.zoneDraft.x2 = Math.max(start.x, point.x);
            this.state.zoneDraft.y2 = Math.max(start.y, point.y);
            return;
        }
        if (dragging.kind === "zone") {
            const draft = this.state.zoneDraft;
            if (dragging.side === "move") {
                const width = dragging.origin.x2 - dragging.origin.x1;
                const height = dragging.origin.y2 - dragging.origin.y1;
                draft.x1 = Math.max(0, Math.min(region.width - width, dragging.origin.x1 + point.x - dragging.startPoint.x));
                draft.y1 = Math.max(0, Math.min(region.height - height, dragging.origin.y1 + point.y - dragging.startPoint.y));
                draft.x2 = draft.x1 + width;
                draft.y2 = draft.y1 + height;
                return;
            }
            if (dragging.side === "left") draft.x1 = Math.min(point.x, draft.x2 - MIN_SIZE);
            if (dragging.side === "right") draft.x2 = Math.max(point.x, draft.x1 + MIN_SIZE);
            if (dragging.side === "top") draft.y1 = Math.min(point.y, draft.y2 - MIN_SIZE);
            if (dragging.side === "bottom") draft.y2 = Math.max(point.y, draft.y1 + MIN_SIZE);
            return;
        }
        const draft = this.state.draft;
        if (!draft) return;
        const { x, y } = point;
        if (dragging.side === "left") draft.x1 = Math.min(x, draft.x2 - MIN_SIZE);
        if (dragging.side === "right") draft.x2 = Math.max(x, draft.x1 + MIN_SIZE);
        if (dragging.side === "top") draft.y1 = Math.min(y, draft.y2 - MIN_SIZE);
        if (dragging.side === "bottom") draft.y2 = Math.max(y, draft.y1 + MIN_SIZE);
    }

    async stopDrag() {
        if (this._move) window.removeEventListener("pointermove", this._move);
        const dragging = this.dragging;
        this.dragging = null;
        if (dragging?.kind === "zone") {
            const edited = { ...this.state.zoneDraft, source: "manual", coordinate_system: "pixels" };
            const zones = this.state.exclusionRegions.map((zone) => (
                zone.id === dragging.zoneId ? edited : zone
            ));
            this.state.zoneDraft = null;
            await this._saveExclusionZones(zones);
            return;
        }
        if (dragging?.kind === "new-zone") {
            const draft = this.state.zoneDraft;
            this.state.zoneDraft = null;
            this.state.addingExclusionZone = false;
            if (draft.x2 - draft.x1 < MIN_SIZE || draft.y2 - draft.y1 < MIN_SIZE) {
                this.notification.add("Draw a larger exclusion zone.", { type: "warning" });
                return;
            }
            const zone = {
                ...draft,
                id: `manual-${Date.now()}-${this.state.exclusionRegions.length}`,
                source: "manual",
                coordinate_system: "pixels",
            };
            await this._saveExclusionZones([...this.state.exclusionRegions, zone]);
            return;
        }
        this._stashDraft();
        await this._save();
    }

    async removeExclusionZone(event, zone) {
        event.preventDefault();
        event.stopPropagation();
        if (this.state.saving) return;
        await this._saveExclusionZones(
            this.state.exclusionRegions.filter((item) => item.id !== zone.id)
        );
    }

    async _saveExclusionZones(zones) {
        const selected = this.state.selected;
        if (!selected || this.state.saving) return false;
        this.state.saving = true;
        try {
            const saved = await this.orm.call(
                "aps.exam.paper.section", "save_region_editor_exclusion_zones",
                [[this.state.data.id], selected.page_id, zones]
            );
            const savedZones = saved.map((zone) => ({ ...zone }));
            this.state.exclusionRegions = savedZones;
            selected.exclusion_regions = savedZones;
            for (const documentType of ["question", "mark_scheme"]) {
                for (const region of this.state.data.regions[documentType] || []) {
                    if (region.page_id === selected.page_id) {
                        region.exclusion_regions = savedZones;
                    }
                }
                for (const page of this.state.data.pages[documentType] || []) {
                    if (page.id === selected.page_id) {
                        page.exclusion_regions = savedZones;
                    }
                }
            }
            return true;
        } catch {
            this.notification.add("Unable to save exclusion zones.", { type: "danger" });
            return false;
        } finally {
            this.state.saving = false;
        }
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
