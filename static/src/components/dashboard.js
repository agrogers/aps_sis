import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { KpiCard } from "./kpi_card/kpi_card";
import { ChartRenderer } from "./chart_renderer/chart_renderer";

export class ApexDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            period: 90,
            selectedStudent: false,
            students: [],
            submissions: { value: 0, percentage: 0 },
            tasks: { value: 0, percentage: 0 },
            overdue: { value: 0, percentage: 0 },
            resources_new: { value: 0, percentage: 0 },
            chartData: [],
            doughnutData: [],
            
        });

        onWillStart(async () => {
            // Fetch unique students from submissions, ordered by name
            const submissionStudents = await this.orm.searchRead("aps.resource.submission", [], ["student_id"]);
            const studentIds = [...new Set(submissionStudents.map(s => s.student_id && s.student_id[0]).filter(id => id))];
            this.state.students = await this.orm.searchRead("res.partner", [['id', 'in', studentIds]], ["id", "name"], {order: 'name'});
            await this.fetchData();
        });
    }

    async fetchData() {
        // Calculate start date based on period
        const today = new Date();
        const startDate = new Date(today.getTime() - this.state.period * 24 * 60 * 60 * 1000);
        const startDateStr = startDate.toISOString().split('T')[0]; // YYYY-MM-DD format
        const todayStr = today.toISOString().split('T')[0];
        
        // Helper to add student filter
        const addStudentFilter = (domain) => {
            if (this.state.selectedStudent && this.state.selectedStudent !== "false") {
                domain.push(['student_id', '=', parseInt(this.state.selectedStudent)]);
            }
            return domain;
        };
        
        // Fetching counts from aps.resource.submission filtered by period
        const submissionDomain = addStudentFilter([['date_assigned', '>=', startDateStr]]);
        const submissionCount = await this.orm.searchCount("aps.resource.submission", submissionDomain);
        this.state.submissions.value = submissionCount;
        
        // Fetch active tasks
        const taskDomain = addStudentFilter([['create_date', '>=', startDateStr]]);
        const taskCount = await this.orm.searchCount("aps.resource.task", taskDomain);
        this.state.tasks.value = taskCount;
        
        // Fetch overdue items (submissions past due date and not submitted)
        const overdueDomain = addStudentFilter([['date_due', '<', todayStr], ['state', 'in', ['assigned']  ]]  );
        const overdueCount = await this.orm.searchCount("aps.resource.submission", overdueDomain);
        this.state.overdue.value = overdueCount;
        
        // Fetch new resources
        const resourceDomain = [['create_date', '>=', startDateStr]];
        const resourceCount = await this.orm.searchCount("aps.resources", resourceDomain);
        this.state.resources_new.value = resourceCount;
        
        // Fetch chart data: submissions per day
        const chartDomain = addStudentFilter([['date_submitted', '>=', startDateStr]]);
        this.state.chartData = await this.orm.readGroup(
            "aps.resource.submission", 
            chartDomain, ['date_submitted'], ['date_submitted:day'], {orderby: 'date_submitted'});
        
        // Fetch doughnut data: tasks assigned per subject
        const doughnutDomain = addStudentFilter([['date_assigned', '>=', startDateStr]]);
        const submissions = await this.orm.searchRead("aps.resource.submission", doughnutDomain, ["subjects"]);
        
        const subjectIds = new Set();
        submissions.forEach(sub => {
            if (sub.subjects && Array.isArray(sub.subjects)) {
                sub.subjects.forEach(id => subjectIds.add(id));
            }
        });
        
        const subjectRecords = await this.orm.searchRead("op.subject", [['id', 'in', Array.from(subjectIds)]], ["id", "name"]);
        const subjectMap = {};
        subjectRecords.forEach(rec => subjectMap[rec.id] = rec.name);
        
        const subjectCounts = {};
        submissions.forEach(sub => {
            if (sub.subjects && Array.isArray(sub.subjects)) {
                sub.subjects.forEach(id => {
                    const name = subjectMap[id] || 'Unknown';
                    if (!subjectCounts[id]) {
                        subjectCounts[id] = { subject: name, __count: 0 };
                    }
                    subjectCounts[id].__count++;
                });
            }
        });
        this.state.doughnutData = Object.values(subjectCounts);
        
        // Logic for percentage calculation would go here [cite: 331, 332]
    }

    async onChangePeriod() {
        await this.fetchData();
    }

    async onChangeStudent() {
        await this.fetchData();
    }

    viewSubmissions() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Submissions",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
        });
    }
}

ApexDashboard.template = "apex_dashboard.Dashboard";
ApexDashboard.components = { KpiCard, ChartRenderer };

registry.category("actions").add("apex_dashboard_main", ApexDashboard);