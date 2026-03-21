import { Component } from "@odoo/owl";

export class Leaderboard extends Component {
    static template = "apex_dashboard.Leaderboard";
    static props = {
        entries: { type: Array, optional: true },
        displayLimit: { type: Number, optional: true },
        valueSuffix: { type: String, optional: true },
        isFaculty: { type: Boolean, optional: true },
        // trackMode: 'default' (plain grey), 'progress' (3-zone coloured), 'completion' (gradient)
        trackMode: { type: String, optional: true },
        // Used only for trackMode === 'progress'
        redlinePercent: { type: Number, optional: true },
        pacePercent: { type: Number, optional: true },
    };

    // Returns entries sorted rank-N first, rank-1 last (left → right display order).
    get displayEntries() {
        const limit = this.props.displayLimit ?? 15;
        const sorted = [...(this.props.entries || [])]
            .sort((a, b) => a.rank - b.rank)
            .slice(0, limit);
        return sorted.reverse();
    }

    // Proportional flex-grow values for the spacers between entries.
    // spacerWeights[i] sits between displayEntries[i] and displayEntries[i+1].
    get spacerWeights() {
        const entries = this.displayEntries;
        if (entries.length <= 1) return [];
        const weights = [];
        for (let i = 0; i < entries.length - 1; i++) {
            // entries are rank-descending so entries[i+1] has MORE points.
            const diff = entries[i + 1].total_points - entries[i].total_points;
            weights.push(Math.max(1, diff));
        }
        return weights;
    }

    // Border / ring colour for each rank position.
    getRingColor(rank) {
        const palette = {
            1: "#3498db", // Blue  – 1st place
            2: "#e74c3c", // Red   – 2nd place
            3: "#FFD700", // Gold  – 3rd place
        };
        return palette[rank] || "#adb5bd"; // Grey for 4th / 5th
    }

    getRingLabel(rank) {
        const labels = { 1: "🥇", 2: "🥈", 3: "🥉" };
        return labels[rank] || `#${rank}`;
    }

    // Image URL based on viewer role and available images.
    // Students see game avatars; teachers see partner photos (with avatar fallback).
    getImageUrl(entry) {
        const avatarUrl = entry.avatar_id
            ? `/web/image/aps.avatar/${entry.avatar_id}/image/128x128`
            : false;
        const partnerUrl = `/web/image/res.partner/${entry.student_id}/image_128`;

        if (this.props.isFaculty) {
            if (entry.has_image) return partnerUrl;
            return avatarUrl || partnerUrl;
        }
        return avatarUrl || partnerUrl;
    }

    // CSS value for the --track-bg custom property on the track element.
    // Returns a solid colour or linear-gradient string, or '' for the default grey.
    get trackBg() {
        const mode = this.props.trackMode;
        if (!mode || mode === 'default') return '';

        const entries = this.displayEntries;
        if (entries.length === 0) return '';

        // Leftmost entry is index 0 (lowest %, worst rank displayed on the left).
        // Rightmost entry is the last index (highest %, rank 1 displayed on the right).
        const minPct = entries[0].total_points;
        const maxPct = entries[entries.length - 1].total_points;
        // Guard against all students sharing the same value.
        const range = maxPct - minPct || 1;

        // Convert an absolute value to its relative position within the visible track.
        // Clamped version keeps the result within [0–100%] so thresholds outside the
        // visible range snap to the track edge rather than bleeding off it.
        const toRelClamped = (val) => Math.max(0, Math.min(100, ((val - minPct) / range) * 100));
        // Unclamped version lets CSS handle positions outside the track naturally,
        // which produces the correct visible slice of a wider gradient.
        const toRelUnclamped = (val) => ((val - minPct) / range) * 100;

        if (mode === 'progress') {
            const redline = this.props.redlinePercent ?? 0;
            const pace = this.props.pacePercent ?? 0;
            const redlineRel = toRelClamped(redline).toFixed(1);
            const paceRel = toRelClamped(pace).toFixed(1);

            // Three colour zones: red → dark-grey → light-grey.
            return `linear-gradient(to right,` +
                ` #dc3545 0%, #dc3545 ${redlineRel}%,` +
                ` #495057 ${redlineRel}%, #495057 ${paceRel}%,` +
                ` #dee2e6 ${paceRel}%, #dee2e6 100%)`;
        }

        if (mode === 'completion') {
            // Global colour stops anchored to absolute progress percentages.
            // CSS handles stop positions outside [0%, 100%] gracefully — it clamps
            // the edge colour — so negative or >100 values produce the correct slice.
            const stops = [
                { pct: 0,   color: '#dc3545' },   // red
                { pct: 30,  color: '#fd7e14' },   // orange
                { pct: 60,  color: '#ffc107' },   // yellow
                { pct: 100, color: '#28a745' },   // green
            ];

            const gradientStops = stops
                .map(s => `${s.color} ${toRelUnclamped(s.pct).toFixed(1)}%`)
                .join(', ');
            return `linear-gradient(to right, ${gradientStops})`;
        }

        return '';
    }
}
