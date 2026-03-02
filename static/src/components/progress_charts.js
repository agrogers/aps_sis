/**
 * Progress Charts Module
 * Handles all progress chart functionality including data fetching, 
 * PACE calculations, and chart rendering for the APEX dashboard.
 * 
 * Simplified approach following ChartRenderer pattern:
 * - Uses refs directly for canvas access
 * - Chart.js handles responsiveness with responsive: true
 * - No retry logic needed - lifecycle handles DOM timing
 * 
 * DEBUG: Set window.PROGRESS_CHARTS_DEBUG = true in browser console to enable logging
 */

export class ProgressCharts {
    constructor(component) {
        this.component = component;
        this.state = component.state;
        this.orm = component.orm;
        this.progressLineChartInstance = null;
        this.progressBarChartInstance = null;
        this.studentComparisonChartInstance = null;
        
        // Track last rendered data to avoid unnecessary re-renders
        this._lastProgressLineDataHash = null;
        this._lastProgressBarDataHash = null;
        this._lastStudentComparisonDataHash = null;
    }
    
    /**
     * Debug logging - only logs if window.PROGRESS_CHARTS_DEBUG is true
     */
    _debug(...args) {
        if (typeof window !== 'undefined' && window.PROGRESS_CHARTS_DEBUG) {
            console.log('[ProgressCharts]', ...args);
        }
    }
    
    /**
     * Generate a simple hash of data for change detection
     */
    _hashData(data) {
        if (!data) return null;
        try {
            return JSON.stringify(data).length + '_' + (Array.isArray(data) ? data.length : Object.keys(data).length);
        } catch (e) {
            return null;
        }
    }
    
