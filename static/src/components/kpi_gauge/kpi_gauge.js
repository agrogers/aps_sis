import { Component, useRef, onMounted, onWillStart, onWillUnmount } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class KpiGauge extends Component {
    static template = "apex_dashboard.KpiGauge";
    static props = {
        name: { type: String, optional: true },
        value: { type: [Number, String], optional: true },
        max: { type: [Number, String], optional: true },
        zones: { type: Array, optional: true },
        points_from_next: { type: [Number, String], optional: true },
        total_students: { type: [Number, String], optional: true },
        icon: { type: String, optional: true },
        period_name: { type: String, optional: true },
        onClick: { type: Function, optional: true },
        percentage: { type: [Number, String], optional: true },
    };

    setup() {
        this.canvasRef = useRef("gaugeCanvas");
        const resizeHandler = () => this.renderGauge();
        
        onWillStart(async () => {
            // Ensure Chart.js is loaded
            await loadJS("/aps_sis/static/src/lib/chart.js");
            // await loadJS("https://unpkg.com/chart.js");
        });
        
        onMounted(() => {
            this.renderGauge();
            // Re-render on window resize
            window.addEventListener("resize", resizeHandler);
        });

        onWillUnmount(() => {
            // Clean up event listener
            window.removeEventListener("resize", resizeHandler);
        });
    }

    renderGauge() {
        if (!this.canvasRef.el) {
            return;
        }

        const value = parseInt(this.props.value || 0, 10);
        const max = parseInt(this.props.max || 10, 10);
        let zones = this.props.zones || [];
        const segmentData = [];
        const segmentColors = [];
        let filledValue = 0;
        let zoneSize = 0;
        let finalColor = '';
        let offset = 0;

        let needlePlugin = null;
        let pointerColor = '#464646';
        let maxValue = Math.max(1, max);
        let centreAdjustment = 0; // default to no adjustment

        if (this.props.name === 'Rank' || this.props.name === 'Points') {
            let maxSegments=0;
            if (this.props.name === 'Points') {
                maxSegments = 4;  // restrict segments to 10 for points to maintain consistent color zones
            } else {
                maxSegments = Math.max(1, max);
            }
            let color = 0;
            let filledAmount = 1;
            centreAdjustment = 180 / maxSegments / 2; // Adjust to point to the center of the segment

            for (let i = 0; i < maxSegments; i++) {
                
                if (this.props.name === 'Rank') {
                    const ratio = maxValue === 1 ? 1 : 1 - (i / (maxValue - 1));
                    const minGreen = 80;
                    const maxGreen = 255;
                    const green = Math.round(minGreen + (maxGreen - minGreen) * ratio);
                    color = `rgb(0, ${green}, 0)`;
                    if (value > (i/(maxSegments - 1) * maxValue)) {
                        pointerColor = color; // Update pointer color to match the current zone
                    }
                    
                } else { // Points
                    centreAdjustment = 0;
                    const ratio = i / (maxSegments - 1);
                    const minGreen = 30;
                    const maxGreen = 200;
                    const minBlue = 80;
                    const maxBlue = 255;
                    const blue = Math.round(minBlue + (maxBlue - minBlue) * ratio);
                    const green = Math.round(minGreen + (maxGreen - minGreen) * ratio);
                    color = `rgb(0, ${green}, ${blue})`;
                    if (value >= (max * (i / (maxSegments - 1)))) {
                        pointerColor = color; // Update pointer color to match the current zone
                    }

                }
                
                zones.push({ color, min: i, max: i + 1, label: `${i}` });
            }
            
            zones.forEach(zone => {
                segmentData.push(1);
                segmentColors.push(zone.color);
                filledValue += filledAmount;
            });
            


        } else {
            // Define color zones: gold (0-2), orange (3-5), red (6-10)
            zones = [
                { color: '#fde402', min: 0, max: 2, label: 'Safe' },        // Gold
                { color: '#FF9800', min: 3, max: 5, label: 'Warning' },     // Orange
                { color: '#F44336', min: 6, max: 10, label: 'Critical' }    // Red
            ];
            // Calculate segment sizes based on current value

            zones.forEach(zone => {
                if (zone.min === 0) {
                    offset = 0;
                    zoneSize = zone.max - zone.min; // total size of this range
                } else {
                    offset = 1;
                    zoneSize = zone.max - zone.min + offset; // total size of this range
                }
                let filledAmount = 0;

                if (value > zone.max) {
                    // Zone is completely filled
                    filledAmount = zoneSize;
                } else if (value >= zone.min) {
                    // Zone is partially filled
                    filledAmount = value - zone.min + offset;
                }
                // else zone is not filled at all (filledAmount = 0)
                if (filledAmount > 0) {
                    finalColor = zone.color; // Update final color based on last filled zone
                };
                if (filledAmount > 0) { 
                    pointerColor = zone.color; // Update pointer color to match the current zone
                };
                segmentData.push(filledAmount);
                segmentColors.push(zone.color);

                filledValue += filledAmount;
            });

            // Add gray for the remainder
            const remainingValue = max - filledValue;
            if (remainingValue > 0) {
                segmentData.push(remainingValue);
                segmentColors.push('#E0E0E0'); // Gray
            }
        }


        if (!isNaN(value)) {
            //Add a speedometer-style needle for rank
            const needleValue = Math.min(value, maxValue);
            let needleAngle = 0;
            needleAngle = (needleValue / maxValue) * 180 - 180 - centreAdjustment; // Adjust angle to point to the center of the segment
            
            // Handle edge cases where needle might go beyond the gauge limits
            if (needleAngle > -4) {
                needleAngle = -4;
            } else if (needleAngle < -176) {
                needleAngle = -176;
            };
            needlePlugin = {
                id: 'needle',
                afterDraw(chart) {  
                    const {ctx, chartArea: {left, top, width, height}} = chart;
                    const centerX = left + width / 2;
                    const centerY = top + height / 1;
                    const needleLength = Math.min(width, height) / 1 * 0.8;
                    const needleStartRatio = 4 / 5;
                    const needleX = centerX + needleLength * 1.1 * Math.cos(needleAngle * Math.PI / 180);
                    const needleY = centerY + needleLength * 1.1 * Math.sin(needleAngle * Math.PI / 180);
                    const needleStartX = centerX + needleLength * needleStartRatio * Math.cos(needleAngle * Math.PI / 180);
                    const needleStartY = centerY + needleLength * needleStartRatio * Math.sin(needleAngle * Math.PI / 180);

                    ctx.save();
                    let circelradius1 = 0;
                    let circelradius2 = 0;
                    for (let i = 0; i < 2; i++) {
                        if (i === 0) {
                            ctx.lineWidth = 6;
                            ctx.strokeStyle = '#FFFFFF'; // White border for better visibility
                            ctx.fillStyle = '#FFFFFF';
                            circelradius1 = 9;
                            circelradius2 = 5;
                        } else {
                            ctx.lineWidth = 4;
                            ctx.strokeStyle = pointerColor; // Needle color
                            ctx.fillStyle = pointerColor;
                            circelradius1 = 7;
                            circelradius2 = 3;
                        }
                        ctx.beginPath();
                        ctx.moveTo(needleStartX, needleStartY);
                        ctx.lineTo(needleX, needleY);
                        ctx.stroke();
                        
                        // Draw circle at the end of the needle
                        ctx.beginPath();
                        ctx.arc(needleX, needleY, circelradius1, 0, 2 * Math.PI);
                        ctx.fill();

                        // Draw circle at the end of the needle
                        ctx.beginPath();
                        ctx.arc(needleStartX, needleStartY, circelradius2, 0, 2 * Math.PI);
                        ctx.fill();
                        
                        ctx.restore();
                    }
                }   
            };
        }

        // Custom plugin to draw center text
        const gaugeTextPlugin = {
            id: 'gaugeText',
            afterDraw(chart) {
                const {ctx, chartArea: {left, top, width, height}} = chart;
                const centerX = left + width / 2;
                const centerY = top + height / 1;
                let textValue = value;
                if (isNaN(value)) {
                    textValue = "-";
                }

                ctx.save();
                ctx.font = 'bold 45px Arial';
                if (textValue === 0) {
                    ctx.fillStyle = '#000';
                } else {
                    ctx.fillStyle = finalColor;
                }
                
                ctx.textAlign = 'center';
                ctx.textBaseline = 'bottom';
                ctx.fillText(textValue, centerX, centerY);
                ctx.restore();
            }
        };

        const ctx = this.canvasRef.el.getContext('2d');
        
        // Destroy existing chart if any
        if (this.chart) {
            this.chart.destroy();
        }

        const chartPlugins = needlePlugin ? [gaugeTextPlugin, needlePlugin] : [gaugeTextPlugin];

        this.chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                datasets: [{
                    data: segmentData,
                    backgroundColor: segmentColors,
                    borderWidth: 0,
                    circumference: 180,
                    rotation: 270,
                    cutout: '80%'
                }]
            },
            options: {
                responsive: true,
                aspectRatio: 2,
                maintainAspectRatio: true,
                animation: {
                    duration: 1500,
                    easing: 'easeInOutQuart'
                },
                layout: {
                    padding: {
                        top: 0,
                        bottom: 0,
                        left: 0,
                        right: 0
                    }
                },
                plugins: {
                    tooltip: {
                        enabled: false,
                        callbacks: {
                            label(context) {
                                const label = context.dataIndex === segmentData.length - 1 ? "Remaining" : "Range";
                                const value = context.raw ?? 0;
                                return `${label}: ${value}`;
                            }
                        }
                    },
                    legend: { display: false }
                }
            },
            plugins: chartPlugins
        });
    }
}

KpiGauge.template = "apex_dashboard.KpiGauge";
