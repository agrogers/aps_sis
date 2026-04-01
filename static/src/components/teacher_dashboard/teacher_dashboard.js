import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "aps_teacher_dashboard_state";

function _loadStoredState() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch {
        return {};
    }
}

export class TeacherDashboard extends Component {
    static template = "aps_sis.TeacherDashboard";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const gs = this.props.globalState || _loadStoredState();
        this.state = useState({
            loading: true,
            categoryId: gs.categoryId ?? false,
            days: gs.days ?? 30,
            categories: [],
            subjectResources: [],
            taskResources: [],
            selectedResourceId: gs.selectedResourceId ?? false,
            selectedResourceName: gs.selectedResourceName ?? "",
            submissions: [],
            submissionsLoading: false,
        });

        onWillStart(async () => {
            await this._fetchData({ resetSelection: false });
            if (this.state.selectedResourceId) {
                await this._fetchSubmissions(this.state.selectedResourceId);
            }
        });
    }

    // ------------------------------------------------------------------ //
    // Date range label helpers
    // ------------------------------------------------------------------ //
    get dateRangeOptions() {
        return [
            { value: 1, label: "Last Day" },
            { value: 8, label: "Last 8 Days" },
            { value: 14, label: "Last 14 Days" },
            { value: 30, label: "Last 30 Days" },
            { value: -1, label: "All Time" },
        ];
    }

    // ------------------------------------------------------------------ //
    // Data fetching
    // ------------------------------------------------------------------ //
    _saveState() {
        const snapshot = {
            categoryId: this.state.categoryId,
            days: this.state.days,
            selectedResourceId: this.state.selectedResourceId,
            selectedResourceName: this.state.selectedResourceName,
        };
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
        } catch {
            // localStorage full or blocked — ignore
        }
        if (this.props.updateActionState) {
            this.props.updateActionState(snapshot);
        }
    }

    async _fetchData({ resetSelection = true } = {}) {
        this.state.loading = true;
        if (resetSelection) {
            this.state.selectedResourceId = false;
            this.state.submissions = [];
        }
        const data = await this.orm.call(
            "aps.resources",
            "get_teacher_dashboard_data",
            [],
            { category_id: this.state.categoryId, days: this.state.days }
        );
        this.state.categories = data.categories || [];
        this.state.subjectResources = data.subject_resources || [];
        this.state.taskResources = data.task_resources || [];
        this.state.loading = false;
        this._saveState();
    }

    async _fetchSubmissions(resourceId) {
        this.state.submissionsLoading = true;
        const subs = await this.orm.call(
            "aps.resources",
            "get_dashboard_submissions_for_resource",
            [],
            {
                resource_id: resourceId,
                days: this.state.days,
            }
        );
        this.state.submissions = subs || [];
        this.state.submissionsLoading = false;
    }

    // ------------------------------------------------------------------ //
    // Event handlers — filters
    // ------------------------------------------------------------------ //
    async onChangeCategory(ev) {
        const val = ev.target.value;
        this.state.categoryId = val ? parseInt(val) : false;
        await this._fetchData();
    }

    async onChangeDays(ev) {
        this.state.days = parseInt(ev.target.value);
        await this._fetchData();
    }


    // ------------------------------------------------------------------ //
    // Event handlers — resource actions
    // ------------------------------------------------------------------ //
    openResource(resourceId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resources",
            res_id: resourceId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async selectResource(resourceId, resourceName) {
        if (this.state.selectedResourceId === resourceId) {
            // Toggle off
            this.state.selectedResourceId = false;
            this.state.selectedResourceName = "";
            this.state.submissions = [];
        } else {
            this.state.selectedResourceId = resourceId;
            this.state.selectedResourceName = resourceName;
            await this._fetchSubmissions(resourceId);
        }
        this._saveState();
    }

    openSubmission(submissionId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resource.submission",
            res_id: submissionId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------ //
    // Helpers
    // ------------------------------------------------------------------ //
    get _stateConfig() {
        return {
            assigned: { label: "Assigned", badgeClass: "bg-secondary" },
            submitted: { label: "Submitted", badgeClass: "bg-primary" },
            complete: { label: "Finalised", badgeClass: "bg-success" },
        };
    }

    stateLabel(state) {
        return (this._stateConfig[state] || {}).label || state;
    }

    stateBadgeClass(state) {
        return (this._stateConfig[state] || {}).badgeClass || "bg-secondary";
    }

    typeIconUrl(typeId) {
        const id = Array.isArray(typeId) ? typeId[0] : typeId;
        return `/web/image/aps.resource.types/${id}/icon`;
    }

    scoreColorClass(score) {
        if (score === false || score === null || score === undefined) return "aps-score-none";
        if (score >= 80) return "aps-score-high";
        if (score >= 50) return "aps-score-mid";
        return "aps-score-low";
    }
}

registry.category("actions").add("aps_teacher_dashboard", TeacherDashboard);
