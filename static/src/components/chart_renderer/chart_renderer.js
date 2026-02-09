import { Component, onMounted, onWillStart, useRef, onPatched } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class ChartRenderer extends Component {
    setup() {
        this.chartRef = useRef("chart");
        this.chart = null;
        
        onWillStart(async () => {
            // Load Chart.js if not already loaded by the framework
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
        });

        onMounted(() => {
            this.renderChart();
        });

        onPatched(() => {
            this.renderChart();
        });
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
        }

        let chartData = {
            labels: ['Red', 'Blue', 'Yellow', 'Green', 'Purple', 'Orange'],
            datasets: [{
                label: this.props.title,
                data: [12, 19, 3, 5, 2, 3],
                borderWidth: 1
            }]
        };

        if (this.props.data) {
            if (this.props.type === 'line') {
                chartData.labels = this.props.data.map(d => d.date_assigned || d.date_submitted || d.month);
                chartData.datasets = [{
                    label: this.props.title,
                    data: this.props.data.map(d => d.__count || d.value),
                    borderColor: 'rgb(75, 192, 192)',
                    tension: 0.1
                }];
            } else if (this.props.type === 'bar') {
                chartData.labels = this.props.data.map(d => d.date_assigned);
                chartData.datasets = [
                    {
                        label: 'Assigned',
                        data: this.props.data.map(d => d.assigned),
                        backgroundColor: 'rgba(255, 99, 132, 0.2)',
                        borderColor: 'rgba(255, 99, 132, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Submitted',
                        data: this.props.data.map(d => d.submitted),
                        backgroundColor: 'rgba(54, 162, 235, 0.2)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Finalized',
                        data: this.props.data.map(d => d.finalized),
                        backgroundColor: 'rgba(75, 206, 86, 0.2)',
                        borderColor: 'rgba(75, 206, 86, 1)',
                        borderWidth: 1
                    }
                ];
            } else if (this.props.type === 'doughnut' || this.props.type === 'pie') {
                if (this.props.data.labels && this.props.data.datasets) {
                    if (Array.isArray(this.props.data.datasets[0])) {
                        chartData.labels = this.props.data.labels;
                        chartData.datasets = this.props.data.datasets.map((dataset, index) => ({
                            label: `Dataset ${index}`,
                            data: dataset,
                            // backgroundColor: this.generateColors(dataset.length, index),
                            hoverOffset: 4
                        }));
                    } else {
                        chartData = this.props.data;
                    }
                } else if (Array.isArray(this.props.data)) {
                    chartData.labels = this.props.data.map(d => d.subject || "Unknown");
                    chartData.datasets = [{
                        label: this.props.title,
                        data: this.props.data.map(d => d.__count),
                        // backgroundColor: this.generateColors(this.props.data.length, 0),
                        hoverOffset: 4
                    }];
                }
            }
        }

        const ctx = this.chartRef.el.getContext('2d');
        this.chart = new Chart(ctx, {
            type: this.props.type,
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: this.props.title }
                }
            }
        });
    }

    generateColors(count, datasetIndex) {
        const colors = [];
        for (let i = 0; i < count; i++) {
            const hue = (i * 360 / count + datasetIndex * 60) % 360;
            colors.push(`hsl(${hue}, 70%, 50%)`);
        }
        return colors;
    }
}

// THIS IS THE MISSING PART THAT LIKELY CAUSED THE ERROR:
ChartRenderer.template = "custom_dashboard.ChartRenderer";