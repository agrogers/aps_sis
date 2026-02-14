import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { KpiCard } from "./kpi_card/kpi_card";
import { ChartRenderer } from "./chart_renderer/chart_renderer";

export class ApexDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        const savedSettings = this.loadSettings();

        this.state = useState({
            period: savedSettings.period || 7,
            period_name: "",
            selectedStudent: false,
            students: [],
            isFaculty: true,
            submissions: { value: 0, percentage: 0, period: "" },
            tasks: { value: 0, percentage: 0, period: "" },
            overdue: { value: 0, percentage: 0, period: "" },
            alloverdue: { value: 0, percentage: 0, period: "" },
            next_7_days: { value: 0, percentage: 0, period: "" },
            student_points: { value: 0, percentage: 0, period: "" },
            student_rank: { value: 0, total_students: 0, period: "" },
            chartData: [],
            doughnutData: [],
            doughnutData2: [],
            list_view_id: false,
            form_view_id: false,
            // Loading states for progressive loading
            loadingKPIs: true,
            loadingCharts: true,
            loadingDoughnuts: true,
        });

        onWillStart(async () => {
            console.time('Dashboard Setup');

            // Fetch view IDs first (needed for actions)
            console.time('Fetch View IDs');
            await this.fetchViewIds();
            console.timeEnd('Fetch View IDs');

            // Fetch students (needed for dropdown)
            console.time('Fetch Students');
            await this.fetchStudents();
            console.timeEnd('Fetch Students');

            console.timeEnd('Dashboard Setup');
        });

        onMounted(async () => {
            // Load dashboard data after component is rendered
            console.time('Load Dashboard Data');
            await this.loadDashboardData();
            console.timeEnd('Load Dashboard Data');
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
            domain.push([field, '=', parseInt(this.state.selectedStudent, 10)]);
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
        return this.addStudentFilter([['date_due', '>', this.getTodayStr()], ['date_due', '<=', this.getTodayPlus7Str()]]);
    }

    getAllSubmissionsDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()]]);
    }

    getDoughnutDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()]]);
    }
    getStudentPointsDomain() {
        if (this.state.selectedStudent && this.state.selectedStudent !== "false") {
            return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()], 
                ['submission_active', '=', true],
                ['points', '>', 0],
            ]);
        } else {
            return [];
        }
    }

    async calculateStudentRank() {
        if (!this.state.selectedStudent || this.state.selectedStudent === "false") {
            this.state.student_rank.value = "";
            this.state.student_rank.total_students = "";
            return;
        }

        console.time('Calculate Student Rank');

        const periodStart = this.getPeriodStartDateStr();

        const domain = [
            ['date_assigned', '>=', periodStart],
            ['submission_active', '=', true],
            ['points', '>', 0]
        ];

        // Optional: apply student filter if you later want per-student context
        // (but for ranking we need all students, so we don't filter here)

        try {
            // Group by student_id and sum points in one database query
            const groups = await this.orm.readGroup(
                "aps.resource.submission",
                domain,
                ["points:sum"],           // aggregate: sum of points
                ["student_id"],           // group by this field
                { orderby: "points:sum desc" }  // sort descending by total points
            );

            // groups is now an array like:
            // [
            //   { student_id: [42, "John Doe"], points: 850, __count: 12, __domain: [...] },
            //   { student_id: [17, "Jane Smith"], points: 720, __count: 8, ... },
            //   ...
            // ]

            const rankedStudents = groups.map((group, index) => ({
                studentId: group.student_id[0],     // the ID
                totalPoints: group.points || 0,
                rank: index + 1                      // already sorted descending
            }));

            const totalStudentsWithPoints = rankedStudents.length;

            const selectedStudentId = parseInt(this.state.selectedStudent, 10);
            const selectedRankObj = rankedStudents.find(s => s.studentId === selectedStudentId);

            this.state.student_rank.value = selectedRankObj ? selectedRankObj.rank : 0;
            this.state.student_rank.total_students = totalStudentsWithPoints;

            console.timeLog(
                'Calculate Student Rank',
                `Rank: ${this.state.student_rank.value} out of ${totalStudentsWithPoints}`
            );
        } catch (error) {
            console.error("Error calculating student rank:", error);
            this.state.student_rank.value = "Error";
            this.state.student_rank.total_students = "";
        }

        console.timeEnd('Calculate Student Rank');
    }

    async fetchViewIds() {
        console.time('fetchViewIds');
        // Fetch student view IDs - use sudo to bypass access restrictions
        const [data_list] = await this.env.services.orm.searchRead(
            "ir.model.data",
            [["module", "=", "aps_sis"], ["name", "=", "view_aps_resource_submission_list_for_students"]],
            ["res_id"],
            { limit: 1 },
            { sudo: true }
        );
        this.state.list_view_id = data_list ? data_list.res_id : false;

        const [data_form] = await this.env.services.orm.searchRead(
            "ir.model.data",
            [["module", "=", "aps_sis"], ["name", "=", "view_aps_resource_submission_form_for_students"]],
            ["res_id"],
            { limit: 1 },
            { sudo: true }
        );
        this.state.form_view_id = data_form ? data_form.res_id : false;
        console.timeEnd('fetchViewIds');
    }

    async fetchStudents() {
        console.time('fetchStudents');
        // Fetch unique students from submissions, ordered by name
        const submissionStudents = await this.orm.searchRead("aps.resource.submission", [], ["student_id"]);
        const studentIds = [...new Set(submissionStudents.map(s => s.student_id && s.student_id[0]).filter(id => id))];
        this.state.students = await this.orm.searchRead("res.partner", [['id', 'in', studentIds]], ["id", "name"], {order: 'name'});

        // Set selectedStudent after students are loaded
        const savedSettings = this.loadSettings();
        if (savedSettings.selectedStudent) {
            const selectedId = parseInt(savedSettings.selectedStudent, 10);
            const studentExists = this.state.students.some(student => student.id === selectedId);
            if (studentExists) {
                this.state.selectedStudent = selectedId;
            } else {
                this.state.selectedStudent = false;
            }
        } else {
            this.state.selectedStudent = false;
        }

        // Check if user is faculty
        // const uid = this.user.userId;
        // this.state.isFaculty = await this.user.hasGroup("aps_sis.group_aps_teacher");
        console.timeEnd('fetchStudents');
    }

    async loadDashboardData() {
        // Load KPIs first (fastest to load, most important for user)
        await this.fetchKPIs();

        // Then load charts and doughnuts in parallel
        await Promise.all([
            this.fetchChartData(),
            this.fetchDoughnutData()
        ]);
    }

    async fetchKPIs() {
        console.time('Fetch KPIs');
        this.state.loadingKPIs = true;

        const todayStr = this.getTodayStr();
        const todayPlus7Str = this.getTodayPlus7Str();
        this.state.period_name = this.selectedPeriodText;

        // Start all KPI fetches immediately and update UI as they complete
        const kpiPromises = [
            // Active submissions
            this.orm.searchCount("aps.resource.submission", this.getActiveSubmissionsDomain())
                .then(count => {
                    this.state.submissions.value = count;
                    console.timeLog('Fetch KPIs', 'Active submissions loaded');
                }),

            // Overdue items
            this.orm.searchCount("aps.resource.submission", this.getOverdueDomain())
                .then(count => {
                    this.state.overdue.value = count;
                    console.timeLog('Fetch KPIs', 'Overdue items loaded');
                }),

            // All overdue items
            this.orm.searchCount("aps.resource.submission", this.getAllOverdueDomain())
                .then(count => {
                    this.state.alloverdue.value = count;
                    console.timeLog('Fetch KPIs', 'All overdue items loaded');
                }),

            // Next 7 days
            this.orm.searchCount("aps.resource.submission", this.getSubmission7DaysDomain())
                .then(count => {
                    this.state.next_7_days.value = count;
                    console.timeLog('Fetch KPIs', 'Next 7 days loaded');
                }),

            // Student points (sum of points, not count)
            this.orm.searchRead("aps.resource.submission", this.getStudentPointsDomain(), ["points"])
                .then(submissions => {
                    const totalPoints = submissions.reduce((sum, submission) => sum + (submission.points || 0), 0);
                    this.state.student_points.value = totalPoints;
                    console.timeLog('Fetch KPIs', 'Student points loaded');
                })                
        ];

        // Wait for all to complete, but UI updates happen immediately as each finishes
        await Promise.all(kpiPromises);

        // Calculate student rank (needs to run after other KPIs)
        await this.calculateStudentRank();

        this.state.loadingKPIs = false;
        console.timeEnd('Fetch KPIs');
    }

    async fetchChartData() {
        console.time('Fetch Chart Data');
        this.state.loadingCharts = true;

        // Fetch chart data: submissions by status per day for the entire period
        const allSubmissionsDomain = this.getAllSubmissionsDomain();
        const allSubmissions = await this.orm.searchRead("aps.resource.submission", allSubmissionsDomain, ["date_assigned", "date_submitted", "date_completed"]);

        console.time('Process Chart Data');
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

        this.state.chartDataCummulative = chartDataCummulative;
        console.timeEnd('Process Chart Data');

        this.state.loadingCharts = false;
        console.timeEnd('Fetch Chart Data');
    }

    async fetchDoughnutData() {
        console.time('Fetch Doughnut Data');
        this.state.loadingDoughnuts = true;

        // Fetch doughnut data: tasks assigned per subject
        const doughnutDomain = this.getDoughnutDomain();
        const submissions = await this.orm.searchRead("aps.resource.submission", doughnutDomain, ["subjects","due_status"]);

        console.time('Process Doughnut Data');
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
        console.timeEnd('Process Doughnut Data');

        this.state.loadingDoughnuts = false;
        console.timeEnd('Fetch Doughnut Data');
    }

    loadSettings() {
        try {
            const settings = localStorage.getItem('aps_dashboard_settings');
            return settings ? JSON.parse(settings) : {};
        } catch (error) {
            console.warn('Failed to load dashboard settings:', error);
            return {};
        }
    }

    saveSettings() {
        try {
            const settings = {
                period: this.state.period,
                selectedStudent: this.state.selectedStudent
            };
            localStorage.setItem('aps_dashboard_settings', JSON.stringify(settings));
        } catch (error) {
            console.warn('Failed to save dashboard settings:', error);
        }
    }

    async onChangePeriod() {
        this.saveSettings();
        await this.loadDashboardData();
    }

    async onChangeStudent() {
        this.saveSettings();
        await this.loadDashboardData();
    }

    viewActiveSubmissions() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Submissions Assigned in the last " + this.state.period_name,
            res_model: "aps.resource.submission",
            views: [[this.state.list_view_id,"list"], [this.state.form_view_id, "form"]],
            domain: this.getActiveSubmissionsDomain(),
        });
    }

    viewTasks() {
        const taskDomain = this.getTaskDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Active Tasks",
            res_model: "aps.resource.task",
            views: [[this.state.list_view_id,"list"], [this.state.form_view_id, "form"]],
            domain: taskDomain,
        });
    }

    viewOverdueSubmissions() {
        const overdueDomain = this.getOverdueDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Overdue Submissions in the last " + this.state.period_name,
            res_model: "aps.resource.submission",
            views: [[this.state.list_view_id,"list"], [this.state.form_view_id, "form"]],
            domain: overdueDomain,
        });
    }

    viewAllOverdueSubmissions() {
        const domain = this.getAllOverdueDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "All Overdue Submissions",
            res_model: "aps.resource.submission",
            views: [[this.state.list_view_id,"list"], [this.state.form_view_id, "form"]],
            domain: domain,
        });
    }

    viewNext7DaysSubmissions() {
        const domain = this.getSubmission7DaysDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Next 7 Days Submissions",
            res_model: "aps.resource.submission",
            views: [[this.state.list_view_id,"list"], [this.state.form_view_id, "form"]],
            domain: domain,
        });
    }
    viewPointsSubmissions() {
        const domain = this.getStudentPointsDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Student Points Submissions",
            res_model: "aps.resource.submission",
            views: [[this.state.list_view_id,"list"], [this.state.form_view_id, "form"]],
            domain: domain,
        });
    }
}

ApexDashboard.template = "apex_dashboard.Dashboard";
ApexDashboard.components = { KpiCard, ChartRenderer };

registry.category("actions").add("apex_dashboard_main", ApexDashboard);