import { Component, useState, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { KpiCard } from "./kpi_card/kpi_card";
import { KpiGauge } from "./kpi_gauge/kpi_gauge";
import { ChartRenderer } from "./chart_renderer/chart_renderer";
import { Domain } from "@web/core/domain";
import { ProgressCharts } from "./progress_charts";


export class ApexDashboard extends Component {
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
        
        const savedSettings = this.loadSettings();

        this.state = useState({
            period: parseInt(savedSettings.period) || 7,
            period_name: "",
            selectedStudent: false,
            students: [],
            isFaculty: true,
            submissions: { value: 0, percentage: 0, period: "" },
            tasks: { value: 0, percentage: 0, period: "" },
            overdue: {  value: 0, percentage: 0, period: "" },
            alloverdue: {  value: 0, percentage: 0, period: "" },
            next_7_days: { value: 0, percentage: 0, period: "" },
            student_points: {value: 0, percentage: 0, period: "", max: 0  },
            student_rank: { value: 0, total_students: 0, period: "", points_from_next: 0, max: 0 },
            submitted_today: { value: 0, percentage: 0, period: "", submitted_yesterday: 0 },
            points_from_next: 0,
            rank_description: "",
            total_submitted: { value: 0, percentage: 0, period: "" },
            chartData: [],
            doughnutData: [],
            doughnutData2: {},
            list_view_id: false,
            form_view_id: false,
            kanban_view_id: false,
            // Loading states for progressive loading
            loadingKPIs: true,
            loadingCharts: true,
            loadingDoughnuts: true,
            confettiReady: false,  // we'll use this to know when canvas is set up
            // Progress tracking
            progressLineData: [],
            progressBarData: [],
            loadingProgress: true,
            periodStart: null,  // For zoom reference
            periodEnd: null,
            paceData: {},  // Store PACE data for all resources
            paceForToday: 0,  // Current PACE percentage for today
            // Student comparison
            studentComparisonData: null,
            loadingStudentComparison: true,
        });

        
        this.confetti = null;  // will hold the confetti.create() function

        // Initialize progress charts module
        this.progressCharts = new ProgressCharts(this);

        onWillStart(async () => {
            // Fetch view IDs first (needed for actions)
            await this.fetchViewIds();

            // Fetch students (needed for dropdown)
            await this.fetchStudents();
        });

        onMounted(async () => {
            // Load dashboard data after component is rendered
            this.initializeConfettiCanvas();
            await this.loadDashboardData();
        });
        
        onPatched(() => {
            // Only render charts if they don't exist yet and data is available
            // Avoid constant re-renders which break legend click functionality
            this.progressCharts.renderIfNeeded();
        });
    }

    get selectedPeriodText() {
        const periodMap = {
            0: 'Select Period',
            7: 'Last 7 Days',
            14: 'Last 14 Days',
            30: 'Last 30 Days',
            90: 'Last 90 Days',
            180: 'Last 6 months',
            270: 'Last 9 months',
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
        // If no period selected, return today's date
        if (this.state.period === 0) {
            return this.getTodayStr();
        }
        
        const today = new Date();
        const startDate = new Date(today.getTime() - this.state.period * 24 * 60 * 60 * 1000);
        
        // Ensure the date is valid
        if (isNaN(startDate.getTime())) {
            console.error('Invalid date calculated for period:', this.state.period);
            return this.getTodayStr();
        }
        
        return startDate.toISOString().split('T')[0];
    }

    getTodayStr() {
        return new Date().toISOString().split('T')[0];
    }

    getTodayPlus7Str() {
        const today = new Date();
        return new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    }

    getSubmittedTodayDomain() {
        const today = new Date();
        const todayStr = today.toISOString().split('T')[0];
        return this.addStudentFilter([['date_submitted', '=', todayStr], ['submission_active', '=', true]]);
    }

    getSubmittedYesterdayDomain() {
        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayStr = yesterday.toISOString().split('T')[0];
        return this.addStudentFilter([['date_submitted', '=', yesterdayStr], ['submission_active', '=', true]]);
    }

    getTotalSubmittedDomain(options = {}) {
        const includeState = options.includeState ?? true;
        const includePeriod = options.includePeriod ?? true;
        let domain =[];
        domain = this.addStudentFilter(domain); 
        domain.push(['submission_active', '=', true]);
        if (includePeriod) {
            domain.push(['date_submitted', '>=', this.getPeriodStartDateStr()]);
        }
        if (includeState) {
            domain.push(['state', 'in', ['submitted', 'complete']]);
        }

        return domain;
    }

    // Generic Data Domain Builder - can be used for multiple KPIs and views by toggling state and period filters
    getDataDomain(options = {}) {
        const incStudentFilter = options.incStudentFilter ?? true;
        const incSubmissionActive = options.incSubmissionActive ?? true;
        const incState = options.incState ?? false;
        const incPeriodSubmitted = options.incPeriodSubmitted ?? false;
        const incPeriodAssigned = options.incPeriodAssigned ?? false;
        const excludeSubmissionNameLike = options.excludeSubmissionNameLike ?? false; // can be string or array of strings
        let domain =[];
        if (incStudentFilter) {domain = this.addStudentFilter(domain); }
        if (incSubmissionActive) {domain.push(['submission_active', '=', true]);}
        if (incPeriodSubmitted) {domain.push(['date_submitted', '>=', this.getPeriodStartDateStr()]);}
        if (incPeriodAssigned) {domain.push(['date_assigned', '>=', this.getPeriodStartDateStr()]);}
        if (incState) {domain.push(['state', 'in', incState]);}  // eg ['submitted', 'complete']
        if (excludeSubmissionNameLike) {
            const namesToExclude = Array.isArray(excludeSubmissionNameLike) ? excludeSubmissionNameLike : [excludeSubmissionNameLike];
            namesToExclude.forEach(name => {
                domain.push(['submission_name', 'not ilike', name]);
            });
        }

        return domain;
    }

    getActiveSubmissionsDomain(inludeSubmissionActive = true) {
        // Parameter is needed because when we open the list view we want to pass in a filter context, not a domain, and the filter context will handle the submission_active part
        let domain = this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()], ['submission_active', '=', true]]);
        if (inludeSubmissionActive) {
            domain.push(['state','=','assigned']);
        }
        return domain;
    }

    getTotalSubmissionsDomain() {
        return this.addStudentFilter([['date_assigned', '>=', this.getPeriodStartDateStr()], ['submission_active', '=', true]]);
    }

    getTaskDomain() {
        return this.addStudentFilter([['create_date', '>=', this.getPeriodStartDateStr()]], 'student_id');
    }

    getOverdueDomain(includePeriod = true, includeState = true) {
        let domain =[];
        domain = this.addStudentFilter(domain);
        domain.push(['date_due','<',this.getTodayStr()]);
        if (includeState) {
            domain.push(['state', 'in', ['assigned']]);
        }
        if (includePeriod) {
            domain.push(['date_due','>=',this.getPeriodStartDateStr()]);
        }
        
        return domain;
    }

    getOldOverdueDomain() {
        return this.addStudentFilter([['date_due','>=',this.getPeriodStartDateStr()], ['state', 'in', ['assigned']]]);
    }
    getAllOverdueDomain() {
        return this.addStudentFilter([ ['state', 'in', ['assigned']]]);
    }

    getSubmission7DaysDomain(options = {}) {
        const includeDateDue = options.includeDateDue ?? true;
        const includeState = options.includeState ?? true;

        let domain = this.addStudentFilter([]);
        domain.push(['submission_active', '=', true]);
        if (includeDateDue) {
            domain.push(['date_due', '>', this.getTodayStr()], ['date_due', '<=', this.getTodayPlus7Str()]);
        }
        if (includeState) {
            domain.push(['state', 'in', ['assigned']]);
        }
        return domain;
    }

    getAllSubmissionsDomain() {
        let domain = this.addStudentFilter([]);
        domain.push(['submission_active', '=', true]);
        domain.push(['date_assigned', '>=', this.getPeriodStartDateStr()]);
        return domain;
    }


    getDoughnutDomain() {
        let domain = this.addStudentFilter([]);
        domain.push(['submission_active', '=', true]);
        domain.push(['date_assigned', '>=', this.getPeriodStartDateStr()]);
        domain.push(['submission_name', 'not ilike', ' Progress']);

        return domain;
    }
    getStudentPointsDomain() {
        let domain = this.addStudentFilter([]);
        domain.push(['submission_active', '=', true]);
        domain.push(['points', '>', 0]);
        domain.push(['date_assigned', '>=', this.getPeriodStartDateStr()]);
        return domain;
    }

    initializeConfettiCanvas() {
     // Create full-window canvas
        const canvas = document.createElement('canvas');
        canvas.style.position = 'fixed';
        canvas.style.inset = '0';
        canvas.style.pointerEvents = 'none';
        canvas.style.zIndex = '9999';           // high z-index so it's on top
        document.body.appendChild(canvas);

        // Create confetti instance (no worker to avoid transfer error)
        this.confetti = confetti.create(canvas, {
            resize: true,
            useWorker: false
        });

        // Handle resize
        const resize = () => {
            canvas.width = window.innerWidth * window.devicePixelRatio;
            canvas.height = window.innerHeight * window.devicePixelRatio;
            const ctx = canvas.getContext('2d');
            if (ctx) ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        };

        resize();
        window.addEventListener('resize', resize);

        this.state.confettiReady = true;
        console.log("Full-page confetti canvas initialized");
    }

    resizeCanvas(canvas, container) {
        const rect = container.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;

        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;

        const ctx = canvas.getContext('2d');
        if (ctx) {
            ctx.scale(dpr, dpr);
        }
    }
    async calculateStudentRank() {
        function randomInRange(min, max) {
            return Math.random() * (max - min) + min;
            }

        if (!this.state.selectedStudent || this.state.selectedStudent === "false") {
            this.state.student_rank.value = "";
            this.state.student_rank.total_students = "";
            this.state.student_rank.points_from_next = 0;
            this.state.rank_description = "";
            return;
        }

        const periodStart = this.getPeriodStartDateStr();

        const domain = [
            ['date_assigned', '>=', periodStart],
            ['submission_active', '=', true],
            ['points', '>', 0]
        ];

        try {
            const groups = await this.orm.call(
                "aps.resource.submission",
                "read_group_points_by_student",
                [domain],
                {
                    orderby: "points:sum desc", // kwargs
                    // You can add lazy: true, offset: 0, limit: null, etc. if needed
                },
            );

            if (!groups.length) {
                this.state.student_rank.value = 0;
                this.state.student_rank.total_students = 0;
                this.state.student_rank.points_from_next = 0;
                this.state.rank_description = "";
                return;
            }

            // Build ranked list with proper dense ranking
            const rankedStudents = [];
            let currentRank = 1;
            let previousPoints = null;
            let position = 1;  // actual placement (used for skipping)

            groups.forEach((group, index) => {
                const currentPoints = group.points || 0;
                const studentId = group.student_id[0];

                // If points are the same as previous, keep the same rank
                if (index > 0 && currentPoints === previousPoints) {
                    // same rank as last one
                } else {
                    // new rank = current position
                    currentRank = position;
                }

                rankedStudents.push({
                    studentId,
                    totalPoints: currentPoints,
                    rank: currentRank,
                    pointsFromNextPlace: 0  // we'll calculate later
                });

                previousPoints = currentPoints;
                position++;
            });


            this.state.student_rank.max = currentRank;  // top score in the period
            this.state.student_points.max = rankedStudents[0].totalPoints;  // top score in the period
            const totalStudentsWithPoints = rankedStudents.length;

            // Find selected student
            const selectedStudentId = parseInt(this.state.selectedStudent, 10);
            const selectedRankObj = rankedStudents.find(s => s.studentId === selectedStudentId);

            let newRank = selectedRankObj ? selectedRankObj.rank : 0;

            // Calculate points to next place (difference to next different score)
            
            let pointsFromNext = 0;
            if (selectedRankObj) {
                const currentIndex = rankedStudents.findIndex(s => s.studentId === selectedStudentId);
                // Find the next student with fewer points
                let lastPts = rankedStudents[0].totalPoints;  // default to top points if not found 
                let groupPoints = [lastPts];
                for (let i = 0; i < rankedStudents.length; i++) {
                    let curPts = rankedStudents[i].totalPoints;
                    if (lastPts !== curPts) {
                        rankedStudents[i].pointsFromNextPlace = lastPts - curPts;  // I dont need to do all of these
                    }
                    if (rankedStudents[i].studentId === selectedStudentId) {
                        pointsFromNext = rankedStudents[i].pointsFromNextPlace;
                    }
                    if (lastPts != curPts) {
                        groupPoints.push(curPts);
                        lastPts = curPts;                               
                    }
                }

                if (groupPoints.length > 1) { // Need to handle first place differently
                    pointsFromNext = groupPoints[0] - groupPoints[1];  // difference between top score and next different score
                };
            } else {
                newRank = "-";
                pointsFromNext = "-";
            };

            // Update state
            this.state.student_rank.value = newRank;
            this.state.student_rank.total_students = totalStudentsWithPoints;
            this.state.student_rank.points_from_next = pointsFromNext;

            // Nice message
            if (newRank === 1) {
                if (pointsFromNext > 0) {
                    this.state.rank_description = `${pointsFromNext} points ahead of 2nd place`;
                } else {
                    this.state.rank_description = "Tied for 1st place";
                }
            } else if (newRank > 1 && pointsFromNext > 0) {
                this.state.rank_description = `${pointsFromNext} points from next place`;
            } else if (newRank > 1 && pointsFromNext === 0) {
                this.state.rank_description = "Tied with next place";
            } else {
                this.state.rank_description = "";
            }

            // Confetti for top 3 ranks (you can adjust duration/particle count)
            if (newRank >= 1 && newRank <= 3 && this.state.confettiReady && this.confetti ) {
                const duration = newRank === 1 ? 1500 : newRank === 2 ? 1000 : 500;
                const end = Date.now() + duration;
                const colors = ['#c700bd', '#ffffff', '#ff0000', '#63008a', '#ffff00'];
                const confettitSettings = {
                        particleCount: newRank === 1 ? 5 : newRank === 2 ? 3 : 2,
                        angle: 60,
                        spread: 55,
                        startVelocity: 35,
                        decay: 0.9,
                        gravity: randomInRange(0.4, 0.6),
                        drift: randomInRange(-0.4, 0.4),
                        origin: { x: 0 },
                        colors: colors
                    };
                let confettitSettings2 = { ...confettitSettings }; // Create a copy
                confettitSettings2.origin = { x: 1 }; // alternate sides
                // confettitSettings2.angle = 120; 

                (function frame() {
                    confetti(confettitSettings);
                    confetti(confettitSettings2);

                    if (Date.now() < end) {
                        requestAnimationFrame(frame);
                    }
                })();

                this.state.confettiTriggered = true;
                console.log(`Rank #${newRank} confetti triggered for ${duration}ms`);
            }


        } catch (error) {
            console.error("Error calculating student rank:", error);
            this.state.student_rank.value = "Error";
            this.state.student_rank.total_students = "";
            this.state.student_rank.points_from_next = 0;
            this.state.rank_description = "";
        }
    }


    async fetchViewIds() {
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

        const [data_kanban] = await this.env.services.orm.searchRead(
            "ir.model.data",
            [["module", "=", "aps_sis"], ["name", "=", "view_aps_resource_submission_kanban"]],
            ["res_id"],
            { limit: 1 },
            { sudo: true }
        );
        this.state.kanban_view_id = data_kanban ? data_kanban.res_id : false;
    }

    async fetchStudents() {
        // Fetch unique students from submissions, ordered by name
        const submissionStudents = await this.orm.searchRead("aps.resource.submission", [], ["student_id"]);
        const studentIds = [...new Set(submissionStudents.map(s => s.student_id && s.student_id[0]).filter(id => id))];
        this.state.students = await this.orm.searchRead("res.partner", [['id', 'in', studentIds]], ["id", "name"], {order: 'name'});

        // If only one student, automatically select it
        if (this.state.students.length === 1) {
            this.state.selectedStudent = this.state.students[0].id;
        } else {
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
        }

        // Check if user is faculty
        try {
            const isTeacher = await this.orm.call(
                "aps.resource.submission",
                "get_current_user_is_teacher",
                []
            );
            console.log("Teacher check result:", isTeacher);
            this.state.isFaculty = isTeacher;
            console.log("isFaculty state set to:", this.state.isFaculty);
        } catch (error) {
            console.error("Could not check user group, defaulting to student view", error);
            this.state.isFaculty = false;
        }
    }

    async loadDashboardData() {
        // Don't load data if no period is selected
        if (this.state.period === 0) {
            console.log('Skipping dashboard data load - no period selected');
            return;
        }

        // Load KPIs first (fastest to load, most important for user)
        await this.fetchKPIs();

        // Then load charts, doughnuts, and progress data in parallel
        await Promise.all([
            this.fetchChartData(),
            this.fetchDoughnutData(),
            this.progressCharts.fetchProgressData(),
            this.progressCharts.fetchStudentComparisonData()
        ]);

        // Now that KPIs are loaded → the rank card should exist
        this.initializeConfettiCanvas();        
    }

    async fetchKPIs() {
        this.state.loadingKPIs = true;

        const todayStr = this.getTodayStr();
        const todayPlus7Str = this.getTodayPlus7Str();
        this.state.period_name = this.selectedPeriodText;

        // Start all KPI fetches immediately and update UI as they complete
        const kpiPromises = [
            // Student points (sum of points, not count)
            this.orm.searchRead("aps.resource.submission", this.getStudentPointsDomain(), ["points"])
                .then(submissions => {
                    const totalPoints = submissions.reduce((sum, submission) => sum + (submission.points || 0), 0);
                    this.state.student_points.value = totalPoints;
                }),
                
            // Overdue items
            this.orm.searchCount("aps.resource.submission", this.getOverdueDomain())
                .then(count => {
                    this.state.overdue.value = count;
                }),

            // All overdue items
            this.orm.searchCount("aps.resource.submission", this.getOverdueDomain(false,true))
                .then(count => {
                    this.state.alloverdue.value = count;
                }),

            // Active submissions
            this.orm.searchCount("aps.resource.submission", this.getActiveSubmissionsDomain())
                .then(count => {
                    this.state.submissions.value = count;
                }),

            // Next 7 days
            this.orm.searchCount("aps.resource.submission", this.getSubmission7DaysDomain())
                .then(count => {
                    this.state.next_7_days.value = count;
                }),

            // Total Submitted
            this.orm.searchCount("aps.resource.submission", this.getDataDomain({'incPeriodSubmitted': true}))
                .then(count => {
                    this.state.total_submitted.value = count;
                }),

            // Submitted today
            this.orm.searchCount("aps.resource.submission", this.getSubmittedTodayDomain())
                .then(count => {
                    this.state.submitted_today.value = count;
                }),

            // Submitted yesterday
            this.orm.searchCount("aps.resource.submission", this.getSubmittedYesterdayDomain())
                .then(count => {
                    this.state.submitted_today.submitted_yesterday = count;
                }),
        ];

        // Wait for all to complete, but UI updates happen immediately as each finishes
        await Promise.all(kpiPromises);

        // Calculate student rank (needs to run after other KPIs)
        await this.calculateStudentRank();

        this.state.loadingKPIs = false;
    }

    async fetchChartData() {
        this.state.loadingCharts = true;

        // Fetch chart data: submissions by status per day for the entire period
        // const allSubmissionsDomain = this.getAllSubmissionsDomain();
        // const allSubmissions = await this.orm.searchRead("aps.resource.submission", allSubmissionsDomain, ["date_assigned", "date_submitted", "date_completed"]);

        const submittedDomain = this.getDataDomain({ incPeriodSubmitted: true, incState: ['submitted','complete'] });
        const assignedDomain = this.getDataDomain({ incPeriodAssigned: true});

        // console.log("Submitted domain:", JSON.stringify(submittedDomain));
        // console.log("Assigned domain:", JSON.stringify(assignedDomain));

        const dataDomain = Domain.or([submittedDomain, assignedDomain]).toList();
        // console.log("Combined OR:", JSON.stringify(dataDomain));

        const allSubmissions = await this.orm.searchRead("aps.resource.submission", dataDomain, ["date_assigned", "date_submitted", "date_completed"]);

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

        // Submissions over time //
        const chartDataCummulative = [];
        var assigned = 0;
        var submitted = 0;

        for (const dateStr in dateMap) {
            assigned += dateMap[dateStr].assigned;
            submitted += dateMap[dateStr].submitted;
            // finalized += dateMap[dateStr].finalized;

            chartDataCummulative.push({
                date: dateStr,
                assigned: assigned,
                submitted_finalized: submitted,  // combine submitted and finalized for a clearer chart (and because finalized is a subset of submitted)
            });
        }

        this.state.chartDataCummulative = chartDataCummulative;

        this.state.loadingCharts = false;
    }

    async fetchDoughnutData() {
        this.state.loadingDoughnuts = true;

        // Fetch doughnut data: tasks assigned per subject
        const doughnutDomain = this.getDoughnutDomain();
        const submissions = await this.orm.searchRead("aps.resource.submission", doughnutDomain, ["subjects","due_status"]);

        const subjectIds = new Set();
        submissions.forEach(sub => {
            if (sub.subjects && Array.isArray(sub.subjects)) {
                sub.subjects.forEach(id => subjectIds.add(id));
            }
        });

        const subjectRecords = await this.orm.searchRead("op.subject", [['id', 'in', Array.from(subjectIds)]], ["id", "name", "category_id"]);
        const subjectMap = {};
        subjectRecords.forEach(rec => {
            subjectMap[rec.id] = {
                name: rec.name,
                category: rec.category_id ? rec.category_id[1] : 'No Category'
            };
        });

        // Tasks by Subject
        const subjectCounts = {};
        submissions.forEach(sub => {
            if (sub.subjects && Array.isArray(sub.subjects)) {
                sub.subjects.forEach(id => {
                    const subjectInfo = subjectMap[id];
                    if (subjectInfo) {
                        const categoryName = subjectInfo.category !== 'No Category' ? subjectInfo.category : subjectInfo.name;
                        if (!subjectCounts[categoryName]) {
                            subjectCounts[categoryName] = { data_point: categoryName, __count: 0 };
                        }
                        subjectCounts[categoryName].__count++;
                    }
                });
            }
        });
        this.state.doughnutData = Object.values(subjectCounts);

        // Tasks by Due Status (outer ring: student, inner ring: class average)
        const dueStatusDisplay = {
            'late': 'Late',
            'on-time': 'On Time',
            'early': 'Early'
        };
        const dueStatusLabels = ['Late', 'On Time', 'Early'];
        const dueStatusColors = {
            'Late': 'rgba(220, 53, 69, 1)',
            'On Time': 'rgba(150, 157, 163, 1)',
            'Early': 'rgba(40, 167, 69, 1)',
        };
        const dueStatusColorsHalf = {
            'Late': 'rgba(220, 53, 69, 0.5)',
            'On Time': 'rgba(150, 157, 163, 0.5)',
            'Early': 'rgba(40, 167, 69, 0.5)',
        };

        // Student counts (outer ring)
        const due_statusCounts = {};
        submissions.forEach(sub => {
            if (sub.due_status) {
                const display = dueStatusDisplay[sub.due_status] || sub.due_status;
                due_statusCounts[display] = (due_statusCounts[display] || 0) + 1;
            }
        });

        // Class average counts (inner ring) - fetch all students' data without student filter
        const classDomain = this.getDataDomain(
            {'incStudentFilter': false, 'incPeriodAssigned': true, 'excludeSubmissionNameLike':[' Progress']});

        const classSubmissions = await this.orm.call(
            "aps.resource.submission",
            "read_submission_data",
            [classDomain, ["due_status", "student_id"]],
        );

        const classStudentIds = new Set();
        const classDueStatusCounts = {};
        classSubmissions.forEach(sub => {
            if (sub.student_id) classStudentIds.add(sub.student_id[0]);
            if (sub.due_status) {
                const display = dueStatusDisplay[sub.due_status] || sub.due_status;
                classDueStatusCounts[display] = (classDueStatusCounts[display] || 0) + 1;
            }
        });
        const numStudents = Math.max(classStudentIds.size, 1);

        // Build multi-dataset doughnut config
        const outerData = dueStatusLabels.map(label => due_statusCounts[label] || 0);
        const innerData = dueStatusLabels.map(label => Math.round(((classDueStatusCounts[label] || 0) / numStudents) * 10) / 10);
        const outerColors = dueStatusLabels.map(label => dueStatusColors[label]);
        const innerColors = dueStatusLabels.map(label => dueStatusColorsHalf[label]);

        this.state.doughnutData2 = {
            labels: dueStatusLabels,
            datasets: [
                {
                    label: 'Student',
                    data: outerData,
                    backgroundColor: outerColors,
                    borderWidth: 1,
                    hoverOffset: 4,
                },
                {
                    label: 'Spacer',
                    data: [1],
                    backgroundColor: ['rgba(255,255,255,0)'],
                    borderWidth: 0,
                    hoverOffset: 0,
                    weight: 0.3,
                },
                {
                    label: 'Class Avg',
                    data: innerData,
                    backgroundColor: innerColors,
                    borderWidth: 1,
                    hoverOffset: 4,
                }
            ]
        };

        this.state.loadingDoughnuts = false;
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

    getResponsiveViews() {
        const isSmallScreen = window.innerWidth < 768;
        return isSmallScreen
            ? [[this.state.kanban_view_id, "kanban"], [this.state.list_view_id, "list"], [this.state.form_view_id, "form"]]
            : [[this.state.list_view_id, "list"], [this.state.form_view_id, "form"], [this.state.kanban_view_id, "kanban"]];
    }

    viewActiveSubmissions() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.state.period_name,
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: this.getActiveSubmissionsDomain(false),
            context: {
                search_default_assigned: 1,
            },            
        });
    }

    viewTasks() {
        const taskDomain = this.getTaskDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Active Tasks",
            res_model: "aps.resource.task",
            views: this.getResponsiveViews(),
            domain: taskDomain,
        });
    }

    viewTotalSubmitted() {
        const totalSubmittedDomain = this.getTotalSubmittedDomain({ includeState: false, includePeriod: true });
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.state.period_name,
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: totalSubmittedDomain,
            context: {
                search_default_submitted: 1,
                search_default_completed: 1,
            },              
        });
    }

    viewOverdueSubmissions() {
        const overdueDomain = this.getOverdueDomain(true,false); // Only show overdue items, ignore period and state (assigned or not);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.state.period_name,
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: overdueDomain,
            context: {
                search_default_overdue: 1,
            },            
        });
    }

    viewAllOverdueSubmissions() {
        const domain = this.getOverdueDomain(false, false); // Only show overdue items, ignore period and state (assigned or not);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "",
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: domain,
            context: {
                search_default_overdue: 1,
            },               
        });
    }

    viewNext7DaysSubmissions() {
        const domain = this.getSubmission7DaysDomain({includeDateDue: false, includeState: false}); // Show all items due in the next 7 days, regardless of assigned state
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Coming Due in the next 7 Days",
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: domain,
            context: {
                search_default_due_next_7_days: 1,
                search_default_assigned: 1,
            }
        });
    }
    viewPointsSubmissions() {
        const domain = this.getStudentPointsDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Student Points Submissions",
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: domain,
        });
    }
    viewTodaySubmissions() {
        const domain = this.getSubmittedTodayDomain();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Today's Submissions",
            res_model: "aps.resource.submission",
            views: this.getResponsiveViews(),
            domain: domain,
        });
    }

}

ApexDashboard.template = "apex_dashboard.Dashboard";
ApexDashboard.components = { KpiCard, KpiGauge, ChartRenderer };

registry.category("actions").add("apex_dashboard_main", ApexDashboard);
