import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";

export class WeeklySubmissionResults extends Component {
    static template = "aps_sis.WeeklySubmissionResults";
    static components = { PercentPie };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.onCellClick = this.onCellClick.bind(this);
        this.toggleType = this.toggleType.bind(this);
        this.selectAllTypes = this.selectAllTypes.bind(this);
        this.selectNoTypes = this.selectNoTypes.bind(this);
        this.storageKey = "aps_sis_weekly_submission_results_filters";
        this.state = useState({
            loading: true,
            error: false,
            studentId: false,
            students: [],
            types: [],
            selectedTypeIds: [],
            academicTermId: false,
            terms: [],
            startDate: "",
            endDate: "",
            weeks: [],
            rows: [],
        });
        this.state.selectedTypeIds = null;
        this._restoreFilterState();
        onWillStart(() => this.load());
    }

    _restoreFilterState() {
        try {
            const saved = JSON.parse(window.localStorage.getItem(this.storageKey) || "null");
            if (!saved || typeof saved !== "object") {
                return;
            }
            if (typeof saved.startDate === "string") this.state.startDate = saved.startDate;
            if (typeof saved.endDate === "string") this.state.endDate = saved.endDate;
            if (saved.studentId) this.state.studentId = Number(saved.studentId);
            if (saved.academicTermId) this.state.academicTermId = Number(saved.academicTermId);
            if (saved.selectedTypeIds === null) {
                this.state.selectedTypeIds = null;
            } else if (Array.isArray(saved.selectedTypeIds)) {
                this.state.selectedTypeIds = saved.selectedTypeIds.map(Number).filter(Boolean);
            }
        } catch {
            // Ignore unavailable or malformed browser storage.
        }
    }

    _saveFilterState() {
        try {
            window.localStorage.setItem(this.storageKey, JSON.stringify({
                startDate: this.state.startDate,
                endDate: this.state.endDate,
                studentId: this.state.studentId || false,
                academicTermId: this.state.academicTermId || false,
                selectedTypeIds: this.state.selectedTypeIds,
            }));
        } catch {
            // Ignore unavailable browser storage.
        }
    }

    async load() {
        this.state.loading = true;
        const requestedTypeIds = this.state.selectedTypeIds;
        try {
            const data = await this.orm.call("aps.weekly.submission.result", "get_grid_data", [
                this.state.studentId || false,
                this.state.startDate || false,
                this.state.endDate || false,
                this.state.selectedTypeIds,
                this.state.academicTermId || false,
            ]);
            Object.assign(this.state, data, { loading: false, error: false });
            this.state.selectedTypeIds = requestedTypeIds;
            this._saveFilterState();
        } catch (error) {
            this.state.loading = false;
            this.state.error = error.message || "Unable to load submission results.";
        }
    }

    async onChangeFilter() {
        if (this.state.studentId) {
            this.state.studentId = Number(this.state.studentId);
        }
        await this.load();
    }

    async onTermChange() {
        const term = this.state.terms.find((item) => item.id === Number(this.state.academicTermId));
        if (term) {
            this.state.startDate = term.start;
            this.state.endDate = term.end;
        }
        this._saveFilterState();
        await this.load();
    }

    async onCellClick(cell) {
        if (!cell || !cell.submission_domain) {
            return;
        }
        const action = this.actionService;
        if (!action) {
            this.state.error = "The submission navigation service is unavailable.";
            return;
        }
        await action.doAction({
            type: "ir.actions.act_window",
            name: "Cell Submissions",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain: cell.submission_domain,
            context: {
                search_default_submitted: 0,
                search_default_completed: 0,
            },
        });
    }

    typeSelected(typeId) {
        return this.state.selectedTypeIds === null || this.state.selectedTypeIds.includes(typeId);
    }

    onTypeMenuControlMouseDown(event) {
        event.preventDefault();
    }

    submissionCountStyle(count) {
        const intensity = Math.min(Math.max(Number(count) || 0, 0), 10) / 10;
        const channel = Math.round(255 - (185 * intensity));
        const colour = `rgb(${channel}, ${channel}, ${channel})`;
        const textColour = channel < 150 ? "#ffffff" : "#212529";
        return `background-color: ${colour} !important; color: ${textColour} !important;`;
    }

    get groupedRows() {
        const groups = new Map();
        for (const row of this.state.rows) {
            if (!groups.has(row.subject_id)) {
                groups.set(row.subject_id, {
                    key: row.subject_id,
                    subjectName: row.subject_name,
                    subjectIconUrl: row.subject_icon_url,
                    rows: [],
                });
            }
            groups.get(row.subject_id).rows.push(row);
        }
        return [...groups.values()];
    }

    toggleType(typeId) {
        const ids = new Set(this.state.selectedTypeIds || this.state.types.map((type) => type.id));
        if (ids.has(typeId)) ids.delete(typeId);
        else ids.add(typeId);
        this.state.selectedTypeIds = [...ids];
        this._saveFilterState();
        this.load();
    }

    selectAllTypes() {
        this.state.selectedTypeIds = null;
        this._saveFilterState();
        this.load();
    }

    selectNoTypes() {
        this.state.selectedTypeIds = [];
        this._saveFilterState();
        this.load();
    }
}

registry.category("actions").add("aps_sis_weekly_submission_results", WeeklySubmissionResults);
