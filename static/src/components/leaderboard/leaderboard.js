import { Component } from "@odoo/owl";

export class Leaderboard extends Component {
    static template = "apex_dashboard.Leaderboard";
    static props = {
        entries: { type: Array, optional: true },
        displayLimit: { type: Number, optional: true },
        valueSuffix: { type: String, optional: true },
        isFaculty: { type: Boolean, optional: true },
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
        return avatarUrl || '/web/static/img/placeholder.png';
    }
}
