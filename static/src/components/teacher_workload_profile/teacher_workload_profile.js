import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const LEAD_COLOR = "#16756f";
const ASSISTANT_COLOR = "#d88732";

function formatNumber(value) {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(Number(value) || 0);
}

function subjectAxisIcons(subjects, images) {
    return {
        id: "subjectAxisIcons",
        afterDraw(chart) {
            const xScale = chart.scales.x;
            if (!xScale) {
                return;
            }
            const iconSize = 20;
            const iconY = chart.height - 27;
            const { ctx } = chart;
            ctx.save();
            subjects.forEach((subject, index) => {
                const image = images[index];
                if (!image) {
                    return;
                }
                const x = xScale.getPixelForTick(index);
                ctx.drawImage(image, x - iconSize / 2, iconY, iconSize, iconSize);
            });
            ctx.restore();
        },
    };
}

function maximumLoadMarker(maxLoad) {
    return {
        id: "maximumLoadMarker",
        afterDatasetsDraw(chart) {
            const xScale = chart.scales.x;
            const { left, right, top, bottom } = chart.chartArea;
            if (!xScale || maxLoad < xScale.min || maxLoad > xScale.max) {
                return;
            }
            const x = xScale.getPixelForValue(maxLoad);
            const label = "Max Load";
            const { ctx } = chart;
            ctx.save();
            ctx.strokeStyle = "#b42318";
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            ctx.moveTo(x, top);
            ctx.lineTo(x, bottom);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = "#b42318";
            ctx.font = "600 12px sans-serif";
            const labelX = Math.max(left, Math.min(x + 7, right - ctx.measureText(label).width));
            ctx.fillText(label, labelX, top + 14);
            ctx.restore();
        },
    };
}

export class TeacherWorkloadProfile extends Component {
    static template = "aps_sis.TeacherWorkloadProfile";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.subjectChartRef = useRef("subjectChart");
        this.loadChartRef = useRef("loadChart");
        this.subjectChart = null;
        this.loadChart = null;
        this.state = useState({ loading: true, error: null, profile: null });
        this.onBeforePrint = this.onBeforePrint.bind(this);
        this.onAfterPrint = this.onAfterPrint.bind(this);

        onWillStart(async () => {
            if (!window.Chart) {
                await loadJS("/aps_sis/static/src/lib/chart.js");
            }
            await this.loadProfile();
        });
        onMounted(() => {
            void this.renderCharts();
            window.addEventListener("beforeprint", this.onBeforePrint);
            window.addEventListener("afterprint", this.onAfterPrint);
        });
        onWillUnmount(() => {
            window.removeEventListener("beforeprint", this.onBeforePrint);
            window.removeEventListener("afterprint", this.onAfterPrint);
            this.destroyCharts();
        });
    }

    async loadProfile() {
        const teacherId = Number(this.props.action?.params?.teacher_id);
        if (!Number.isInteger(teacherId) || teacherId <= 0) {
            this.state.error = "A teacher record was not provided.";
            this.state.loading = false;
            return;
        }
        try {
            this.state.profile = await this.orm.call(
                "aps.teacher",
                "get_timetable_workload_profile",
                [[teacherId]],
                {}
            );
        } catch (error) {
            console.error("Unable to load teacher workload profile", error);
            this.state.error = "Unable to load workload data for this teacher.";
        } finally {
            this.state.loading = false;
        }
    }

    async renderCharts() {
        if (!this.state.profile || !window.Chart) {
            return;
        }
        const profile = this.state.profile;
        const subjects = profile.subjects || [];
        const subjectIcons = await Promise.all(subjects.map((subject) => {
            if (!subject.icon_url) {
                return null;
            }
            return new Promise((resolve) => {
                const image = new Image();
                image.onload = () => resolve(image);
                image.onerror = () => resolve(null);
                image.src = subject.icon_url;
            });
        }));
        if (this.subjectChartRef.el && subjects.length) {
            this.subjectChart = new window.Chart(this.subjectChartRef.el, {
                type: "bar",
                data: {
                    labels: subjects.map((subject) => subject.name),
                    datasets: [
                        {
                            label: "Lead",
                            data: subjects.map((subject) => subject.lead_minutes),
                            backgroundColor: LEAD_COLOR,
                            borderRadius: 2,
                        },
                        {
                            label: "Assistant",
                            data: subjects.map((subject) => subject.assistant_minutes),
                            backgroundColor: ASSISTANT_COLOR,
                            borderRadius: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: { padding: { bottom: 32 } },
                    interaction: { mode: "index", intersect: false },
                    plugins: { legend: { position: "bottom" } },
                    scales: {
                        x: {
                            stacked: true,
                            ticks: { maxRotation: 45, minRotation: 25, autoSkip: false },
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            title: { display: true, text: "Minutes" },
                        },
                    },
                },
                plugins: [subjectAxisIcons(subjects, subjectIcons)],
            });
        }

        if (this.loadChartRef.el) {
            const axisMax = Math.max(profile.total_minutes, profile.max_load, 1);
            this.loadChart = new window.Chart(this.loadChartRef.el, {
                type: "bar",
                data: {
                    labels: ["Scheduled Load"],
                    datasets: subjects.map((subject) => ({
                        label: subject.name,
                        data: [subject.lead_minutes + subject.assistant_minutes],
                        backgroundColor: subject.category_color || "#64748b",
                        borderRadius: 2,
                    })),
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: "bottom" } },
                    scales: {
                        x: {
                            stacked: true,
                            beginAtZero: true,
                            max: Math.ceil(axisMax * 1.12),
                            title: { display: true, text: "Minutes" },
                        },
                        y: { stacked: true },
                    },
                },
                plugins: [maximumLoadMarker(profile.max_load)],
            });
        }
    }

    destroyCharts() {
        this.subjectChart?.destroy();
        this.loadChart?.destroy();
        this.subjectChart = null;
        this.loadChart = null;
    }

    resizeCharts(forPrint = false) {
        for (const chart of [this.subjectChart, this.loadChart]) {
            if (!chart) {
                continue;
            }
            if (forPrint) {
                const bounds = chart.canvas.parentElement.getBoundingClientRect();
                chart.resize(Math.floor(bounds.width), Math.floor(bounds.height));
            } else {
                chart.resize();
            }
        }
    }

    onBeforePrint() {
        this.resizeCharts(true);
    }

    onAfterPrint() {
        this.resizeCharts();
    }

    printPage() {
        window.print();
    }

    formatMinutes(value) {
        return formatNumber(value);
    }

    formatHours(value) {
        return formatNumber((Number(value) || 0) / 60);
    }
}

registry.category("actions").add("aps_teacher_workload_profile", TeacherWorkloadProfile);
