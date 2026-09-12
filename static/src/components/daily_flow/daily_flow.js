import { Component } from "@odoo/owl";

export class DailyFlow extends Component {
    static template = "aps_sis.DailyFlow";
    static props = {
        days: { type: Array, optional: true },
        subjects: { type: Array, optional: true },
        scale: { type: Object, optional: true },
        loading: { type: Boolean, optional: true },
        emptyMessage: { type: String, optional: true },
        showLegend: { type: Boolean, optional: true },
        showMetrics: { type: Boolean, optional: true },
        showDayLabels: { type: Boolean, optional: true },
        singleColumn: { type: Boolean, optional: true },
        onEntryClick: { type: Function, optional: true },
    };

    static defaultProps = {
        days: [],
        subjects: [],
        scale: { start: "", end: "", labels: [] },
        loading: false,
        emptyMessage: "No recorded time for this period.",
        showLegend: true,
        showMetrics: true,
        showDayLabels: true,
        singleColumn: false,
    };

    setup() {
        this._handleEntryClick = this._handleEntryClick.bind(this);
    }

    _dateValue(value) {
        if (!value) return 0;
        return new Date(String(value).replace(" ", "T")).getTime();
    }

    _formatDuration(minutes) {
        const value = Math.max(0, Math.round(Number(minutes) || 0));
        const hours = Math.floor(value / 60);
        const rest = value % 60;
        return hours ? `${hours}h ${String(rest).padStart(2, "0")}m` : `${rest}m`;
    }

    _formatHours(hours) {
        return this._formatDuration(Number(hours || 0) * 60);
    }

    _totalHours(subjects) {
        return (subjects || []).reduce((total, subject) => total + (Number(subject.hours) || 0), 0);
    }

    _formatPercent(value) {
        if (value === false || value === null || value === undefined) return "—";
        const number = Number(value) || 0;
        return `${number > 0 ? "+" : ""}${number.toFixed(0)}%`;
    }

    _formatTime(value) {
        if (!value) return "";
        const text = String(value);
        const timePart = text.includes("T") ? text.split("T")[1] : text.split(" ")[1] || text;
        const [hoursText, minutesText] = timePart.split(":");
        const hours = Number(hoursText);
        if (!Number.isFinite(hours)) return text;
        const suffix = hours >= 12 ? "p" : "a";
        const displayHours = hours % 12 || 12;
        return `${displayHours}:${String(minutesText || "00").padStart(2, "0")}${suffix}`;
    }

    _formatDeltaHours(value) {
        const number = Number(value) || 0;
        return `${number > 0 ? "+" : ""}${number.toFixed(1)}h`;
    }

    _subjectTooltip(subject) {
        return subject.name || "Subject";
    }

    _dayTooltip(day, comparison) {
        const label = comparison === "previous"
            ? "Compared with the same day one week earlier"
            : "Compared with the average time recorded by all users for this day over the selected dashboard period";
        const value = comparison === "previous"
            ? day.previous_total_minutes
            : day.average_minutes;
        return `${label}\nBaseline: ${this._formatDuration(value)}\nChange: ${this._formatPercent(
            comparison === "previous" ? day.previous_percent : day.average_percent
        )}`;
    }

    _comparisonClass(value) {
        if (value === false || value === null || value === undefined || Number(value) === 0) {
            return "is-neutral";
        }
        return Number(value) > 0 ? "is-positive" : "is-negative";
    }

    _timelineStyle(entry) {
        const start = this._dateValue(this.props.scale.start);
        const end = this._dateValue(this.props.scale.end);
        const duration = Math.max(end - start, 60 * 60000);
        const entryStart = this._dateValue(entry.position_start || entry.start_time);
        const entryStop = this._dateValue(entry.position_stop || entry.stop_time);
        const top = ((entryStart - start) / duration) * 100;
        const height = Math.max(1.6, ((entryStop - entryStart) / duration) * 100);
        const safeTop = Math.max(0, Math.min(100, top));
        return `top: ${safeTop}%; height: ${Math.min(100 - safeTop, height)}%; --segment-color: ${entry.color || "#64748b"};`;
    }

    _pauseStyle(entry) {
        const elapsed = Math.max(
            1,
            this._dateValue(entry.position_stop || entry.stop_time)
                - this._dateValue(entry.position_start || entry.start_time)
        );
        const pause = Math.min(elapsed, Math.max(0, Number(entry.pause_minutes) || 0) * 60000);
        const height = (pause / elapsed) * 100;
        return `height: ${Math.max(4, height)}%; top: ${50 - Math.max(2, height / 2)}%;`;
    }

    _entryTitle(entry) {
        return `${entry.subject_name}\n${this._formatTime(entry.start_time)} – ${this._formatTime(entry.stop_time)}\n${this._formatDuration(entry.total_minutes)}`;
    }

    _handleEntryClick(ev) {
        const dayDate = ev.currentTarget.dataset.dayDate;
        const entryId = String(ev.currentTarget.dataset.entryId);
        const day = this.props.days.find((item) => item.date === dayDate);
        const entry = day?.entries.find((item) => String(item.id) === entryId);
        if (this.props.onEntryClick) {
            return this.props.onEntryClick(entry);
        }
    }
}
