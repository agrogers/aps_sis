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
        this.toggleClassDropdown = this.toggleClassDropdown.bind(this);
        this.selectClass = this.selectClass.bind(this);
        this.onStudentChange = this.onStudentChange.bind(this);
        this.onDropdownSearchKeydown = this.onDropdownSearchKeydown.bind(this);
        this.storageKey = "aps_sis_weekly_submission_results_filters";
        this.state = useState({
            loading: true,
            error: false,
            classId: false,
            classes: [],
            classDropdownOpen: false,
            classSearch: "",
            studentId: false,
            students: [],
            canSelectAllStudents: true,
            groupByStudent: false,
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
            if (saved.classId) this.state.classId = Number(saved.classId);
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
                classId: this.state.classId || false,
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
                this.state.classId || false,
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

    async onStudentChange() {
        this.state.studentId = this.state.studentId ? Number(this.state.studentId) : false;
        await this.load();
    }

    async onClassChange() {
        this.state.classId = this.state.classId ? Number(this.state.classId) : false;
        this.state.studentId = false;
        this._saveFilterState();
        await this.load();
    }

    toggleClassDropdown() {
        this.state.classDropdownOpen = !this.state.classDropdownOpen;
        this.state.classSearch = "";
    }

    async selectClass(classOrEvent) {
        const classId = classOrEvent?.currentTarget
            ? Number(classOrEvent.currentTarget.dataset.classId) || false
            : classOrEvent?.id || false;
        this.state.classId = classId;
        this.state.classDropdownOpen = false;
        this.state.classSearch = "";
        await this.onClassChange();
    }

    onDropdownSearchKeydown(event) {
        event.stopPropagation();
    }

    get filteredClasses() {
        const query = (this.state.classSearch || "").trim().toLowerCase();
        if (!query) {
            return this.state.classes;
        }
        return this.state.classes.filter((classItem) =>
            (classItem.name || "").toLowerCase().includes(query)
        );
    }

    get selectedClass() {
        return this.state.classes.find((classItem) => classItem.id === this.state.classId);
    }

    get selectedStudentName() {
        if (!this.state.studentId) {
            return "All Students";
        }
        return this.state.students.find((student) => student.id === this.state.studentId)?.name || "All Students";
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
                    typeGroups: [],
                });
            }
            const group = groups.get(row.subject_id);
            if (this.state.groupByStudent) {
                let typeGroup = group.typeGroups.find((item) => item.typeId === row.type_id);
                if (!typeGroup) {
                    typeGroup = {
                        key: `${row.subject_id}-${row.type_id}`,
                        typeId: row.type_id,
                        typeName: row.type_name,
                        typeDescription: row.type_description,
                        typeIconUrl: row.type_icon_url,
                        rows: [],
                    };
                    group.typeGroups.push(typeGroup);
                }
                typeGroup.rows.push(row);
            } else {
                group.rows.push(row);
            }
        }
        for (const group of groups.values()) {
            group.typeGroups.sort((left, right) => left.typeName.localeCompare(right.typeName));
            for (const typeGroup of group.typeGroups) {
                typeGroup.rows.sort((left, right) => left.student_name.localeCompare(right.student_name));
            }
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