    /**
     * Called from onPatched - only renders if chart doesn't exist and data is ready
     * This prevents constant re-renders that break legend click functionality
     */
    renderIfNeeded() {
        const lineCanvas = this.component.__owl__.refs?.progressLineChart;
        const barCanvas = this.component.__owl__.refs?.progressBarChart;
        const comparisonCanvas = this.component.__owl__.refs?.studentComparisonChart;
        
        // Progress line chart - render only if canvas exists, connected, sized, but chart doesn't exist
        if (lineCanvas && lineCanvas.isConnected && lineCanvas.offsetWidth > 0 && 
            !this.progressLineChartInstance && this.state.progressLineData?.length) {
            this._debug('renderIfNeeded: Creating progress line chart (canvas ready, no instance)');
            this.renderProgressLineChart();
        }
        
        // Progress bar chart - render only if canvas exists, connected, sized, but chart doesn't exist  
        if (barCanvas && barCanvas.isConnected && barCanvas.offsetWidth > 0 &&
            !this.progressBarChartInstance && this.state.progressBarData?.length) {
            this._debug('renderIfNeeded: Creating progress bar chart (canvas ready, no instance)');
            this.renderProgressBarChart();
        }
        
        // Student comparison chart - render only if canvas exists, connected, sized, but chart doesn't exist
        if (comparisonCanvas && comparisonCanvas.isConnected && comparisonCanvas.offsetWidth > 0 &&
            !this.studentComparisonChartInstance && this.state.studentComparisonData?.datasets?.length) {
            this._debug('renderIfNeeded: Creating student comparison chart (canvas ready, no instance)');
            this.renderStudentComparisonChart();
        }
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
     */
    getSubjectDatasetStyle(subjectName, color) {
        return {
            borderColor: color + '80',
            backgroundColor: color + '40',
            tension: 0.4,
            fill: false,
            pointStyle: this.getSubjectPointStyle(subjectName),
            pointRadius: 7,
            pointHoverRadius: 10,
            borderWidth: 2,
            borderDash: [2, 1],
        };
    }

    /**
     * Fetch progress data from the backend and process it for charts.
     */
    async fetchProgressData() {
        this._debug('fetchProgressData: Starting, selectedStudent=', this.state.selectedStudent);
        this.state.loadingProgress = true;
        
        // Destroy existing chart instances - canvas will be removed from DOM during loading
        // This ensures renderIfNeeded() will create new charts after Owl renders
        if (this.progressLineChartInstance) {
            this.progressLineChartInstance.destroy();
            this.progressLineChartInstance = null;
        }
        if (this.progressBarChartInstance) {
            this.progressBarChartInstance.destroy();
            this.progressBarChartInstance = null;
        }

        if (!this.state.selectedStudent || this.state.selectedStudent === "false") {
            this._debug('fetchProgressData: No student selected, clearing data');
            this.state.progressLineData = [];
            this.state.progressBarData = [];
            this.state.loadingProgress = false;
            return;
        }

        try {
            this._debug('fetchProgressData: Calling ORM...');
            const progressData = await this.orm.call(
                "aps.resource.submission",
                "get_progress_data_for_dashboard",
                [parseInt(this.state.selectedStudent, 10), this.component.getPeriodStartDateStr()]
            );
            this._debug('fetchProgressData: ORM returned', {
                hasLineData: !!progressData.line_data,
                lineDataKeys: Object.keys(progressData.line_data || {}),
                hasBarData: !!progressData.bar_data,
                barDataLength: (progressData.bar_data || []).length,
                periodStart: progressData.period_start,
                periodEnd: progressData.period_end
            });

            this.state.periodStart = progressData.period_start;
            this.state.periodEnd = progressData.period_end;

            const lineData = progressData.line_data || {};
            const paceData = progressData.pace_data || {};
            const subjectColors = progressData.subject_colors || {};
            
            this.state.paceData = paceData;
            this.state.paceForToday = this.calculatePaceForToday(paceData);

            const datasets = [];
            const today = new Date().toISOString().split('T')[0];

            for (const [subjectId, dataPoints] of Object.entries(lineData)) {
                if (!dataPoints || dataPoints.length === 0) continue;

                const subjectIdNum = parseInt(subjectId);
                const subjectName = this.cleanSubjectName(dataPoints[0].subject_name);
                const color = subjectColors[subjectIdNum];

                const sortedPoints = dataPoints.sort((a, b) => a.date.localeCompare(b.date));

                datasets.push({
                    label: subjectName,
                    data: sortedPoints.map(p => ({ x: p.date, y: p.result_percent })),
                    ...this.getSubjectDatasetStyle(subjectName, color),
                    subjectId: subjectIdNum,
                });
            }

            datasets.sort((a, b) => {
                if (a.isPace && !b.isPace) return 1;
                if (!a.isPace && b.isPace) return -1;
                if (a.isPace && b.isPace) return 0;
                return a.label.localeCompare(b.label);
            });

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

            const barData = progressData.bar_data || [];
            this.state.progressBarData = barData
                .map(item => ({
                    subject_name: this.cleanSubjectName(item.subject_name),
                    progress: item.progress,
                    color: item.color,
                    subject_id: item.subject_id
                }))
                .sort((a, b) => a.subject_name.localeCompare(b.subject_name));

            this._debug('fetchProgressData: Processed datasets', {
                progressLineDatasets: this.state.progressLineData?.length,
                progressBarItems: this.state.progressBarData?.length
            });

        } catch (error) {
            console.error("Error fetching progress data:", error);
            this._debug('fetchProgressData: ERROR', error.message);
            this.state.progressLineData = [];
            this.state.progressBarData = [];
        }

        this.state.loadingProgress = false;
        this._debug('fetchProgressData: Complete, scheduling render with double RAF for Owl timing');
        // Double requestAnimationFrame ensures Owl has rendered the canvas
        // First RAF: current frame completes, Owl processes state change
        // Second RAF: Owl has rendered, canvas should be in DOM
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                this._debug('fetchProgressData: Double RAF fired, calling renderProgressCharts');
                this.renderProgressCharts();
            });
        });
    }

    /**
     * Calculate the average PACE percentage for today across all resources.
     */
    calculatePaceForToday(paceData) {
        if (!paceData || Object.keys(paceData).length === 0) {
            return 0;
        }

        const today = new Date();
        const paceValues = [];

        for (const [resourceId, pace] of Object.entries(paceData)) {
            if (!pace || !pace.start_date || !pace.end_date) continue;

            try {
                const startDate = new Date(pace.start_date);
                const endDate = new Date(pace.end_date);

                if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) continue;
                if (today < startDate || today > endDate) continue;

                const totalDays = (endDate - startDate) / (1000 * 60 * 60 * 24);
                if (totalDays <= 0) continue;

                const daysFromStart = (today - startDate) / (1000 * 60 * 60 * 24);
                const progressPercent = (daysFromStart / totalDays) * 100;
                paceValues.push(Math.max(0, Math.min(100, progressPercent)));
            } catch (error) {
                console.error("Error calculating PACE for today:", error);
            }
        }

        return paceValues.length > 0 
            ? paceValues.reduce((a, b) => a + b, 0) / paceValues.length 
            : 0;
    }

    /**
     * Calculate PACE line showing expected progress over time.
     */
    calculatePaceLine(startDateStr, endDateStr, periodStartStr, todayStr, resourceName) {
        try {
            const startDate = new Date(startDateStr);
            const endDate = new Date(endDateStr);
            const periodStart = new Date(periodStartStr);
            const today = new Date(todayStr);

            if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) return null;

            const totalDays = (endDate - startDate) / (1000 * 60 * 60 * 24);
            if (totalDays <= 0) return null;

            const paceData = [];

            const displayStart = periodStart > startDate ? periodStart : startDate;
            const daysFromStart = (displayStart - startDate) / (1000 * 60 * 60 * 24);
            const startProgress = (daysFromStart / totalDays) * 100;

            paceData.push({
                x: displayStart.toISOString().split('T')[0],
                y: Math.max(0, Math.min(100, startProgress))
            });

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
                pointHoverRadius: 0,
                pointHitRadius: 0,
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
     */
    renderProgressCharts() {
        this._debug('renderProgressCharts: Called');
        this.renderProgressLineChart();
        this.renderProgressBarChart();
    }

    /**
     * Render the progress line chart showing progress over time.
     */
    renderProgressLineChart() {
        const canvas = this.component.__owl__.refs?.progressLineChart;
        const hasData = this.state.progressLineData?.length > 0;
        
        this._debug('renderProgressLineChart:', {
            canvasExists: !!canvas,
            canvasConnected: canvas?.isConnected,
            canvasSize: canvas ? `${canvas.offsetWidth}x${canvas.offsetHeight}` : 'N/A',
            hasData: hasData,
            datasetCount: this.state.progressLineData?.length || 0,
            existingInstance: !!this.progressLineChartInstance
        });
        
        if (!canvas || !hasData) {
            this._debug('renderProgressLineChart: Skipping - no canvas or no data');
            return;
        }

        if (this.progressLineChartInstance) {
            this._debug('renderProgressLineChart: Destroying existing instance');
            this.progressLineChartInstance.destroy();
            this.progressLineChartInstance = null;
        }

        const periodStartTs = this.state.periodStart ? new Date(this.state.periodStart).getTime() : null;
        const periodEndTs = this.state.periodEnd ? new Date(this.state.periodEnd).getTime() : null;

        const datasetsWithTimestamps = this.state.progressLineData.map(dataset => ({
            ...dataset,
            data: dataset.data.map(point => ({
                x: new Date(point.x).getTime(),
                y: point.y
            }))
        }));

        this.progressLineChartInstance = new Chart(canvas, {
            type: 'line',
            data: { datasets: datasetsWithTimestamps },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { usePointStyle: true, padding: 15 }
                    },
                    title: { display: false },
                    tooltip: {
                        enabled: true,
                        filter: (tooltipItem) => !tooltipItem.dataset.isPace,
                        callbacks: {
                            title: (context) => {
                                const date = new Date(context[0].parsed.x);
                                return date.toLocaleDateString('en-US', { 
                                    year: 'numeric', month: 'short', day: 'numeric' 
                                });
                            },
                            label: (context) => {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
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
                        min: periodStartTs,
                        max: periodEndTs,
                        title: { display: true, text: 'Date' },
                        ticks: {
                            maxRotation: 45,
                            minRotation: 0,
                            callback: function(value) {
                                const date = new Date(value);
                                return `${date.toLocaleString('en', { month: 'short' })} ${date.getDate()}`;
                            }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: { display: true, text: 'Progress (%)' },
                        ticks: { callback: (value) => value + '%' }
                    }
                }
            }
        });
        this._debug('renderProgressLineChart: Chart created successfully');
    }

    /**
     * Render the progress bar chart showing current progress by subject.
     */
    renderProgressBarChart() {
        const canvas = this.component.__owl__.refs?.progressBarChart;
        const hasData = this.state.progressBarData?.length > 0;
        
        this._debug('renderProgressBarChart:', {
            canvasExists: !!canvas,
            canvasConnected: canvas?.isConnected,
            canvasSize: canvas ? `${canvas.offsetWidth}x${canvas.offsetHeight}` : 'N/A',
            hasData: hasData,
            itemCount: this.state.progressBarData?.length || 0,
            existingInstance: !!this.progressBarChartInstance
        });
        
        if (!canvas || !hasData) {
            this._debug('renderProgressBarChart: Skipping - no canvas or no data');
            return;
        }

        if (this.progressBarChartInstance) {
            this._debug('renderProgressBarChart: Destroying existing instance');
            this.progressBarChartInstance.destroy();
            this.progressBarChartInstance = null;
        }

        const labels = this.state.progressBarData.map(item => item.subject_name);
        const data = this.state.progressBarData.map(item => item.progress);
        const colors = this.state.progressBarData.map(item => item.color);
        const paceForToday = this.state.paceForToday;

        this.progressBarChartInstance = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Current Progress',
                    data: data,
                    backgroundColor: colors.map(c => c + '80'),
                    borderColor: colors,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                layout: { padding: { top: 30 } },
                plugins: {
                    legend: { display: false },
                    title: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => 'Progress: ' + Math.round(context.parsed.x) + '%'
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        max: 100,
                        title: { display: true, text: 'Progress (%)' },
                        ticks: { callback: (value) => value + '%' }
                    },
                    y: { title: { display: false } }
                }
            },
            plugins: [{
                id: 'paceLine',
                afterDatasetsDraw: (chart) => {
                    if (!paceForToday) return;

                    const ctx = chart.ctx;
                    const xScale = chart.scales.x;
                    const yScale = chart.scales.y;
                    const xPixel = xScale.getPixelForValue(paceForToday);

                    ctx.save();
                    ctx.strokeStyle = '#808080';
                    ctx.lineWidth = 2;
                    ctx.setLineDash([5, 5]);
                    ctx.beginPath();
                    ctx.moveTo(xPixel, yScale.top);
                    ctx.lineTo(xPixel, yScale.bottom);
                    ctx.stroke();
                    ctx.restore();

                    ctx.save();
                    ctx.font = 'bold 12px sans-serif';
                    ctx.fillStyle = '#808080';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'bottom';
                    ctx.fillText(`PACE: ${Math.round(paceForToday)}%`, xPixel, yScale.top - 5);
                    ctx.restore();
                }
            }]
        });
        this._debug('renderProgressBarChart: Chart created successfully');
    }

    /**
     * Fetch student comparison data from backend.
     */
    async fetchStudentComparisonData() {
        this._debug('fetchStudentComparisonData: Starting');
        this.state.loadingStudentComparison = true;
        
        // Destroy existing chart instance - canvas will be removed from DOM during loading
        if (this.studentComparisonChartInstance) {
            this.studentComparisonChartInstance.destroy();
            this.studentComparisonChartInstance = null;
        }

        try {
            this._debug('fetchStudentComparisonData: Calling ORM...');
            const comparisonData = await this.orm.call(
                "aps.resource.submission",
                "get_student_comparison_data",
                []
            );
            
            this._debug('fetchStudentComparisonData: ORM returned', {
                hasStudentData: !!comparisonData.student_data,
                studentCount: (comparisonData.student_data || []).length,
                hasSubjectList: !!comparisonData.subject_list,
                subjectCount: (comparisonData.subject_list || []).length,
                paceAverage: comparisonData.pace_average,
                excludeFromAverage: comparisonData.exclude_from_average
            });

            const studentData = comparisonData.student_data || [];
            const subjectList = comparisonData.subject_list || [];
            const paceAverage = comparisonData.pace_average || 0;
            const excludeFromAverage = comparisonData.exclude_from_average || [];

            studentData.sort((a, b) => a.student_name.localeCompare(b.student_name));

            const studentLabels = studentData.map(student => student.student_name);
            const datasets = [];

            const sortedSubjects = subjectList
                .map(subject => ({ ...subject, name: this.cleanSubjectName(subject.name) }))
                .sort((a, b) => a.name.localeCompare(b.name));
            
            // Build a set of subject IDs to exclude from average calculation
            // Match by cleaned subject name (case-insensitive)
            const excludedSubjectIds = new Set();
            const excludeNamesLower = excludeFromAverage.map(name => 
                this.cleanSubjectName(name).toLowerCase()
            );
            for (const subject of sortedSubjects) {
                if (excludeNamesLower.includes(subject.name.toLowerCase())) {
                    excludedSubjectIds.add(subject.id);
                    this._debug('fetchStudentComparisonData: Excluding from average:', subject.name);
                }
            }

            // Average progress per student (excluding specified subjects)
            const averageData = studentData.map(student => {
                const progresses = [];
                for (const [subjectId, value] of Object.entries(student.progress_by_subject)) {
                    if (value != null && !excludedSubjectIds.has(parseInt(subjectId))) {
                        progresses.push(value);
                    }
                }
                if (!progresses.length) return null;
                return progresses.reduce((a, b) => a + b, 0) / progresses.length;
            });

            datasets.push({
                label: 'Average',
                data: averageData,
                borderColor: '#404040d3',
                backgroundColor: 'transparent',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 2,
                borderDash: [16, 8],
                tension: 0.3,
                fill: false,
                order: 1
            });

            sortedSubjects.forEach(subject => {
                const dataPoints = studentData.map(student => 
                    student.progress_by_subject[subject.id] ?? null
                );

                datasets.push({
                    label: subject.name,
                    data: dataPoints,
                    ...this.getSubjectDatasetStyle(subject.name, subject.color),
                    subjectId: subject.id
                });
            });

            if (paceAverage > 0) {
                datasets.push({
                    label: 'PACE (Expected)',
                    data: studentData.map(() => paceAverage),
                    borderColor: '#a1a1a1',
                    backgroundColor: 'rgba(128, 128, 128, 0.15)',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    pointHitRadius: 0,
                    fill: 'origin',
                    spanGaps: true,
                    isPace: true
                });
            }

            this.state.studentComparisonData = {
                labels: studentLabels,
                datasets: datasets,
                paceAverage: paceAverage
            };

            this._debug('fetchStudentComparisonData: Processed', {
                labels: this.state.studentComparisonData?.labels?.length,
                datasets: this.state.studentComparisonData?.datasets?.length
            });

        } catch (error) {
            console.error("Error fetching student comparison data:", error);
            this._debug('fetchStudentComparisonData: ERROR', error.message);
            this.state.studentComparisonData = { labels: [], datasets: [], paceAverage: 0 };
        }

        this.state.loadingStudentComparison = false;
        this._debug('fetchStudentComparisonData: Complete, scheduling render with double RAF for Owl timing');
        // Double requestAnimationFrame ensures Owl has rendered the canvas
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                this._debug('fetchStudentComparisonData: Double RAF fired, calling renderStudentComparisonChart');
                this.renderStudentComparisonChart();
            });
        });
    }

    /**
     * Render the student comparison chart.
     */
    renderStudentComparisonChart() {
        const canvas = this.component.__owl__.refs?.studentComparisonChart;
        const hasData = this.state.studentComparisonData?.datasets?.length > 0;
        
        this._debug('renderStudentComparisonChart:', {
            canvasExists: !!canvas,
            canvasConnected: canvas?.isConnected,
            canvasSize: canvas ? `${canvas.offsetWidth}x${canvas.offsetHeight}` : 'N/A',
            hasData: hasData,
            datasetCount: this.state.studentComparisonData?.datasets?.length || 0,
            labelCount: this.state.studentComparisonData?.labels?.length || 0,
            existingInstance: !!this.studentComparisonChartInstance,
            isFaculty: this.state.isFaculty
        });
        
        if (!canvas || !hasData) {
            this._debug('renderStudentComparisonChart: Skipping - no canvas or no data');
            return;
        }
        
        // Additional check: canvas must be connected to DOM and have dimensions
        if (!canvas.isConnected || canvas.offsetWidth === 0 || canvas.offsetHeight === 0) {
            this._debug('renderStudentComparisonChart: Skipping - canvas not connected or zero size, will retry via renderIfNeeded');
            return;
        }

        if (this.studentComparisonChartInstance) {
            this._debug('renderStudentComparisonChart: Destroying existing instance');
            this.studentComparisonChartInstance.destroy();
            this.studentComparisonChartInstance = null;
        }

        this.studentComparisonChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: this.state.studentComparisonData.labels,
                datasets: this.state.studentComparisonData.datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { usePointStyle: true, padding: 15 }
                    },
                    title: { display: false },
                    tooltip: {
                        enabled: true,
                        filter: (tooltipItem) => !tooltipItem.dataset.isPace,
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
                        offset: true,
                        title: { display: false },
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45,
                            callback: function(value) {
                                const label = this.getLabelForValue(value);
                                const maxChars = 15;
                                if (label.length <= maxChars) return label;
                                
                                const words = label.split(' ');
                                const lines = [];
                                let line = '';
                                words.forEach(word => {
                                    if ((line + ' ' + word).trim().length > maxChars) {
                                        if (line) lines.push(line);
                                        line = word;
                                    } else {
                                        line = line ? line + ' ' + word : word;
                                    }
                                });
                                if (line) lines.push(line);
                                return lines;
                            }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: { display: true, text: 'Progress (%)' },
                        ticks: { callback: (value) => value + '%' }
                    }
                }
            }
        });
        this._debug('renderStudentComparisonChart: Chart created successfully');
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

