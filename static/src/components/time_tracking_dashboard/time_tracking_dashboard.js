import { Component, useState, onWillStart, onMounted, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";

export class TimeTrackingDashboard extends Component {
    static template = "aps_sis.TimeTrackingDashboard";
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

        this.weeklyChartRef = useRef("weeklyChart");
        this.doughnutChartRef = useRef("doughnutChart");
        this.historyChartRef = useRef("historyChart");
        this.studentChartRef = useRef("studentChart");

        this._weeklyChart = null;
        this._doughnutChart = null;
        this._historyChart = null;
        this._studentChart = null;

        this.state = useState({
            loading: true,
            days: 30,
            dateFilter: "30",
            partnerId: "",
            categoryId: "",
            students: [],
            categories: [],
            weeklyComparison: [],
            subjectDoughnut: { labels: [], data: [] },
            studentBar: { labels: [], datasets: [] },
            historyBar: { labels: [], datasets: [] },
        });

        onWillStart(async () => {
            await loadJS("/aps_sis/static/src/lib/chart.js");
            this.state.students = await this.orm.call(
                "aps.time.tracking",
                "get_dashboard_students",
                [],
                {}
            );
            this.state.categories = await this.orm.call(
                "aps.time.tracking",
                "get_dashboard_subject_categories",
                [],
                {}
            );
            await this._fetchData();
        });

        onMounted(() => {
            this._renderCharts();
        });

        onPatched(() => {
            this._renderCharts();
        });
    }

    async _fetchData() {
        this.state.loading = true;
        const data = await this.orm.call(
            "aps.time.tracking",
            "get_dashboard_data",
            [
                parseInt(this.state.days),
                this.state.partnerId ? parseInt(this.state.partnerId) : false,
                this.state.categoryId ? parseInt(this.state.categoryId) : false,
                this.state.dateFilter,
            ],
            {}
        );
        this.state.weeklyComparison = data.weekly_comparison || [];
        this.state.subjectDoughnut = data.subject_doughnut || { labels: [], data: [] };
        this.state.studentBar = data.student_bar || { labels: [], datasets: [] };
        this.state.historyBar = data.history_bar || { labels: [], datasets: [] };
        this.state.loading = false;

        // Destroy old charts so they get re-rendered via onPatched
        this._destroyCharts();
    }

    _destroyCharts() {
        if (this._weeklyChart) { this._weeklyChart.destroy(); this._weeklyChart = null; }
        if (this._doughnutChart) { this._doughnutChart.destroy(); this._doughnutChart = null; }
        if (this._historyChart) { this._historyChart.destroy(); this._historyChart = null; }
        if (this._studentChart) { this._studentChart.destroy(); this._studentChart = null; }
    }

    _renderCharts() {
        if (this.state.loading) return;
        this._renderWeeklyChart();
        this._renderDoughnutChart();
        this._renderHistoryChart();
        this._renderStudentChart();
    }

    _renderWeeklyChart() {
        const el = this.weeklyChartRef.el;
        if (!el) return;
        if (this._weeklyChart) return; // already rendered

        const labels = this.state.weeklyComparison.map(d => d.label);
        const thisWeek = this.state.weeklyComparison.map(d => d.this_week);
        const lastWeek = this.state.weeklyComparison.map(d => d.last_week);

        this._weeklyChart = new Chart(el, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Last Week",
                        data: lastWeek,
                        backgroundColor: "rgba(255, 206, 86, 0.7)",
                        borderColor: "rgba(255, 206, 86, 1)",
                        borderWidth: 1,
                    },
                    {
                        label: "This Week",
                        data: thisWeek,
                        backgroundColor: "rgba(54, 162, 235, 0.7)",
                        borderColor: "rgba(54, 162, 235, 1)",
                        borderWidth: 1,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    title: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} min`,
                        },
                    },
                },
                scales: {
                    y: {
                        title: { display: true, text: "Minutes" },
                        beginAtZero: true,
                    },
                },
            },
        });
    }

    _renderDoughnutChart() {
        const el = this.doughnutChartRef.el;
        if (!el) return;
        if (this._doughnutChart) return;

        const { labels, data, colors } = this.state.subjectDoughnut;
        if (!labels || !labels.length) return;

        const defaultColors = [
            "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0",
            "#9966FF", "#FF9F40", "#C9CBCF", "#E7E9ED",
        ];
        const borderColors = colors && colors.length
            ? colors
            : labels.map((_, i) => defaultColors[i % defaultColors.length]);
        const backgroundColors = borderColors.map(c => c + '80');

        this._doughnutChart = new Chart(el, {
            type: "doughnut",
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: backgroundColors,
                    borderColor: borderColors,
                    borderWidth: 2,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "right" },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.label}: ${ctx.parsed} min`,
                        },
                    },
                },
            },
        });
    }

    _renderHistoryChart() {
        const el = this.historyChartRef.el;
        if (!el) return;
        if (this._historyChart) return;

        const { labels, datasets } = this.state.historyBar;
        if (!labels || !labels.length) return;

        this._historyChart = new Chart(el, {
            type: "bar",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} min`,
                        },
                    },
                },
                scales: {
                    x: { stacked: true },
                    y: {
                        stacked: true,
                        title: { display: true, text: "Minutes" },
                        beginAtZero: true,
                    },
                },
            },
        });
    }

    _renderStudentChart() {
        const el = this.studentChartRef.el;
        if (!el) return;
        if (this._studentChart) return;

        const { labels, datasets } = this.state.studentBar;
        if (!labels || !labels.length) return;

        this._studentChart = new Chart(el, {
            type: "bar",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} min`,
                        },
                    },
                },
                scales: {
                    x: { stacked: true },
                    y: {
                        stacked: true,
                        title: { display: true, text: "Minutes" },
                        beginAtZero: true,
                    },
                },
            },
        });
    }

    async onChangeDays(ev) {
        this.state.dateFilter = ev.target.value;
        if (/^\d+$/.test(ev.target.value)) {
            this.state.days = parseInt(ev.target.value);
        }
        await this._fetchData();
    }

    async onChangeStudent(ev) {
        this.state.partnerId = ev.target.value;
        await this._fetchData();
    }

    async onChangeCategory(ev) {
        this.state.categoryId = ev.target.value;
        await this._fetchData();
    }

    openTimeList() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.time.tracking",
            views: [[false, "list"], [false, "form"]],
            name: "Time Entries",
        });
    }
}

// Register as a client action
registry.category("actions").add("aps_time_tracking_dashboard", TimeTrackingDashboard);
