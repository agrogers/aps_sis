import { Component, onMounted, onWillStart, useRef, onPatched } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class ChartRenderer extends Component {
    static props = {
        name: { type: String, optional: true },
        value: { type: [Number, String], optional: true },
        // max: { type: [Number, String], optional: true },
        // zones: { type: Array, optional: true },
        // points_from_next: { type: [Number, String], optional: true },
        // total_students: { type: [Number, String], optional: true },
        // icon: { type: String, optional: true },
        // period_name: { type: String, optional: true },
        onClick: { type: Function, optional: true },
        percentage: { type: [Number, String], optional: true },
        title: { type: String, optional: true },
        type: { type: String, optional: true }, // 'bar', 'line', 'doughnut', 'pie'
        data: { type: [Array, Object], optional: true }, // Expecting array of objects with 'date', 'assigned', 'submitted', 'finalized' keys for line/bar; or 'data_point' and '__count' for doughnut/pie; or pre-built chart config object

    };    
    setup() {
        this.chartRef = useRef("chart"); // Reference to the canvas element [cite: 21, 23]
        this.chart = null; // Store chart instance
        
        onWillStart(async () => {
            // Loading the latest Chart.js version via CDN [cite: 21, 22]
            // await loadJS("https://unpkg.com/chart.js");
            await loadJS("/aps_sis/static/src/lib/chart.js");
            // await loadJS("/aps_sis/static/src/lib/chartjs-plugin-datalabels-2.0.0.min.js");
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
            // labels: ['Red', 'Blue', 'Yellow', 'Green', 'Purple', 'Orange'],
            // datasets: [{
            //     label: this.props.title,
            //     data: [12, 19, 3, 5, 2, 3],
            //     borderWidth: 1
            // }]
        };

        const data = this.props.data;
        const isArrayData = Array.isArray(data) && data.length > 0;
        const isObjectData = data && !Array.isArray(data) && typeof data === 'object' && data.labels;

        if (isArrayData || isObjectData) {
            if (this.props.type === 'line') {
                chartData.labels = this.props.data.map(d => d.date);
                const datasetColors = ['rgb(255 172 0)', 'rgb(23 162 184)', 'rgb(150, 157, 163)'];
                chartData.datasets = [

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
                        borderWidth: 1,
                        stack: 'assigned'
                    },
                    {
                        label: 'Submitted - Early',
                        data: this.props.data.map(d => d.submitted_early ?? 0),
                        backgroundColor: Array(chartData.labels.length).fill('rgb(40 167 69)'),
                        borderColor: Array(chartData.labels.length).fill('rgb(40 167 69)'),
                        borderWidth: 1,
                        stack: 'submitted'
                    },
                    {
                        label: 'Submitted - On Time',
                        data: this.props.data.map(d => d.submitted_on_time ?? 0),
                        backgroundColor: Array(chartData.labels.length).fill('rgb(150, 157, 163)'),
                        borderColor: Array(chartData.labels.length).fill('rgb(150, 157, 163)'),
                        borderWidth: 1,
                        stack: 'submitted'
                    },
                    {
                        label: 'Submitted - Late',
                        data: this.props.data.map(d => d.submitted_late ?? 0),
                        backgroundColor: Array(chartData.labels.length).fill('rgb(220 53 69)'),
                        borderColor: Array(chartData.labels.length).fill('rgb(220 53 69)'),
                        borderWidth: 1,
                        stack: 'submitted'
                    },
                    // {
                    //     label: 'Finalised',
                    //     data: this.props.data.map(d => d.finalized),
                    //     backgroundColor: Array(chartData.labels.length).fill(this.lightenColor(datasetColors[2], 40)),
                    //     borderColor: Array(chartData.labels.length).fill(datasetColors[2]),
                    //     borderWidth: 1
                    // }
                ];

            } else if (this.props.type === 'doughnut' || this.props.type === 'pie') {
                if (this.props.data.labels && this.props.data.datasets) {
                    if (Array.isArray(this.props.data.datasets[0])) {
                        // datasets is list of lists
                        chartData.labels = this.props.data.labels;
                        chartData.datasets = this.props.data.datasets.map((dataArr, index) => ({
                            data: dataArr,
                            backgroundColor: this.generateColors(this.props.data.labels, index),
                            borderWidth: 1,
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
                        hoverOffset: 4,
                    }];
                }
            }
        }

        const hasSpacerDataset = chartData.datasets && chartData.datasets.some(ds => ds.label === 'Spacer');

        // Inline plugin to draw center label on dual-ring doughnuts
        const centerLabelPlugin = {
            id: 'centerLabel',
            afterDraw(chart) {
                if (!hasSpacerDataset) return;
                const { ctx, chartArea } = chart;
                const centerX = (chartArea.left + chartArea.right) / 2;
                const centerY = (chartArea.top + chartArea.bottom) / 2;

                // Center label: "Class Average"
                ctx.save();
                ctx.font = '11px sans-serif';
                ctx.fillStyle = '#6c757d';
                ctx.textAlign = 'left';
                ctx.textBaseline = 'bottom';
                ctx.fillText('← Class Average', centerX - 60, centerY);
                ctx.restore();

                // Outer ring label: "Student Data" at top-right
                const outerMeta = chart.getDatasetMeta(0);
                if (outerMeta && outerMeta.data.length > 0) {
                    const outerRadius = outerMeta.data[0].outerRadius;
                    const labelX = centerX + 60;
                    const labelY = chartArea.top;
                    ctx.save();
                    ctx.font = '11px sans-serif';
                    ctx.fillStyle = '#6c757d';
                    ctx.textAlign = 'left';
                    ctx.textBaseline = 'top';
                    ctx.fillText('↙ Student Data', labelX, labelY);
                    ctx.restore();
                }
            }
        };

        this.chart = new Chart(this.chartRef.el, 
            {
            type: this.props.type || 'bar',
            data: chartData,
            plugins: hasSpacerDataset ? [centerLabelPlugin] : [],
            options: {
                borderWidth: 1,
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: (this.props.type === 'bar' || this.props.type === 'line') ? 'bottom' : 'right',
                        ...(hasSpacerDataset ? {
                            labels: {
                                filter: (legendItem) => {
                                    return legendItem.datasetIndex !== chartData.datasets.findIndex(ds => ds.label === 'Spacer');
                                }
                            }
                        } : {}),
                    },
                    tooltip: {
                        ...(hasSpacerDataset ? {
                            filter: (tooltipItem) => {
                                return tooltipItem.dataset.label !== 'Spacer';
                            }
                        } : {}),
                    },
                    title: {
                        display: true,
                        text: this.props.title,
                        position: 'top',
                        align: 'center',  // 'start', 'center', 'end'
                    },
                    

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
        );
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