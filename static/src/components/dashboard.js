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
            period: 7,
            period_name: "",
            selectedStudent: false,
            students: [],
            isFaculty: true,
            submissions: { value: 0, percentage: 0, period: "" },
            tasks: { value: 0, percentage: 0, period: "" },
            overdue: { value: 0, percentage: 0, period: "" },
            alloverdue: { value: 0, percentage: 0, period: "" },
            next_7_days: { value: 0, percentage: 0, period: "" },
            chartData: [],
            doughnutData: [],
            doughnutData2: [],
            
        });

        onWillStart(async () => {
            // Fetch unique students from submissions, ordered by name
            const submissionStudents = await this.orm.searchRead("aps.resource.submission", [], ["student_id"]);
            const studentIds = [...new Set(submissionStudents.map(s => s.student_id && s.student_id[0]).filter(id => id))];
            this.state.students = await this.orm.searchRead("res.partner", [['id', 'in', studentIds]], ["id", "name"], {order: 'name'});
            // Check if user is faculty
            // const uid = this.user.userId;
            // this.state.isFaculty = await this.user.hasGroup("aps_sis.group_aps_teacher");
            await this.fetchData();
        });
    }

    get selectedPeriodText() {
        const periodMap = {
            0: 'Select Period',
            7: 'Last 7 Days',
            14: 'Last 14 Days',
            30: 'Last 30 Days',
            90: 'Last 90 Days',
            365: 'Last Year'
        };
        return periodMap[this.state.period] || 'Select Period';
    }

    addStudentFilter(domain, field = 'student_id.id') {
        if (this.state.selectedStudent && this.state.selectedStudent !== "false") {
            domain.push([field, '=', this.state.selectedStudent]);
        }
        return domain;
    }

    getPeriodStartDateStr() {
        const today = new Date();
        const startDate = new Date(today.getTime() - this.state.period * 24 * 60 * 60 * 1000);
        return startDate.toISOString().split('T')[0];
    }

    getTodayStr() {
        return new Date().toISOString().split('T')[0];
    }

    getTodayPlus7Str() {
        const today = new Date();
        return new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    }

    getActiveSubmissionsDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()], ['state','=','assigned'],['submission_active', '=', true]]);
    }

    getTotalSubmissionsDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()], ['submission_active', '=', true]]);
    }

    getTaskDomain() {
        return this.addStudentFilter([['create_date', '>=', this.getPeriodStartDateStr()]], 'student_id');
    }

    getOverdueDomain() {
        return this.addStudentFilter([['days_till_due', '<', 0], ['date_due','>=',this.getPeriodStartDateStr()], ['state', 'in', ['assigned']]]);
    }
    getAllOverdueDomain() {
        return this.addStudentFilter([['days_till_due', '<', 0], ['state', 'in', ['assigned']]]);
    }

    getSubmission7DaysDomain() {
        return this.addStudentFilter([['date_assigned', '>', this.getTodayStr()], ['date_assigned', '<=', this.getTodayPlus7Str()]]);
    }

    getAllSubmissionsDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()]]);
    }

    getDoughnutDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()]]);
    }

    async fetchData() {
        // try {
            // Calculate start date based on period
            const startDateStr = this.getPeriodStartDateStr();
            const todayStr = this.getTodayStr();
            const todayPlus7Str = this.getTodayPlus7Str();
            
            this.state.period_name = this.selectedPeriodText;

            // Fetching counts from aps.resource.submission filtered by period
            const submissionDomain = this.getActiveSubmissionsDomain();
            const submissionCount = await this.orm.searchCount("aps.resource.submission", submissionDomain);
            this.state.submissions.value = submissionCount;
            
            // // Fetch active tasks
            // const taskDomain = this.getTaskDomain();
            // const taskCount = await this.orm.searchCount("aps.resource.task", taskDomain);
            // this.state.tasks.value = taskCount;
            
            // Fetch overdue items (submissions past due date and not submitted)
            const overdueDomain = this.getOverdueDomain();
            const overdueCount = await this.orm.searchCount("aps.resource.submission", overdueDomain);
            this.state.overdue.value = overdueCount;
    
            
            // Fetch ALL overdue items (submissions past due date and not submitted)
            const allOverdueCount = await this.orm.searchCount("aps.resource.submission", this.getAllOverdueDomain());
            this.state.alloverdue.value = allOverdueCount;
            
            // Fetch new resources
            const submission7daysDomain = this.getSubmission7DaysDomain();
            const submission7daysCount = await this.orm.searchCount("aps.resource.submission", submission7daysDomain);
            this.state.next_7_days.value = submission7daysCount;
            
            // Fetch chart data: submissions by status per day for the entire period
            const allSubmissionsDomain = this.getAllSubmissionsDomain();
            const allSubmissions = await this.orm.searchRead("aps.resource.submission", allSubmissionsDomain, ["date_assigned", "date_submitted", "date_completed"]);
            
            const chartData = [];
            const dateMap = {};
            const today = new Date();
            const startDate = new Date(today.getTime() - this.state.period * 24 * 60 * 60 * 1000);

            let currentDate = new Date(startDate);
            while (currentDate <= today) {
                const dateStr = currentDate.toISOString().split('T')[0];
                dateMap[dateStr] = { assigned: 0, submitted: 0, finalized: 0 };
                currentDate.setDate(currentDate.getDate() + 1);
            }
            
            allSubmissions.forEach(sub => {
                if (sub.date_assigned && dateMap[sub.date_assigned]) {
                    dateMap[sub.date_assigned].assigned++;
                }
                if (sub.date_submitted && dateMap[sub.date_submitted]) {
                    dateMap[sub.date_submitted].submitted++;
                }
                if (sub.date_completed && dateMap[sub.date_completed]) {
                    dateMap[sub.date_completed].finalized++;
                }
            });
            
            for (const dateStr in dateMap) {
                chartData.push({
                    date: dateStr,
                    assigned: dateMap[dateStr].assigned,
                    submitted: dateMap[dateStr].submitted,
                    finalized: dateMap[dateStr].finalized
                });
            }
            this.state.chartData = chartData;

            const chartDataCummulative = [];
            var assigned = 0;
            var submitted = 0;
            var finalized = 0;

            for (const dateStr in dateMap) {
                assigned += dateMap[dateStr].assigned;
                submitted += dateMap[dateStr].submitted;
                finalized += dateMap[dateStr].finalized;


                chartDataCummulative.push({
                    date: dateStr,
                    assigned: assigned,
                    submitted: submitted,
                    finalized: finalized
                });
            }

            this.state.chartDataCummulative = chartDataCummulative
            
            // Fetch doughnut data: tasks assigned per subject
            const doughnutDomain = this.getDoughnutDomain();
            const submissions = await this.orm.searchRead("aps.resource.submission", doughnutDomain, ["subjects","due_status"]);
            
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
            const due_statusCounts = {};
            const dueStatusDisplay = {
                'late': 'Late',
                'on-time': 'On Time',
                'early': 'Early'
            };
            submissions.forEach(sub => {
                if (sub.subjects && Array.isArray(sub.subjects)) {
                    sub.subjects.forEach(id => {
                        const name = subjectMap[id] || 'Unknown';
                        if (!subjectCounts[id]) {
                            subjectCounts[id] = { data_point: name, __count: 0 };
                        }
                        subjectCounts[id].__count++;
                    });
                }
                if (sub.due_status) {
                    const display = dueStatusDisplay[sub.due_status] || sub.due_status;
                    if (!due_statusCounts[display]) {
                        due_statusCounts[display] = { data_point: display, __count: 0 };
                    }
                    due_statusCounts[display].__count++;
                }
            });
            this.state.doughnutData = Object.values(subjectCounts);
            this.state.doughnutData2 = Object.values(due_statusCounts);
        // } catch (error) {
        //     console.error("Error fetching dashboard data:", error);
        //     // Optionally, set default values or show an error message
        // }
    }

    async onChangePeriod() {
        await this.fetchData();
    }

    async onChangeStudent() {
        await this.fetchData();
    }

    viewActiveSubmissions() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Submissions",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain: this.getActiveSubmissionsDomain(),
        });
    }

    viewTasks() {
        const taskDomain = this.getTaskDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Active Tasks",
            res_model: "aps.resource.task",
            views: [[false, "list"], [false, "form"]],
            domain: taskDomain,
        });
    }

    viewOverdueSubmissions() {
        const overdueDomain = this.getOverdueDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Overdue Submissions",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain: overdueDomain,
        });
    }

    viewAllOverdueSubmissions() {
        const domain = this.getAllOverdueDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Overdue Submissions",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
        });
    }

    viewNext7DaysSubmissions() {
        const domain = this.getSubmission7DaysDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Next 7 Days Submissions",
            res_model: "aps.resource.submission",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
        });
    }
}

ApexDashboard.template = "apex_dashboard.Dashboard";
ApexDashboard.components = { KpiCard, ChartRenderer };

registry.category("actions").add("apex_dashboard_main", ApexDashboard);