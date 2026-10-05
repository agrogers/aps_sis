import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { ResourceHierarchyTable } from "../resource_hierarchy_table/resource_hierarchy_table";
import { PercentPie } from "../percent_pie/percent_pie";
import { BadgeDecoratorDisplay } from "../../js/badge_decorator_widget";

const STORAGE_KEY = "aps_teacher_dashboard_state";

function _loadStoredState() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch {
        return {};
    }
}

function _normalizeResourceId(value) {
    if (value === false || value === null || value === undefined || value === "") {
        return false;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? false : parsed;
}

export class TeacherDashboard extends Component {
    static template = "aps_sis.TeacherDashboard";
    static components = { ResourceHierarchyTable, PercentPie, BadgeDecoratorDisplay };
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
        this._submissionFormViewId = null;
        this._submissionGroupIndex = new Map();

        const storedState = _loadStoredState();
        const actionState = this.props.globalState || {};
        const gs = {
            ...storedState,
            ...actionState,
        };
        const restoredResourceId = _normalizeResourceId(gs.selectedResourceId);
        this.state = useState({
            loading: true,
            categoryId: gs.categoryId ?? false,
            days: gs.days ?? 30,
            studentId: gs.studentId ?? false,
            categories: [],
            students: [],
            subjectResources: [],
            favouriteResources: [],
            taskResources: [],
            submissionGroups: [],
            dashboardMetrics: {},
            expandedSubmissionGroups: gs.expandedSubmissionGroups ?? {},
            hiddenSubmissionTypes: gs.hiddenSubmissionTypes ?? {},
            selectedResourceId: restoredResourceId,
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
            studentId: this.state.studentId,
            selectedResourceId: this.state.selectedResourceId,
            selectedResourceName: this.state.selectedResourceName,
            expandedSubmissionGroups: Object.fromEntries(
                Object.entries(this.state.expandedSubmissionGroups)
            ),
            hiddenSubmissionTypes: Object.fromEntries(
                Object.entries(this.state.hiddenSubmissionTypes)
            ),
        };
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
        } catch {
            // localStorage full or blocked - ignore
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
            {
                category_id: this.state.categoryId,
                days: this.state.days,
                student_id: this.state.studentId,
            }
        );
        this.state.categories = data.categories || [];
        this.state.students = data.students || [];
        this.state.studentId = data.selected_student_id || false;
        this.state.subjectResources = data.subject_resources || [];
        this.state.favouriteResources = data.favourite_resources || [];
        this.state.taskResources = data.task_resources || [];
        this.state.submissionGroups = data.submission_groups || [];
        this.state.dashboardMetrics = data.dashboard_metrics || {};
        this._submissionGroupIndex = new Map(
            this.state.submissionGroups.map((group) => [group.key, group])
        );

        if (this.state.selectedResourceId) {
            const restored = this.state.taskResources.find(
                (res) => res.id === this.state.selectedResourceId
            );
            if (restored) {
                this.state.selectedResourceName = restored.name || this.state.selectedResourceName;
            } else {
                this.state.selectedResourceId = false;
                this.state.selectedResourceName = "";
                this.state.submissions = [];
            }
        }

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
                student_id: this.state.studentId,
            }
        );
        this.state.submissions = subs || [];
        this.state.submissionsLoading = false;
    }

    // ------------------------------------------------------------------ //
    // Event handlers - filters
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

    async onChangeStudent(ev) {
        this.state.studentId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        await this._fetchData();
    }


    // ------------------------------------------------------------------ //
    // Event handlers - resource actions
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

    async _getSubmissionFormViewId() {
        if (this._submissionFormViewId) {
            return this._submissionFormViewId;
        }

        let viewId = false;
        try {
            // Preferred pattern already used elsewhere in this addon static code.
            const [, resolvedViewId] = await this.orm.call(
                "ir.model.data",
                "check_object_reference",
                ["aps_sis", "view_aps_resource_submission_form"]
            );
            viewId = resolvedViewId || false;
        } catch {
            // Fallback for environments where check_object_reference may be restricted.
            const [data] = await this.orm.searchRead(
                "ir.model.data",
                [["module", "=", "aps_sis"], ["name", "=", "view_aps_resource_submission_form"]],
                ["res_id"],
                { limit: 1 }
            );
            viewId = data ? data.res_id : false;
        }

        this._submissionFormViewId = viewId;
        return this._submissionFormViewId;
    }

    async openSubmission(submissionId) {
        const formViewId = await this._getSubmissionFormViewId();
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resource.submission",
            res_id: submissionId,
            views: [[formViewId || false, "form"]],
            target: "current",
        });
    }

    async openAllSubmissions() {
        const domain = [["resource_id", "=", this.state.selectedResourceId]];
        if (this.state.studentId) {
            domain.push(["task_id.student_id", "=", this.state.studentId]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    toggleSubmissionGroup(key) {
        this.state.expandedSubmissionGroups[key] = !this.state.expandedSubmissionGroups[key];
        this._saveState();
    }

    toggleSubmissionType(typeId) {
        this.state.hiddenSubmissionTypes[typeId] = !this.state.hiddenSubmissionTypes[typeId];
        this._saveState();
    }

    get submissionGroupTypes() {
        const types = new Map();
        for (const group of this.state.submissionGroups) {
            if (!group.type_id) {
                continue;
            }
            const [id, name] = group.type_id;
            if (!types.has(id)) {
                types.set(id, {
                    id,
                    name,
                    type_icon: group.type_icon,
                    total: 0,
                    overdue: 0,
                    assigned: 0,
                    submitted: 0,
                    finalised: 0,
                });
            }
            const type = types.get(id);
            type.total += group.total;
            type.overdue += group.overdue;
            type.assigned += group.assigned;
            type.submitted += group.submitted;
            type.finalised += group.finalised;
        }
        return [...types.values()]
            .map((type) => ({
                ...type,
                badgeColor: type.overdue
                    ? "overdue"
                    : type.assigned
                      ? "assigned"
                      : type.submitted
                        ? "submitted"
                        : "finalised",
            }))
            .sort((left, right) => left.name.localeCompare(right.name));
    }

    get visibleSubmissionGroups() {
        const childrenByParent = new Map();
        for (const group of this.state.submissionGroups) {
            const key = group.parent_key || "";
            if (!childrenByParent.has(key)) {
                childrenByParent.set(key, []);
            }
            childrenByParent.get(key).push(group);
        }
        for (const [parentKey, groups] of childrenByParent) {
            if (parentKey) {
                groups.sort(
                    (left, right) =>
                        (left.resource_sequence || 0) - (right.resource_sequence || 0) ||
                        left.resource_id - right.resource_id ||
                        left.label.localeCompare(right.label)
                );
            }
        }
        const hasVisibleTypeInSubtree = (group, ancestors = new Set()) => {
            if (ancestors.has(group.key)) {
                return false;
            }
            ancestors.add(group.key);
            const typeId = group.type_id ? group.type_id[0] : false;
            const hasVisibleType =
                typeId === false || !this.state.hiddenSubmissionTypes[typeId] ||
                (childrenByParent.get(group.key) || []).some(
                    (child) => hasVisibleTypeInSubtree(child, ancestors)
                );
            ancestors.delete(group.key);
            return hasVisibleType;
        };
        const visible = [];
        const appendChildren = (parentKey, depth, isRoot = false) => {
            for (const group of childrenByParent.get(parentKey) || []) {
                if (isRoot && !hasVisibleTypeInSubtree(group)) {
                    continue;
                }
                visible.push({ ...group, depth });
                if (this.state.expandedSubmissionGroups[group.key]) {
                    appendChildren(group.key, depth + 1);
                }
            }
        };
        appendChildren("", 0, true);
        return visible;
    }

    get visibleTaskResources() {
        return this.state.taskResources.filter((resource) => {
            const typeId = resource.type_id ? resource.type_id[0] : 0;
            return !this.state.hiddenSubmissionTypes[typeId];
        });
    }

    submissionGroupAncestors(group) {
        const ancestors = [];
        const visited = new Set([group.key]);
        let current = this._submissionGroupIndex.get(group.parent_key);
        while (current && !visited.has(current.key)) {
            visited.add(current.key);
            ancestors.push(current);
            current = this._submissionGroupIndex.get(current.parent_key);
        }
        ancestors.reverse();
        return ancestors.map((ancestor, index) => {
            return {
                key: ancestor.key,
                name: ancestor.title,
                indent: "- ".repeat(index),
            };
        });
    }

    openGroupSubmissions(submissionIds, groupTitle, filterLabel) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${filterLabel} — ${groupTitle}`,
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", submissionIds]],
            target: "current",
        });
    }

    openMetricSubmissions(domain, title) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    relativeDate(dateValue) {
        if (!dateValue) {
            return "—";
        }
        const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateValue);
        if (!match) {
            return dateValue;
        }
        const assigned = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
        if (Number.isNaN(assigned.getTime())) {
            return dateValue;
        }
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const days = Math.round((today - assigned) / 86400000);
        if (!days) {
            return "Today";
        }
        const count = Math.abs(days);
        let amount;
        let unit;
        if (count < 7) {
            amount = count;
            unit = "day";
        } else if (count < 30) {
            amount = Math.floor(count / 7);
            unit = "week";
        } else {
            amount = Math.floor(count / 30);
            unit = "mth";
        }
        const phrase = `${amount} ${unit}${amount === 1 ? "" : "s"}`;
        return days > 0 ? `${phrase} ago` : `in ${phrase}`;
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

    binaryIconUrl(iconData) {
        if (!iconData) {
            return "";
        }
        return iconData.startsWith("data:")
            ? iconData
            : `data:image/png;base64,${iconData}`;
    }

    scoreColorClass(score) {
        if (score === false || score === null || score === undefined) return "aps-score-none";
        if (score >= 80) return "aps-score-high";
        if (score >= 50) return "aps-score-mid";
        return "aps-score-low";
    }

    // URL generation for right-click / middle-click "open in new tab" support.
    // Must use real action XML IDs — Odoo 18's router looks up the action by ID
    // and will throw "does not exist" if the generic type name is used instead.
    getResourceUrl(resourceId) {
        return `/web#action=aps_sis.action_aps_resources&id=${resourceId}&view_type=form`;
    }

    getSubmissionsUrl(resourceId) {
        return `/web#action=aps_sis.action_aps_resource_submissions&view_type=list&search_default_resource_id=${resourceId}`;
    }

    getSubmissionUrl(submissionId) {
        return `/web#action=aps_sis.action_aps_resource_submissions&id=${submissionId}&view_type=form`;
    }
}

registry.category("actions").add("aps_teacher_dashboard", TeacherDashboard);
