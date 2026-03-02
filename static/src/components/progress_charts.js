/**
 * Progress Charts Module
 * Handles all progress chart functionality including data fetching, 
 * PACE calculations, and chart rendering for the APEX dashboard.
 */

export class ProgressCharts {
    constructor(component) {
        this.component = component;
        this.state = component.state;
        this.orm = component.orm;
        this.progressLineChartInstance = null;
        this.progressBarChartInstance = null;
    }

    /**
     * Fetch progress data from the backend and process it for charts.
     */
    async fetchProgressData() {
        console.time('Fetch Progress Data');
        this.state.loadingProgress = true;

        // Only fetch progress data if a student is selected
        if (!this.state.selectedStudent || this.state.selectedStudent === "false") {
            this.state.progressLineData = [];
            this.state.progressBarData = [];
            this.state.loadingProgress = false;
            console.timeEnd('Fetch Progress Data');
            return;
        }

        try {
            // Call the backend method to get progress data
            const progressData = await this.orm.call(
                "aps.resource.submission",
                "get_progress_data_for_dashboard",
                [parseInt(this.state.selectedStudent, 10), this.component.getPeriodStartDateStr()]
            );

            console.time('Process Progress Data');

            // Store period boundaries for zoom
            this.state.periodStart = progressData.period_start;
            this.state.periodEnd = progressData.period_end;

            // Process line chart data
            const lineData = progressData.line_data || {};
            const paceData = progressData.pace_data || {};
            const subjectColors = progressData.subject_colors || {};
            
            // Store PACE data and calculate today's PACE
            this.state.paceData = paceData;
            this.state.paceForToday = this.calculatePaceForToday(paceData);

            // Convert line data to Chart.js format
            const datasets = [];
            const today = new Date().toISOString().split('T')[0];

            for (const [subjectId, dataPoints] of Object.entries(lineData)) {
                if (!dataPoints || dataPoints.length === 0) continue;

                const subjectIdNum = parseInt(subjectId);
                const subjectName = dataPoints[0].subject_name;
                const color = subjectColors[subjectIdNum];

                // Sort data points by date
                const sortedPoints = dataPoints.sort((a, b) => a.date.localeCompare(b.date));

                datasets.push({
                    label: subjectName,
                    data: sortedPoints.map(p => ({
                        x: p.date,
                        y: p.result_percent
                    })),
                    borderColor: color,
                    backgroundColor: color + '40', // Add transparency
                    tension: 0.4,
                    fill: false,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    subjectId: subjectIdNum
                });
            }

            // Add PACE lines (one per resource, not per subject)
            for (const [resourceId, pace] of Object.entries(paceData)) {
                if (pace && pace.start_date && pace.end_date) {
                    const paceDataset = this.calculatePaceLine(
                        pace.start_date,
                        pace.end_date,
                        this.component.getPeriodStartDateStr(),
                        today,
                        pace.resource_name
                    );
                    if (paceDataset) {
                        datasets.push(paceDataset);
                    }
                }
            }

            this.state.progressLineData = datasets;

            // Process bar chart data
            const barData = progressData.bar_data || [];
            this.state.progressBarData = barData.map(item => ({
                subject_name: item.subject_name,
                progress: item.progress,
                color: item.color,
                subject_id: item.subject_id
            }));

            console.timeEnd('Process Progress Data');
        } catch (error) {
            console.error("Error fetching progress data:", error);
            this.state.progressLineData = [];
            this.state.progressBarData = [];
        }

        this.state.loadingProgress = false;
        console.timeEnd('Fetch Progress Data');
        
        // Render charts after data is loaded
        this.renderProgressCharts();
    }

    /**
     * Calculate the average PACE percentage for today across all resources.
     * Returns a single percentage value representing where students should be today.
     */
    calculatePaceForToday(paceData) {
        if (!paceData || Object.keys(paceData).length === 0) {
            return 0;
        }

        const today = new Date();
        const paceValues = [];

        for (const [resourceId, pace] of Object.entries(paceData)) {
            if (!pace || !pace.start_date || !pace.end_date) {
                continue;
            }

            try {
                const startDate = new Date(pace.start_date);
                const endDate = new Date(pace.end_date);

                if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
                    continue;
                }

                // Only include if today is within the resource date range
                if (today < startDate || today > endDate) {
                    continue;
                }

                const totalDays = (endDate - startDate) / (1000 * 60 * 60 * 24);
                if (totalDays <= 0) continue;

                const daysFromStart = (today - startDate) / (1000 * 60 * 60 * 24);
                const progressPercent = (daysFromStart / totalDays) * 100;
                paceValues.push(Math.max(0, Math.min(100, progressPercent)));
            } catch (error) {
                console.error("Error calculating PACE for today:", error);
                continue;
            }
        }

