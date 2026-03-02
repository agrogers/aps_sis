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
        this.studentComparisonChartInstance = null;
    }

    /**
     * Clean subject name by removing (IGCSE) suffix
     */
    cleanSubjectName(subjectName) {
        if (!subjectName) return subjectName;
        return subjectName.replace(/\s*\(IGCSE\)\s*$/i, '').trim();
    }

    /**
     * Return a consistent Chart.js point style for a subject name.
     * Uses keyword matching first, then deterministic fallback for unknown subjects.
     */
    getSubjectPointStyle(subjectName) {
        const name = (this.cleanSubjectName(subjectName) || '').toLowerCase();

        const keywordStyles = [
            { keywords: ['math', 'mathematics', 'algebra', 'geometry', 'calculus'], style: 'triangle' },
            { keywords: ['english', 'language', 'literature', 'ela'], style: 'rectRounded' },
            { keywords: ['biology', 'bio'], style: 'circle' },
            { keywords: ['chemistry', 'chem'], style: 'rect' },
            { keywords: ['physics', 'phys'], style: 'rectRot' },
            { keywords: ['science', 'sci'], style: 'star' },
            { keywords: ['history'], style: 'cross' },
            { keywords: ['geography', 'geo'], style: 'crossRot' },
            { keywords: ['business', 'economics', 'commerce', 'accounting'], style: 'dash' },
            { keywords: ['computer', 'ict', 'coding', 'programming', 'cs'], style: 'line' },
            { keywords: ['art', 'design', 'drama'], style: 'circle' },
            { keywords: ['music'], style: 'star' },
            { keywords: ['physical education', 'pe', 'sport'], style: 'triangle' },
        ];

        for (const entry of keywordStyles) {
            if (entry.keywords.some(keyword => name.includes(keyword))) {
                return entry.style;
            }
        }

        const fallbackStyles = ['circle', 'rect', 'triangle', 'rectRot', 'star', 'cross', 'crossRot', 'line', 'dash', 'rectRounded'];
        const hash = Array.from(name).reduce((total, char) => total + char.charCodeAt(0), 0);
        return fallbackStyles[hash % fallbackStyles.length];
    }

    /**
     * Shared subject-series formatting used by all line-based subject charts.
     * Source of truth is the Subject Progress Over Time chart style.
     */
    getSubjectDatasetStyle(subjectName, color) {
        return {
            borderColor: color + '80',  // Add 50% transparency (80 in hex)
            backgroundColor: color + '40', // Add transparency
            tension: 0.4,
            fill: false,
            pointStyle: this.getSubjectPointStyle(subjectName),
            pointRadius: 7,
            pointHoverRadius: 10,
            borderWidth: 2,  // Thin lines
            borderDash: [2, 1],  // Dotted pattern
        };
    }

    /**
     * Fetch progress data from the backend and process it for charts.
     */
    async fetchProgressData() {
        this.state.loadingProgress = true;

        // Only fetch progress data if a student is selected
        if (!this.state.selectedStudent || this.state.selectedStudent === "false") {
            this.state.progressLineData = [];
            this.state.progressBarData = [];
            this.state.loadingProgress = false;
            return;
        }

        try {
            // Call the backend method to get progress data
            const progressData = await this.orm.call(
                "aps.resource.submission",
                "get_progress_data_for_dashboard",
                [parseInt(this.state.selectedStudent, 10), this.component.getPeriodStartDateStr()]
            );

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
                const subjectName = this.cleanSubjectName(dataPoints[0].subject_name);
                const color = subjectColors[subjectIdNum];

                // Sort data points by date
                const sortedPoints = dataPoints.sort((a, b) => a.date.localeCompare(b.date));

                datasets.push({
                    label: subjectName,
                    data: sortedPoints.map(p => ({
                        x: p.date,
                        y: p.result_percent
                    })),
                    ...this.getSubjectDatasetStyle(subjectName, color),
                    subjectId: subjectIdNum,
                });
            }

            // Sort datasets alphabetically by subject name (exclude PACE lines)
            datasets.sort((a, b) => {
                // Keep PACE lines at the end
                if (a.isPace && !b.isPace) return 1;
                if (!a.isPace && b.isPace) return -1;
                if (a.isPace && b.isPace) return 0;
                // Sort subjects alphabetically
                return a.label.localeCompare(b.label);
            });

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
            this.state.progressBarData = barData
                .map(item => ({
                    subject_name: this.cleanSubjectName(item.subject_name),
                    progress: item.progress,
                    color: item.color,
                    subject_id: item.subject_id
                }))
                .sort((a, b) => a.subject_name.localeCompare(b.subject_name)); // Sort alphabetically


        } catch (error) {
            console.error("Error fetching progress data:", error);
            this.state.progressLineData = [];
            this.state.progressBarData = [];
        }

        this.state.loadingProgress = false;
        
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
                borderDash: [5, 3],
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
     * Render both progress charts (line and bar).
     * Called when data changes.
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

        // Destroy existing chart only if it exists
        if (this.progressLineChartInstance) {
            this.progressLineChartInstance.destroy();
            this.progressLineChartInstance = null;
        }

        // Calculate period boundaries as timestamps
        const periodStartTs = this.state.periodStart ? new Date(this.state.periodStart).getTime() : null;
        const periodEndTs = this.state.periodEnd ? new Date(this.state.periodEnd).getTime() : null;

        // Convert dates to timestamps for all datasets
        const datasetsWithTimestamps = this.state.progressLineData.map(dataset => {
            const dataWithTimestamps = dataset.data.map(point => ({
                x: new Date(point.x).getTime(),  // Convert to timestamp
                y: point.y
            }));
            
            return {
                ...dataset,
                data: dataWithTimestamps
            };
        });
        // Create chart with linear scale (timestamps)
        this.progressLineChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                datasets: datasetsWithTimestamps
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
                        labels: {
                            usePointStyle: true,
                            padding: 15
                        }
                    },
                    title: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
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
                            display: false
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
     * Fetch student comparison data from backend.
     */
    async fetchStudentComparisonData() {
        this.state.loadingStudentComparison = true;

        try {
            // Call the backend method to get comparison data
            const comparisonData = await this.orm.call(
                "aps.resource.submission",
                "get_student_comparison_data",
                []
            );

            const studentData = comparisonData.student_data || [];
            const subjectList = comparisonData.subject_list || [];
            const paceAverage = comparisonData.pace_average || 0;

            // Sort students alphabetically
            studentData.sort((a, b) => a.student_name.localeCompare(b.student_name));

            // Extract student labels for x-axis
            const studentLabels = studentData.map(student => student.student_name);

            // Create datasets - one per subject
            const datasets = [];

            // Sort subjects alphabetically and clean names
            const sortedSubjects = subjectList
                .map(subject => ({
                    ...subject,
                    name: this.cleanSubjectName(subject.name)
                }))
                .sort((a, b) => a.name.localeCompare(b.name));

            // Calculate average progress for each student across all subjects
            const averageData = studentData.map(student => {
                const subjectProgresses = Object.values(student.progress_by_subject).filter(val => val !== null && val !== undefined);
                if (subjectProgresses.length === 0) return null;
                const sum = subjectProgresses.reduce((acc, val) => acc + val, 0);
                return sum / subjectProgresses.length;
            });

            // Add Average series first (so it renders behind other series)
            datasets.push({
                label: 'Average',
                data: averageData,
                borderColor: '#404040d3',  // Dark gray
                backgroundColor: 'transparent',
                pointRadius: 0,  // No markers
                pointHoverRadius: 0,
                borderWidth: 2,
                borderDash: [16, 8],
                tension: 0.3,
                fill: false,
                order: 1  // Lower order renders first (behind)
            });

            sortedSubjects.forEach((subject, index) => {
                const dataPoints = [];
                
                // For each student, get their progress in this subject
                studentData.forEach(student => {
                    const progress = student.progress_by_subject[subject.id];
                    if (progress !== undefined) {
                        dataPoints.push(progress);
                    } else {
                        // Add null for students without data in this subject
                        dataPoints.push(null);
                    }
                });

                datasets.push({
                    label: subject.name,
                    data: dataPoints,
                    ...this.getSubjectDatasetStyle(subject.name, subject.color),
                    subjectId: subject.id
                });
            });

            // Add PACE line as a horizontal line
            if (paceAverage > 0) {
                const paceData = studentData.map(() => paceAverage);

                datasets.push({
                    label: 'PACE (Expected)',
                    data: paceData,
                    borderColor: '#a1a1a1',
                    backgroundColor: 'rgba(128, 128, 128, 0.15)',  // Light gray shade
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    pointHitRadius: 0,  // Disable hit detection for PACE points
                    fill: 'origin',  // Fill from bottom (y=0) to the line
                    spanGaps: true,
                    isPace: true
                });
            }

            this.state.studentComparisonData = {
                labels: studentLabels,
                datasets: datasets,
                paceAverage: paceAverage
            };


        } catch (error) {
            console.error("Error fetching student comparison data:", error);
            this.state.studentComparisonData = { labels: [], datasets: [], paceAverage: 0 };
        }

        this.state.loadingStudentComparison = false;
    }

    /**
     * Render the student comparison chart.
     */
    renderStudentComparisonChart() {
        const canvas = this.component.__owl__.refs?.studentComparisonChart;
        
        if (!canvas || !this.state.studentComparisonData || !this.state.studentComparisonData.datasets || this.state.studentComparisonData.datasets.length === 0) {
            return;
        }

        // Destroy existing chart
        if (this.studentComparisonChartInstance) {
            this.studentComparisonChartInstance.destroy();
        }

        // Create chart
        this.studentComparisonChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: this.state.studentComparisonData.labels,
                datasets: this.state.studentComparisonData.datasets
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
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            padding: 15
                        }
                    },
                    title: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
                        filter: (tooltipItem) => {
                            // Exclude PACE line from tooltips
                            return !tooltipItem.dataset.isPace;
                        },
                        callbacks: {
                            label: (context) => {
                                const label = context.dataset.label || '';
                                const value = context.parsed.y;
                                if (value === null) return null;
                                return `${label}: ${Math.round(value)}%`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'category',
                        offset: true,  // Add padding to center labels like bars
                        title: {
                            display: false
                        },
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45,
                            callback: function(value, index, values) {
                                // Wrap long student names at word boundaries (max ~15 chars per line)
                                const label = this.getLabelForValue(value);
                                const maxCharsPerLine = 15;
                                if (label.length <= maxCharsPerLine) {
                                    return label;
                                }
                                // Split into multiple lines at spaces
                                const words = label.split(' ');
                                const lines = [];
                                let currentLine = '';
                                words.forEach(word => {
                                    if ((currentLine + ' ' + word).trim().length > maxCharsPerLine) {
                                        if (currentLine) lines.push(currentLine);
                                        currentLine = word;
                                    } else {
                                        currentLine = currentLine ? currentLine + ' ' + word : word;
                                    }
                                });
                                if (currentLine) lines.push(currentLine);
                                return lines;
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
        if (this.studentComparisonChartInstance) {
            this.studentComparisonChartInstance.destroy();
            this.studentComparisonChartInstance = null;
        }
    }
}
