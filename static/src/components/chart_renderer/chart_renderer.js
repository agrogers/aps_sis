import { Component, onMounted, onWillStart, useRef, onPatched } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class ChartRenderer extends Component {
    setup() {
        this.chartRef = useRef("chart"); // Reference to the canvas element [cite: 21, 23]
        this.chart = null; // Store chart instance
        
        onWillStart(async () => {
            // Loading the latest Chart.js version via CDN [cite: 21, 22]
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
        });

        onMounted(() => {
            this.renderChart(); // Render chart once component is in the DOM [cite: 21, 27]
        });

        onPatched(() => {
            this.renderChart(); // Re-render chart when component updates
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

        if (this.props.data && this.props.data.length > 0) {
            if (this.props.type === 'line') {
                chartData.labels = this.props.data.map(d => d.date_assigned || d.date_submitted);
                chartData.datasets[0].data = this.props.data.map(d => d.__count);

            } else if (this.props.type === 'bar') {
                chartData.labels = this.props.data.map(d => d.date);
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
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        borderColor: 'rgba(75, 192, 192, 1)',
                        borderWidth: 1
                    }
                ];

            } else if (this.props.type === 'doughnut') {
                if (this.props.data.labels && this.props.data.datasets) {
                    if (Array.isArray(this.props.data.datasets[0])) {
                        // datasets is list of lists
                        chartData.labels = this.props.data.labels;
                        chartData.datasets = this.props.data.datasets.map((dataArr, index) => ({
                            data: dataArr,
                            backgroundColor: this.generateColors(dataArr.length, index),
                            borderWidth: 1
                        }));
                    } else {
                        // datasets is already array of dataset objects
                        chartData = this.props.data;
                    }
                } else {
                    // For doughnut, data grouped by subject
                    chartData.labels = this.props.data.map(d => d.subject || 'Unknown');
                    chartData.datasets[0].data = this.props.data.map(d => d.__count);
                }
            }
        }

        this.chart = new Chart(this.chartRef.el, {
            type: this.props.type || 'bar',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                    },
                    title: {
                        display: true,
                        text: this.props.title,
                        position: 'bottom'
                    }
                },
                scales: this.props.type === 'bar' ? {
                    x: {
                        stacked: true,
                    },
                    y: {
                        stacked: true,
                    }
                } : {}
            }
        });
    }
}

ChartRenderer.template = "custom_dashboard.ChartRenderer";