        // Return average PACE or 0 if no valid pace data
        return paceValues.length > 0 
            ? paceValues.reduce((a, b) => a + b, 0) / paceValues.length 
            : 0;
    }

    /**
     * Calculate PACE line showing expected progress over time.
     * PACE is calculated pro-rata from start_date to end_date.
     * Returns a dataset object for Chart.js or null if dates are invalid.
     */
    calculatePaceLine(startDateStr, endDateStr, periodStartStr, todayStr, resourceName) {
        try {
            const startDate = new Date(startDateStr);
            const endDate = new Date(endDateStr);
            const periodStart = new Date(periodStartStr);
            const today = new Date(todayStr);

            if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
                return null;
            }

            // Calculate total duration in days
            const totalDays = (endDate - startDate) / (1000 * 60 * 60 * 24);
            if (totalDays <= 0) return null;

            // Create pace data points
            const paceData = [];

            // Start point (either period start or pace start, whichever is later)
            const displayStart = periodStart > startDate ? periodStart : startDate;
            const daysFromStart = (displayStart - startDate) / (1000 * 60 * 60 * 24);
            const startProgress = (daysFromStart / totalDays) * 100;

            paceData.push({
                x: displayStart.toISOString().split('T')[0],
                y: Math.max(0, Math.min(100, startProgress))
            });

            // Current point (today or end date, whichever is earlier)
            const displayEnd = today < endDate ? today : endDate;
            const daysFromStartToEnd = (displayEnd - startDate) / (1000 * 60 * 60 * 24);
            const currentProgress = (daysFromStartToEnd / totalDays) * 100;

            paceData.push({
                x: displayEnd.toISOString().split('T')[0],
                y: Math.max(0, Math.min(100, currentProgress))
            });

            return {
                label: `${resourceName} PACE`,
                data: paceData,
                borderColor: '#808080',
                backgroundColor: 'transparent',
                borderDash: [5, 5],
                tension: 0,
                fill: false,
                pointRadius: 2,
                pointHoverRadius: 0,  // Disable hover on points
                pointHitRadius: 0,     // Disable hit detection
                borderWidth: 2,
                isPace: true
            };
        } catch (error) {
            console.error("Error calculating PACE line:", error);
            return null;
        }
    }

    /**
     * Toggle visibility of a subject in the line chart.
     * Click a subject to show only that subject. Click it again to show all subjects.
     */
    toggleSubjectVisibility(subjectId) {
        if (this.state.selectedSubjectId === subjectId) {
            // Clicking the same subject again: show all subjects
            this.state.selectedSubjectId = null;
        } else {
            // Clicking a different subject: focus on it
            this.state.selectedSubjectId = subjectId;
        }
        
        // Trigger re-render
        this.renderProgressCharts();
    }

    /**
     * Render both progress charts (line and bar).
     * Called when data changes or when subject visibility is toggled.
     */
    renderProgressCharts() {
        this.renderProgressLineChart();
        this.renderProgressBarChart();
    }

    /**
     * Render the progress line chart showing progress over time.
     * Uses linear scale with timestamps to properly space dates.
     * Chart displays the selected period with proper date-based spacing.
     */
    renderProgressLineChart() {
        const canvas = this.component.__owl__.refs?.progressLineChart;
        if (!canvas || !this.state.progressLineData || this.state.progressLineData.length === 0) {
            return;
        }

        // Destroy existing chart
        if (this.progressLineChartInstance) {
            this.progressLineChartInstance.destroy();
        }

        // Calculate period boundaries as timestamps
        const periodStartTs = this.state.periodStart ? new Date(this.state.periodStart).getTime() : null;
        const periodEndTs = this.state.periodEnd ? new Date(this.state.periodEnd).getTime() : null;

        // Filter datasets based on selected subject and convert dates to timestamps
        const visibleDatasets = this.state.progressLineData.map(dataset => {
            const dataWithTimestamps = dataset.data.map(point => ({
                x: new Date(point.x).getTime(),  // Convert to timestamp
                y: point.y
            }));
            
            // If a subject is selected, hide all others (except PACE lines). Otherwise show all.
            const shouldHide = this.state.selectedSubjectId !== null && 
                               dataset.subjectId && 
                               dataset.subjectId !== this.state.selectedSubjectId;
            
            return {
                ...dataset,
                data: dataWithTimestamps,
                hidden: shouldHide || dataset.hidden
            };
        });

        // Create chart with linear scale (timestamps)
        this.progressLineChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                datasets: visibleDatasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        onClick: (evt, legendItem, legend) => {
                            // Handle legend click to toggle subject visibility
                            const index = legendItem.datasetIndex;
                            const dataset = this.state.progressLineData[index];
                            if (dataset && dataset.subjectId && !dataset.isPace) {
                                this.toggleSubjectVisibility(dataset.subjectId);
                            }
                            // Return false to prevent default Chart.js behavior (which causes errors with PACE datasets)
                            return false;
                        }
                    },
                    title: {
                        display: false
                    },
                    tooltip: {
                        filter: (tooltipItem) => {
                            // Exclude PACE datasets from tooltips to prevent errors
                            return !tooltipItem.dataset.isPace;
                        },
                        callbacks: {
                            title: (context) => {
                                // Format date for tooltip from timestamp
                                const timestamp = context[0].parsed.x;
                                const date = new Date(timestamp);
                                return date.toLocaleDateString('en-US', { 
                                    year: 'numeric', 
                                    month: 'short', 
                                    day: 'numeric' 
                                });
                            },
                            label: (context) => {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += Math.round(context.parsed.y) + '%';
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: periodStartTs,  // Set initial view to period start
                        max: periodEndTs,    // Set initial view to period end
                        title: {
                            display: true,
                            text: 'Date'
                        },
                        ticks: {
                            maxRotation: 45,
                            minRotation: 0,
                            callback: function(value) {
                                // Format timestamp to date string
                                const date = new Date(value);
                                const month = date.toLocaleString('en', { month: 'short' });
                                const day = date.getDate();
                                return `${month} ${day}`;
                            }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Progress (%)'
                        },
                        ticks: {
                            callback: function(value) {
                                return value + '%';
                            }
                        }
                    }
                }
            }
        });
    }

    /**
     * Render the progress bar chart showing current progress by subject.
     * Includes a vertical reference line showing the expected PACE for today.
     */
    renderProgressBarChart() {
        const canvas = this.component.__owl__.refs?.progressBarChart;
        if (!canvas || !this.state.progressBarData || this.state.progressBarData.length === 0) {
            return;
        }

        // Destroy existing chart
        if (this.progressBarChartInstance) {
            this.progressBarChartInstance.destroy();
        }

        // Prepare data
        const labels = this.state.progressBarData.map(item => item.subject_name);
        const data = this.state.progressBarData.map(item => item.progress);
        const colors = this.state.progressBarData.map(item => item.color);
        const paceForToday = this.state.paceForToday;

        // Create chart
        this.progressBarChartInstance = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Current Progress',
                    data: data,
                    backgroundColor: colors.map(c => c + '80'), // Add transparency
                    borderColor: colors,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y', // Horizontal bar chart
                layout: {
                    padding: {
                        top: 30  // Add padding above chart for PACE label
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    title: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                return 'Progress: ' + Math.round(context.parsed.x) + '%';
                            }
                        }
                    },
                    // Add plugin to draw PACE reference line
                    paceLine: {
                        paceValue: paceForToday
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Progress (%)'
                        },
                        ticks: {
                            callback: function(value) {
                                return value + '%';
                            }
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Subject'
                        }
                    }
                }
            },
            plugins: [{
                id: 'paceLine',
                afterDatasetsDraw: (chart) => {
                    const paceValue = paceForToday;
                    if (paceValue === 0 || paceValue === undefined) {
                        return;  // Don't draw line if no PACE value
                    }

                    const ctx = chart.ctx;
                    const xScale = chart.scales.x;
                    const yScale = chart.scales.y;

                    // Convert pace percentage to pixel position on x-axis
                    const xPixel = xScale.getPixelForValue(paceValue);

                    // Draw vertical line
                    ctx.save();
                    ctx.strokeStyle = '#808080';
                    ctx.lineWidth = 2;
                    ctx.setLineDash([5, 5]);
                    ctx.beginPath();
                    ctx.moveTo(xPixel, yScale.top);
                    ctx.lineTo(xPixel, yScale.bottom);
                    ctx.stroke();

                    // Draw label at top
                    ctx.restore();
                    ctx.save();
                    ctx.font = 'bold 12px sans-serif';
                    ctx.fillStyle = '#808080';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'bottom';
                    ctx.fillText(`PACE: ${Math.round(paceValue)}%`, xPixel, yScale.top - 5);
                    ctx.restore();
                }
            }]
        });
    }

    /**
     * Cleanup method to destroy chart instances.
     */
    destroy() {
        if (this.progressLineChartInstance) {
            this.progressLineChartInstance.destroy();
            this.progressLineChartInstance = null;
        }
        if (this.progressBarChartInstance) {
            this.progressBarChartInstance.destroy();
            this.progressBarChartInstance = null;
        }
    }
}
