import { expect, test } from "@odoo/hoot";
import { TeacherDashboard } from "@aps_sis/components/teacher_dashboard/teacher_dashboard";

function makeDashboard(includePart = false) {
    const groups = [
        { key: "paper", type_id: [7, "Past Paper"], parent_key: false },
        { key: "q2", type_id: [1, "Question (Past Paper)"], parent_key: "paper", resource_sequence: 2 },
        { key: "q1", type_id: [1, "Question (Past Paper)"], parent_key: "paper", resource_sequence: 1 },
        { key: "part", type_id: [2, "Question Part"], parent_key: "q1" },
    ].filter((group) => includePart || group.key !== "part").map((group, index) => ({
        resource_id: index + 1,
        resource_sequence: 0,
        label: "",
        title: group.key,
        assigned: 1,
        submitted: 0,
        finalised: 0,
        overdue: 0,
        ...group,
    }));
    const dashboard = Object.create(TeacherDashboard.prototype);
    dashboard.state = {
        submissionGroups: groups,
        hiddenSubmissionTypes: {},
        hiddenSubmissionStates: {},
        expandedSubmissionGroups: { paper: true },
        isStudent: false,
    };
    dashboard._submissionGroupIndex = new Map(groups.map((group) => [group.key, group]));
    dashboard._saveState = () => {};
    return dashboard;
}

function visibleCards(dashboard) {
    return dashboard.visibleSubmissionGroups.map((group) => [group.key, group.depth]);
}

test("enabled papers retain nested questions and the child type override", () => {
    const dashboard = makeDashboard();
    dashboard.state.hiddenSubmissionTypes[1] = true;
    expect(visibleCards(dashboard)).toEqual([["paper", 0], ["q1", 1], ["q2", 1]]);
});

test("hidden papers promote questions even when collapsed without changing source parents", () => {
    const dashboard = makeDashboard();
    dashboard.state.expandedSubmissionGroups.paper = false;
    dashboard.toggleSubmissionType(7);
    expect(visibleCards(dashboard)).toEqual([["q2", 0], ["q1", 0]]);
    for (const group of dashboard.visibleSubmissionGroups) {
        expect(group.parent_key).toBe(false);
        expect(dashboard.submissionGroupAncestors(group)).toEqual([]);
    }
    expect(dashboard.state.submissionGroups[1].parent_key).toBe("paper");

    dashboard.toggleSubmissionType(1);
    expect(visibleCards(dashboard)).toEqual([]);
});

test("promoted question descendants keep their hierarchy without hidden paper ancestors", () => {
    const dashboard = makeDashboard(true);
    dashboard.toggleSubmissionType(7);
    dashboard.state.expandedSubmissionGroups.q1 = true;
    expect(visibleCards(dashboard)).toEqual([["q2", 0], ["q1", 0], ["part", 1]]);
    const part = dashboard.visibleSubmissionGroups.find((group) => group.key === "part");
    expect(dashboard.submissionGroupAncestors(part).map((group) => group.key)).toEqual(["q1"]);
});

test("promoted questions respect submission state filters", () => {
    const dashboard = makeDashboard();
    dashboard.toggleSubmissionType(7);
    dashboard.state.hiddenSubmissionStates = { assigned: true, overdue: true, complete: true };
    dashboard.state.submissionGroups[1].assigned = 0;
    dashboard.state.submissionGroups[1].submitted = 1;
    expect(visibleCards(dashboard)).toEqual([["q2", 0]]);

    dashboard.state.isStudent = true;
    dashboard.state.submissionGroups[1].student_state = "submitted";
    dashboard.state.submissionGroups[2].student_state = "assigned";
    expect(visibleCards(dashboard)).toEqual([["q2", 0]]);
});

test("toggling papers restores their previous expansion state and nesting", () => {
    const dashboard = makeDashboard();
    dashboard.toggleSubmissionType(7);
    dashboard.toggleSubmissionType(7);
    expect(visibleCards(dashboard)).toEqual([["paper", 0], ["q1", 1], ["q2", 1]]);
    dashboard.state.expandedSubmissionGroups.paper = false;
    dashboard.toggleSubmissionType(7);
    dashboard.toggleSubmissionType(7);
    expect(visibleCards(dashboard)).toEqual([["paper", 0]]);
});

test("hidden Exam containers retain their existing hierarchy behavior", () => {
    const dashboard = makeDashboard();
    dashboard.state.submissionGroups[0].type_id = [8, "Exam"];
    dashboard.toggleSubmissionType(8);
    expect(visibleCards(dashboard)).toEqual([["paper", 0], ["q1", 1], ["q2", 1]]);
});

test("name filter keeps non-matching parents of matching children and auto-expands them", () => {
    const dashboard = makeDashboard(true);
    dashboard.state.expandedSubmissionGroups.paper = false;
    dashboard.onChangeSubmissionNameFilter({ target: { value: "ART" } });
    const cards = dashboard.visibleSubmissionGroups;
    expect(cards.map((group) => [group.key, group.depth])).toEqual([
        ["paper", 0],
        ["q1", 1],
        ["part", 2],
    ]);
    expect(cards.map((group) => group.auto_expanded)).toEqual([true, true, false]);

    dashboard.onChangeSubmissionNameFilter({ target: { value: "nomatch" } });
    expect(visibleCards(dashboard)).toEqual([]);
});

test("a matching parent shows its children when expanded", () => {
    const dashboard = makeDashboard(true);
    dashboard.state.submissionGroups[0].title = "Paper 1";
    dashboard.onChangeSubmissionNameFilter({ target: { value: "paper 1" } });
    expect(visibleCards(dashboard)).toEqual([["paper", 0], ["q1", 1], ["q2", 1]]);
    dashboard.state.expandedSubmissionGroups.paper = false;
    expect(visibleCards(dashboard)).toEqual([["paper", 0]]);
});

test("minimum submissions filter counts child submissions and keeps ancestors of busy groups", () => {
    const dashboard = makeDashboard(true);
    const counts = {
        paper: [1, 32],
        q1: [3, 3],
        q2: [25, 0],
        part: [3, 0],
    };
    for (const group of dashboard.state.submissionGroups) {
        [group.total, group.child_count] = counts[group.key];
    }
    dashboard.onChangeMinSubmissions({ target: { value: "20" } });
    expect(visibleCards(dashboard)).toEqual([["paper", 0], ["q2", 1]]);

    dashboard.state.submissionGroups[0].child_count = 0;
    dashboard.state.expandedSubmissionGroups.paper = false;
    expect(visibleCards(dashboard).map(([key]) => key)).toEqual(["paper", "q2"]);
    expect(dashboard.visibleSubmissionGroups[0].auto_expanded).toBe(true);

    dashboard.onChangeMinSubmissions({ target: { value: "" } });
    expect(dashboard.state.minSubmissions).toBe(0);
    expect(visibleCards(dashboard)).toEqual([["paper", 0]]);
});
