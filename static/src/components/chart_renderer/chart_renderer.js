import { Component, onMounted, onWillStart, useRef, onPatched } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class ChartRenderer extends Component {
    setup() {
        this.chartRef = useRef("chart"); // Reference to the canvas element [cite: 21, 23]
        this.chart = null; // Store chart instance
        
        onWillStart(async () => {
            // Loading the latest Chart.js version via CDN [cite: 21, 22]
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0");
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
                chartData.labels = this.props.data.map(d => d.date);
                const datasetColors = ['rgb(255 172 0)', 'rgb(23 162 184)', 'rgb(150, 157, 163)'];
                chartData.datasets = [

                // {
                //         label: 'Finalised',
                //         data: this.props.data.map(d => d.Finalised),
                //         backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[2], 40)),
                //         borderColor: Array(chartData.labels.length).fill(datasetColors[2]),
                //         borderWidth: 2,
                //         fill: true,
                //         tension: 0.1,
                //         pointRadius: 0,
                //         cubicInterpolationMode: 'monotone',
                //     }   ,                 
                    {
                        label: 'Submitted*',
                        data: this.props.data.map(d => d.submitted_finalized),
                        backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[1], 40)),
                        borderColor: Array(chartData.labels.length).fill(datasetColors[1]),
                        borderWidth: 2,
                        fill: true,
                        tension: 0.1,
                        pointRadius: 0,
                        cubicInterpolationMode: 'monotone',
                    },
                    {
                        label: 'Assigned',
                        data: this.props.data.map(d => d.assigned),
                        backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[0], 40)),
                        borderColor: Array(chartData.labels.length).fill(datasetColors[0]),
                        borderWidth: 2,
                        fill: true,
                        tension: 0.1,
                        pointRadius: 0,
                        cubicInterpolationMode: 'monotone',
                    },                    
      
                ];
            } else if (this.props.type === 'bar') {
                chartData.labels = this.props.data.map(d => d.date);
                const datasetColors = ['rgb(255 172 0)', 'rgb(23 162 184)', 'rgb(150, 157, 163)'];
                chartData.datasets = [
                    {
                        label: 'Assigned',
                        data: this.props.data.map(d => d.assigned),
                        backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[0], 40)),
                        borderColor: Array(chartData.labels.length).fill(datasetColors[0]),
                        borderWidth: 1
                    },
                    {
                        label: 'Submitted',
                        data: this.props.data.map(d => d.submitted),
                        backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[1], 40)),
                        borderColor: Array(chartData.labels.length).fill(datasetColors[1]),
                        borderWidth: 1
                    },
                    {
                        label: 'Finalised',
                        data: this.props.data.map(d => d.finalized),
                        backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[2], 40)),
                        borderColor: Array(chartData.labels.length).fill(datasetColors[2]),
                        borderWidth: 1
                    }
                ];

            } else if (this.props.type === 'doughnut' || this.props.type === 'pie') {
                if (this.props.data.labels && this.props.data.datasets) {
                    if (Array.isArray(this.props.data.datasets[0])) {
                        // datasets is list of lists
                        chartData.labels = this.props.data.labels;
                        chartData.datasets = this.props.data.datasets.map((dataArr, index) => ({
                            data: dataArr,
                            backgroundColor: this.generateColors(this.props.data.labels, index),
                            borderWidth: 1
                        }));
                    } else {
                        // datasets is already array of dataset objects
                        chartData = this.props.data;
                    }
                } else {
                    // For doughnut, data grouped by subject
                    chartData.labels = this.props.data.map(d => d.data_point || 'Unknown');
                    chartData.datasets = [{
                        label: this.props.title,
                        data: this.props.data.map(d => d.__count),
                        backgroundColor: this.generateColors(chartData.labels, 0),
                        hoverOffset: 4
                    }];
                }
            }
        }

        this.chart = new Chart(this.chartRef.el, {
            type: this.props.type || 'bar',
            data: chartData,
            plugins: [ChartDataLabels],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: (this.props.type === 'bar' || this.props.type === 'line') ? 'bottom' : 'right',
                    },
                    title: {
                        display: true,
                        text: this.props.title,
                        position: 'top',
                        align: 'center',  // 'start', 'center', 'end'
                    },
                    // subtitle: {
                    //     display: true,
                    //     text: 'Data for Q1 2026 - All regions',  // Your subtitle here
                    //     font: {
                    //     size: 14,
                    //     style: 'italic'
                    //     },
                    //     color: '#666',
                    //     padding: {
                    //     top: 0,
                    //     bottom: 100
                    //     },
                    //     align: 'start',  // 'start', 'center', 'end',
                    //     position: 'bottom'
                    // },
                    datalabels: {
                        display: (this.props.type === 'doughnut' || this.props.type === 'pie'),
                        color: '#fff', // Text color
                        anchor: 'center',
                        align: 'center',
                        font: {
                            weight: 'bold',
                            size: 14
                        },
                        formatter: (value, context) => {
                            // Only show if value is greater than 0
                            return value > 0 ? value : ''; 
                        }
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

    generateColors(labels, datasetIndex) {
        const colorMap = {
            'Late': 'rgb(220 53 69)',
            'Early': 'rgb(40 167 69)',
            'On Time': 'rgb(150, 157, 163)',
            'Assigned': 'rgb(255 172 0)',
            'Finalised': 'rgb(150, 157, 163)',
            'Submitted': 'rgb(23 162 184)',
            // Add more label-color mappings as needed
        };
        const defaultColors = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40'];
        return labels.map((label, i) => colorMap[label] || defaultColors[(i + datasetIndex * 2) % defaultColors.length]);
    }

    lightenColor(color, percent) {
        const match = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
        if (match) {
            const r = Math.min(255, parseInt(match[1]) + (255 - parseInt(match[1])) * percent / 100);
            const g = Math.min(255, parseInt(match[2]) + (255 - parseInt(match[2])) * percent / 100);
            const b = Math.min(255, parseInt(match[3]) + (255 - parseInt(match[3])) * percent / 100);
            return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
        }
        // For hex, could add conversion, but for now return as is
        return color;
    }
}

ChartRenderer.template = "custom_dashboard.ChartRenderer";