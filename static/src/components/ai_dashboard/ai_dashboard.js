import { Component, onMounted, onPatched, onWillStart, useRef, useState } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AIDashboard extends Component {
    static template = "aps_sis.AIDashboard";
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
        this.modelChartRef = useRef("modelChart");
        this.providerChartRef = useRef("providerChart");
        this.dailyChartRef = useRef("dailyChart");
        this._modelChart = null;
        this._providerChart = null;
        this._dailyChart = null;
        this.state = useState({
            loading: true,
            days: 30,
            summary: {},
            modelUsage: { labels: [], counts: [], costs: [] },
            providerCost: { labels: [], costs: [] },
            dailyTrend: { labels: [], counts: [], costs: [] },
            modelStats: [],
        });

        onWillStart(async () => {
            await loadJS("/aps_sis/static/src/lib/chart.js");
            await this.fetchData();
        });

        onMounted(() => this.renderCharts());
        onPatched(() => this.renderCharts());
    }

    async fetchData() {
        this.state.loading = true;
        const data = await this.orm.call("aps.ai.call.log", "get_dashboard_data", [parseInt(this.state.days, 10)], {});
        this.state.summary = data.summary || {};
        this.state.modelUsage = data.model_usage || { labels: [], counts: [], costs: [] };
        this.state.providerCost = data.provider_cost || { labels: [], costs: [] };
        this.state.dailyTrend = data.daily_trend || { labels: [], counts: [], costs: [] };
        this.state.modelStats = data.model_stats || [];
        this.state.loading = false;
        this.destroyCharts();
    }

    destroyCharts() {
        if (this._modelChart) {
            this._modelChart.destroy();
            this._modelChart = null;
        }
        if (this._providerChart) {
            this._providerChart.destroy();
            this._providerChart = null;
        }
        if (this._dailyChart) {
            this._dailyChart.destroy();
            this._dailyChart = null;
        }
    }

    renderCharts() {
        if (this.state.loading) {
            return;
        }
        this.renderModelChart();
        this.renderProviderChart();
        this.renderDailyChart();
    }

    renderModelChart() {
        const element = this.modelChartRef.el;
        if (!element || this._modelChart || !this.state.modelUsage.labels.length) {
            return;
        }
        this._modelChart = new Chart(element, {
            type: "bar",
            data: {
                labels: this.state.modelUsage.labels,
                datasets: [
                    {
                        label: "Queries",
                        data: this.state.modelUsage.counts,
                        backgroundColor: "rgba(30, 136, 229, 0.75)",
                        borderColor: "rgba(30, 136, 229, 1)",
                        borderWidth: 1,
                        yAxisID: "y",
                    },
                    {
                        label: "Cost",
                        data: this.state.modelUsage.costs,
                        type: "line",
                        borderColor: "rgba(67, 160, 71, 1)",
                        backgroundColor: "rgba(67, 160, 71, 0.2)",
                        borderWidth: 2,
                        tension: 0.3,
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Queries" } },
                    y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Cost" } },
                },
            },
        });
    }

    renderProviderChart() {
        const element = this.providerChartRef.el;
        if (!element || this._providerChart || !this.state.providerCost.labels.length) {
            return;
        }
        const palette = ["#0f766e", "#2563eb", "#ea580c", "#7c3aed", "#0891b2", "#65a30d", "#dc2626", "#d97706"];
        this._providerChart = new Chart(element, {
            type: "doughnut",
            data: {
                labels: this.state.providerCost.labels,
                datasets: [{
                    data: this.state.providerCost.costs,
                    backgroundColor: this.state.providerCost.labels.map((_, index) => palette[index % palette.length] + "B3"),
                    borderColor: this.state.providerCost.labels.map((_, index) => palette[index % palette.length]),
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        });
    }

    renderDailyChart() {
        const element = this.dailyChartRef.el;
        if (!element || this._dailyChart || !this.state.dailyTrend.labels.length) {
            return;
        }
        this._dailyChart = new Chart(element, {
            type: "line",
            data: {
                labels: this.state.dailyTrend.labels,
                datasets: [
                    {
                        label: "Queries",
                        data: this.state.dailyTrend.counts,
                        borderColor: "rgba(37, 99, 235, 1)",
                        backgroundColor: "rgba(37, 99, 235, 0.15)",
                        fill: true,
                        tension: 0.3,
                        yAxisID: "y",
                    },
                    {
                        label: "Cost",
                        data: this.state.dailyTrend.costs,
                        borderColor: "rgba(245, 158, 11, 1)",
                        backgroundColor: "rgba(245, 158, 11, 0.15)",
                        tension: 0.3,
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Queries" } },
                    y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Cost" } },
                },
            },
        });
    }

    async onChangeDays(event) {
        this.state.days = parseInt(event.target.value, 10);
        await this.fetchData();
    }

    openLogs() {
        const domain = this.state.days > 0
            ? [["create_date", ">=", this.getCutoffDateString(this.state.days)]]
            : [];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "AI Call Logs",
            res_model: "aps.ai.call.log",
            views: [[false, "graph"], [false, "pivot"], [false, "list"], [false, "form"]],
            domain,
        });
    }

    getCutoffDateString(days) {
        const date = new Date();
        date.setDate(date.getDate() - days);
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} 00:00:00`;
    }

    formatCost(value) {
        return Number(value || 0).toFixed(6);
    }

    formatDuration(value) {
        const milliseconds = Number(value || 0);
        if (!milliseconds) {
            return "0 ms";
        }
        if (milliseconds < 1000) {
            return `${milliseconds.toFixed(0)} ms`;
        }
        return `${(milliseconds / 1000).toFixed(2)} s`;
    }
}

registry.category("actions").add("aps_ai_dashboard", AIDashboard);