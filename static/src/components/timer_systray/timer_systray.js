import { Component, useState, useRef, onMounted, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { DailyFlow } from "@aps_sis/components/daily_flow/daily_flow";

// ─── Stop Timer Dialog ────────────────────────────────────────────────────────

export class TimerStopDialog extends Component {
    static template = "aps_sis.TimerStopDialog";
    static components = { Dialog };
    static props = {
        entry: { type: Object },
        subjects: { type: Array },
        partnerId: { type: Number },
        partnerName: { type: String },
        onSave: { type: Function },
        onDiscard: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        const subjectId = Array.isArray(this.props.entry.subject_id)
            ? this.props.entry.subject_id[0]
            : (this.props.entry.subject_id || false);
        // datetime-local inputs need "T" separator; strip seconds for step=60
        const startTime = (this.props.entry.start_time || "").replace(" ", "T").slice(0, 16);
        const stopTime = (this.props.entry.stop_time || "").replace(" ", "T").slice(0, 16);
        this.state = useState({
            subject_id: subjectId,
            start_time: startTime,
            stop_time: stopTime,
            notes: this.props.entry.notes || "",
            pause_minutes: this.props.entry.pause_minutes || 0,
            is_outside_school_hours: this.props.entry.is_outside_school_hours || false,
            total_minutes: this.props.entry.total_minutes || 0,
            subjectError: false,
            validationError: "",
        });
    }

    _recomputeDuration() {
        if (this.state.start_time && this.state.stop_time) {
            const start = new Date(this.state.start_time);
            const stop = new Date(this.state.stop_time);
            const diffMs = stop - start;
            if (diffMs > 0) {
                this.state.total_minutes = Math.round(Math.max(0, diffMs / 60000 - (parseFloat(this.state.pause_minutes) || 0)));
            } else {
                this.state.total_minutes = 0;
            }
        }
    }

    _offsetMs() {
        return ((parseFloat(this.state.total_minutes) || 0) + (parseFloat(this.state.pause_minutes) || 0)) * 60000;
    }

    _toLocal16(dt) {
        // Format a Date to "YYYY-MM-DDTHH:MM" in local time for datetime-local input
        const pad = (n) => String(n).padStart(2, "0");
        return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
    }

    _fillMissingTime() {
        // Mirror Python onchange('total_minutes', 'pause_minutes')
        if (this.state.total_minutes > 0) {
            const offsetMs = this._offsetMs();
            if (this.state.stop_time && !this.state.start_time) {
                this.state.start_time = this._toLocal16(new Date(new Date(this.state.stop_time).getTime() - offsetMs));
            } else if (this.state.start_time && !this.state.stop_time) {
                this.state.stop_time = this._toLocal16(new Date(new Date(this.state.start_time).getTime() + offsetMs));
            } else if (this.state.stop_time) {
                // Both exist — anchor on stop_time
                this.state.start_time = this._toLocal16(new Date(new Date(this.state.stop_time).getTime() - offsetMs));
            }
        }
    }

    onTimeChange(ev) {
        const field = ev.target.name; // "start_time" or "stop_time"
        // If both times now exist, recompute duration
        if (this.state.start_time && this.state.stop_time) {
            this._recomputeDuration();
        } else if (field === "start_time" && this.state.start_time && this.state.total_minutes > 0 && !this.state.stop_time) {
            // Mirror Python _onchange_start_time
            const offsetMs = this._offsetMs();
            this.state.stop_time = this._toLocal16(new Date(new Date(this.state.start_time).getTime() + offsetMs));
        } else if (field === "stop_time" && this.state.stop_time && this.state.total_minutes > 0 && !this.state.start_time) {
            // Mirror Python _onchange_stop_time
            const offsetMs = this._offsetMs();
            this.state.start_time = this._toLocal16(new Date(new Date(this.state.stop_time).getTime() - offsetMs));
        }
    }

    onDurationChange() {
        this._fillMissingTime();
    }

    onPauseChange() {
        // Changing pause should re-derive times just like duration change
        if (this.state.start_time && this.state.stop_time) {
            this._recomputeDuration();
        } else {
            this._fillMissingTime();
        }
    }

    _validate() {
        if (!this.state.subject_id) {
            this.state.subjectError = true;
            return "Please select a subject.";
        }
        this.state.subjectError = false;
        if (this.state.start_time && this.state.stop_time) {
            const start = new Date(this.state.start_time);
            const stop = new Date(this.state.stop_time);
            if (stop < start) {
                return "Stop time cannot be before start time.";
            }
            if ((stop - start) > 24 * 60 * 60 * 1000) {
                return "Start and stop time cannot be more than 24 hours apart.";
            }
        }
        return null;
    }

    async onSave() {
        const error = this._validate();
        if (error) {
            this.state.validationError = error;
            return;
        }
        this.state.validationError = "";
        // Convert local times back to UTC for Odoo
        const toUTC = (localStr) => {
            if (!localStr) return false;
            const dt = new Date(localStr.replace(" ", "T"));
            return dt.toISOString().replace("T", " ").slice(0, 19);
        };
        const vals = {
            subject_id: parseInt(this.state.subject_id),
            partner_id: this.props.partnerId,
            start_time: toUTC(this.state.start_time),
            stop_time: toUTC(this.state.stop_time),
            total_minutes: parseInt(this.state.total_minutes) || 0,
            date: this.state.start_time ? new Date(this.state.start_time).toISOString().slice(0, 10) : new Date().toISOString().slice(0, 10),
            notes: this.state.notes,
            pause_minutes: parseFloat(this.state.pause_minutes) || 0,
            is_outside_school_hours: this.state.is_outside_school_hours,
        };
        await this.orm.create("aps.time.tracking", [vals]);
        this.props.onSave();
        this.props.close();
    }

    onDiscard() {
        this.props.onDiscard();
        this.props.close();
    }
}

// ─── Enhanced Stop Timer Dialog ─────────────────────────────────────────────

export class EnhancedTimerStopDialog extends Component {
    static template = "aps_sis.EnhancedTimerStopDialog";
    static components = { Dialog, DailyFlow };
    static props = {
        entry: { type: Object },
        subjects: { type: Array },
        partnerId: { type: Number },
        partnerName: { type: String },
        onSave: { type: Function },
        onDiscard: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.startInput = useRef("startInput");
        this.stopInput = useRef("stopInput");
        this.onFixOverlap = this.onFixOverlap.bind(this);
        this.onTimelineClick = this.onTimelineClick.bind(this);
        this.state = useState({
            ...this._entryState(this.props.entry),
            entries: [],
            conflicts: [],
            loading: true,
            saving: false,
            validationError: "",
            subjectError: false,
            focusTimeFields: false,
        });
        this._validationSequence = 0;
        this._timelineSequence = 0;

        // Validate the initial interval before the dialog is first rendered so
        // an existing overlap is visible immediately, without requiring the
        // user to change one of the time fields first.
        onWillStart(() => this._validateOverlap());
        onMounted(() => this._refreshTimeline());
        onWillUnmount(() => {
            this._validationSequence += 1;
            this._timelineSequence += 1;
        });
    }

    _entryState(entry) {
        const subjectId = Array.isArray(entry.subject_id)
            ? entry.subject_id[0]
            : (entry.subject_id || false);
        return {
            id: entry.id || false,
            subject_id: subjectId,
            start_time: (entry.start_time || "").replace(" ", "T").slice(0, 16),
            stop_time: (entry.stop_time || "").replace(" ", "T").slice(0, 16),
            notes: entry.notes || "",
            pause_minutes: entry.pause_minutes || 0,
            is_outside_school_hours: entry.is_outside_school_hours || false,
            total_minutes: entry.total_minutes || 0,
        };
    }

    get selectedSubject() {
        return this.props.subjects.find(
            (subject) => Number(subject.id) === Number(this.state.subject_id)
        ) || null;
    }

    get timelineDate() {
        return this.state.start_time
            ? this.state.start_time.slice(0, 10)
            : this._localDate(new Date());
    }

    get timelineEntries() {
        const entries = this.state.entries.map((entry) => ({ ...entry, isDraft: false }));
        if (!this.state.start_time || !this.state.stop_time) {
            return entries;
        }
        const draft = this._draftTimelineEntry();
        const withoutCurrent = entries.filter((entry) => entry.id !== this.state.id);
        return [...withoutCurrent, draft].sort(
            (a, b) => this._dateValue(a.start_time) - this._dateValue(b.start_time)
        );
    }

    get timelineScale() {
        // Keep an empty day's scale anchored to school hours. The draft entry
        // being edited is intentionally excluded here; otherwise opening a
        // short entry before 8am or after 4pm would move the day's baseline
        // even when there are no other records to provide context.
        const values = this.state.entries
            .filter((entry) => Number(entry.id) !== Number(this.state.id))
            .flatMap((entry) => [
                this._dateValue(entry.start_time),
                this._dateValue(entry.stop_time),
            ])
            .filter(Boolean);
        const day = this.timelineDate;
        const fallbackStart = new Date(`${day}T08:00`).getTime();
        const fallbackStop = new Date(`${day}T16:00`).getTime();
        const padding = 30 * 60000;
        const start = values.length ? Math.min(fallbackStart, ...values) - padding : fallbackStart;
        const stop = values.length ? Math.max(fallbackStop, ...values) + padding : fallbackStop;
        return { start, stop, duration: Math.max(stop - start, 60 * 60000) };
    }

    get timelineLabels() {
        const scale = this.timelineScale;
        return [0, 0.5, 1].map((ratio) => ({
            label: this._formatTime(new Date(scale.start + scale.duration * ratio)),
            style: `top: ${ratio * 100}%`,
        }));
    }

    get dailyFlowScale() {
        const scale = this.timelineScale;
        const start = new Date(scale.start);
        const stop = new Date(scale.stop);
        const labels = this.timelineLabels.map((item) => ({
            value: item.label,
            label: item.label,
            ratio: parseFloat(item.style.match(/[\d.]+/)?.[0] || 0) / 100,
        }));
        return {
            start: start.toISOString(),
            end: stop.toISOString(),
            labels: labels.map((label, index) => ({
                ...label,
                value: `${index}-${label.value}`,
            })),
        };
    }

    get dailyFlowDays() {
        return [{
            date: this.timelineDate,
            label: "Today",
            short_date: this.timelineDate,
            total_minutes: this.timelineTotal,
            subject_count: new Set(this.timelineEntries.map((entry) => entry.subject_id)).size,
            entries: this.timelineEntries.map((entry) => ({
                ...entry,
                position_start: entry.start_time.replace(" ", "T"),
                position_stop: entry.stop_time.replace(" ", "T"),
            })),
        }];
    }

    get dailyFlowSubjects() {
        const subjects = new Map();
        for (const entry of this.timelineEntries) {
            if (!entry.subject_id || subjects.has(entry.subject_id)) continue;
            subjects.set(entry.subject_id, {
                id: entry.subject_id,
                name: entry.subject_name,
                color: entry.color || "#64748b",
                icon_url: entry.icon_url || false,
                hours: Number(entry.total_minutes || 0) / 60,
                delta_hours: 0,
                delta_percent: false,
            });
        }
        return [...subjects.values()];
    }

    get selectedSubjectColor() {
        return this.selectedSubject?.color || "#64748b";
    }

    get timelineTotal() {
        return this.timelineEntries.reduce(
            (sum, entry) => sum + Number(entry.total_minutes || 0),
            0
        );
    }

    _localDate(date) {
        const pad = (value) => String(value).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    }

    _dateValue(value) {
        if (!value) return 0;
        return new Date(String(value).replace(" ", "T")).getTime();
    }

    _formatTime(date) {
        return date.toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
            hour12: true,
        });
    }

    _formatDuration(minutes) {
        const value = Math.max(0, Math.round(Number(minutes) || 0));
        const hours = Math.floor(value / 60);
        const rest = value % 60;
        return hours ? `${hours}h ${String(rest).padStart(2, "0")}m` : `${rest}m`;
    }

    _timelineTooltip(entry) {
        const start = this._formatDateTime(entry.start_time);
        const stop = this._formatDateTime(entry.stop_time);
        const pause = Number(entry.pause_minutes) > 0
            ? `\nPause: ${this._formatDuration(entry.pause_minutes)}`
            : "";
        return `${entry.subject_name}\nStart: ${start}\nEnd: ${stop}${pause}`;
    }

    _formatDateTime(value) {
        if (!value) return "—";
        const date = new Date(String(value).replace(" ", "T"));
        return `${date.toLocaleDateString([], { month: "short", day: "numeric" })}, ${this._formatTime(date)}`;
    }

    _timelineStyle(entry) {
        const scale = this.timelineScale;
        const start = this._dateValue(entry.start_time);
        const stop = this._dateValue(entry.stop_time);
        const top = ((start - scale.start) / scale.duration) * 100;
        const height = Math.max(1.5, ((stop - start) / scale.duration) * 100);
        return `top: ${Math.max(0, top)}%; height: ${Math.min(100 - Math.max(0, top), height)}%; --segment-color: ${entry.color || "#64748b"};`;
    }

    onDailyFlowEntryClick(entry) {
        this.onTimelineClick({ currentTarget: { dataset: { entryId: entry.id } } });
    }

    _pauseStyle(entry) {
        const elapsed = Math.max(1, this._dateValue(entry.stop_time) - this._dateValue(entry.start_time));
        const pause = Math.min(elapsed, Math.max(0, Number(entry.pause_minutes) || 0) * 60000);
        const height = (pause / elapsed) * 100;
        return `height: ${Math.max(4, height)}%; top: ${50 - Math.max(2, height / 2)}%;`;
    }

    _draftTimelineEntry() {
        return {
            id: this.state.id || "draft",
            subject_id: this.state.subject_id,
            subject_name: this.selectedSubject?.name || "New entry",
            category_name: this.selectedSubject?.category_name || "",
            color: this.selectedSubjectColor,
            start_time: this.state.start_time.replace("T", " "),
            stop_time: this.state.stop_time.replace("T", " "),
            pause_minutes: Number(this.state.pause_minutes) || 0,
            total_minutes: Number(this.state.total_minutes) || 0,
            isDraft: true,
        };
    }

    async _refreshTimeline() {
        const sequence = ++this._timelineSequence;
        this.state.loading = true;
        const result = await this.orm.call(
            "aps.time.tracking",
            "get_timer_timeline",
            [this.timelineDate, this.props.partnerId],
            {}
        );
        if (sequence !== this._timelineSequence) return;
        this.state.entries = result.entries || [];
        this.state.loading = false;
    }

    async _validateOverlap() {
        const sequence = ++this._validationSequence;
        if (!this.state.start_time || !this.state.stop_time) {
            this.state.conflicts = [];
            return;
        }
        const result = await this.orm.call(
            "aps.time.tracking",
            "validate_timer_interval",
            [this.props.partnerId, this._toUTC(this.state.start_time), this._toUTC(this.state.stop_time), this.state.id || false],
            {}
        );
        if (sequence === this._validationSequence) {
            this.state.conflicts = result.conflicts || [];
        }
    }

    _toUTC(localValue) {
        if (!localValue) return false;
        return new Date(localValue.replace(" ", "T")).toISOString().replace("T", " ").slice(0, 19);
    }

    _recomputeDuration() {
        if (this.state.start_time && this.state.stop_time) {
            const diff = this._dateValue(this.state.stop_time) - this._dateValue(this.state.start_time);
            this.state.total_minutes = diff > 0
                ? Math.round(Math.max(0, diff / 60000 - (Number(this.state.pause_minutes) || 0)))
                : 0;
        }
    }

    _offsetMs() {
        return (Number(this.state.total_minutes || 0) + Number(this.state.pause_minutes || 0)) * 60000;
    }

    _toLocal16(date) {
        const pad = (value) => String(value).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    _fillMissingTime() {
        if (!Number(this.state.total_minutes)) return;
        if (this.state.stop_time && !this.state.start_time) {
            this.state.start_time = this._toLocal16(new Date(this._dateValue(this.state.stop_time) - this._offsetMs()));
        } else if (this.state.start_time && !this.state.stop_time) {
            this.state.stop_time = this._toLocal16(new Date(this._dateValue(this.state.start_time) + this._offsetMs()));
        }
    }

    async onTimeChange(ev) {
        const field = ev.target.name;
        if (this.state.start_time && this.state.stop_time) {
            this._recomputeDuration();
        } else if (field === "start_time" && this.state.total_minutes) {
            this._fillMissingTime();
        } else if (field === "stop_time" && this.state.total_minutes) {
            this._fillMissingTime();
        }
        await this._refreshTimeline();
        await this._validateOverlap();
    }

    async onDurationChange() {
        this._fillMissingTime();
        await this._refreshTimeline();
        await this._validateOverlap();
    }

    async onPauseChange() {
        if (this.state.start_time && this.state.stop_time) this._recomputeDuration();
        else this._fillMissingTime();
        await this._refreshTimeline();
    }

    async onSubjectChange() {
        this.state.subjectError = !this.state.subject_id;
        await this._refreshTimeline();
    }

    _validate() {
        if (!this.state.subject_id) {
            this.state.subjectError = true;
            return "Please select a subject.";
        }
        this.state.subjectError = false;
        if (!this.state.start_time || !this.state.stop_time) return "Start and stop times are required.";
        const diff = this._dateValue(this.state.stop_time) - this._dateValue(this.state.start_time);
        if (diff <= 0) return "Stop time must be after start time.";
        if (diff > 24 * 60 * 60 * 1000) return "Start and stop time cannot be more than 24 hours apart.";
        if (this.state.conflicts.length) return "Fix the overlapping time before saving.";
        return null;
    }

    onFixOverlap() {
        const conflict = this.state.conflicts[0];
        if (!conflict) return;

        const currentStart = this._dateValue(this.state.start_time);
        const currentStop = this._dateValue(this.state.stop_time);
        const conflictStart = this._dateValue(conflict.start_time);
        const conflictStop = this._dateValue(conflict.stop_time);
        const elapsed = Math.max(0, currentStop - currentStart);

        if (conflictStop < currentStop) {
            // The usual case: move the start to the end of the earlier entry.
            this.state.start_time = this._toLocal16(
                new Date(Math.max(currentStart, conflictStop))
            );
            if (this._dateValue(this.state.start_time) >= currentStop) {
                this.state.stop_time = this._toLocal16(
                    new Date(this._dateValue(this.state.start_time) + elapsed)
                );
            }
        } else if (conflictStart > currentStart) {
            // If the conflicting record is after this entry, shorten the end.
            this.state.stop_time = this._toLocal16(new Date(conflictStart));
        } else {
            // The existing record contains this entry; move the complete entry
            // after it while retaining the original elapsed duration.
            this.state.start_time = this._toLocal16(new Date(conflictStop));
            this.state.stop_time = this._toLocal16(new Date(conflictStop + elapsed));
        }
        this._recomputeDuration();
        this.state.focusTimeFields = true;
        this.state.validationError = "";
        void this._refreshTimeline();
        void this._validateOverlap();
        setTimeout(() => this.startInput.el?.focus(), 0);
    }

    async onTimelineClick(ev) {
        const entryId = Number(ev.currentTarget.dataset.entryId);
        const entry = this.timelineEntries.find((item) => Number(item.id) === entryId);
        if (!entry || entry.isDraft || !entry.id) return;
        this.dialog.add(EnhancedTimerStopDialog, {
            entry,
            subjects: this.props.subjects,
            partnerId: this.props.partnerId,
            partnerName: this.props.partnerName,
            onSave: async () => {
                await this._refreshTimeline();
                await this._validateOverlap();
            },
            onDiscard: async () => {
                await this._refreshTimeline();
                await this._validateOverlap();
            },
        });
    }

    async onSave() {
        const error = this._validate();
        if (error) {
            this.state.validationError = error;
            return;
        }
        this.state.saving = true;
        this.state.validationError = "";
        try {
            const fresh = await this.orm.call(
                "aps.time.tracking",
                "validate_timer_interval",
                [this.props.partnerId, this._toUTC(this.state.start_time), this._toUTC(this.state.stop_time), this.state.id || false],
                {}
            );
            if (!fresh.valid) {
                this.state.conflicts = fresh.conflicts || [];
                this.state.validationError = "This entry overlaps an existing time record.";
                return;
            }
            const vals = {
                subject_id: Number(this.state.subject_id),
                partner_id: this.props.partnerId,
                start_time: this._toUTC(this.state.start_time),
                stop_time: this._toUTC(this.state.stop_time),
                total_minutes: Number(this.state.total_minutes) || 0,
                date: this.timelineDate,
                notes: this.state.notes,
                pause_minutes: Number(this.state.pause_minutes) || 0,
                is_outside_school_hours: this.state.is_outside_school_hours,
            };
            if (this.state.id) {
                await this.orm.write("aps.time.tracking", [this.state.id], vals);
            } else {
                await this.orm.create("aps.time.tracking", [vals]);
            }
            await this.props.onSave();
            this.props.close();
        } catch (error) {
            this.state.validationError = error.data?.message || error.message || "Unable to save this time entry.";
        } finally {
            this.state.saving = false;
        }
    }

    async onDiscard() {
        await this.props.onDiscard();
        this.props.close();
    }
}

// ─── System Tray Item ─────────────────────────────────────────────────────────

export class TimerSystrayItem extends Component {
    static template = "aps_sis.TimerSystrayItem";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");

        this.state = useState({
            running: false,
            paused: false,
            startedAt: null,
            _tick: 0,        // bumped each second to trigger re-render
            pausedSeconds: 0,
            subjects: [],
            partnerId: null,
            partnerName: "",
        });

        this._timerInterval = null;
        this._pauseStart = null;

        this._onBeforeUnload = (ev) => {
            if (this.state.running) {
                ev.preventDefault();
                ev.returnValue = "";
            }
        };
        window.addEventListener("beforeunload", this._onBeforeUnload);
        onWillUnmount(() => {
            window.removeEventListener("beforeunload", this._onBeforeUnload);
        });
    }

    get elapsedLabel() {
        // Compute from real wall-clock time to avoid setInterval drift
        const now = Date.now();
        const startedAt = this.state.startedAt ? this.state.startedAt.getTime() : now;
        const pauseMs = (this.state.pausedSeconds || 0) * 1000;
        const s = Math.max(0, Math.floor((now - startedAt - pauseMs) / 1000));
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        if (h > 0) {
            return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
        }
        return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
    }

    async _loadDialogDefaults() {
        const defaults = await this.orm.call("aps.time.tracking", "get_timer_dialog_defaults", [], {});
        this.state.subjects = defaults.subjects;
        this.state.partnerId = defaults.partner_id;
        this.state.partnerName = defaults.partner_name;
    }

    async onStart() {
        if (this.state.running) return;

        await this._loadDialogDefaults();

        this.state.startedAt = new Date();
        this.state.running = true;
        this.state.paused = false;
        this.state._tick = 0;
        this.state.pausedSeconds = 0;
        this._pauseStart = null;

        this._timerInterval = setInterval(() => {
            this.state._tick += 1;
        }, 1000);
    }

    onPause() {
        if (!this.state.running || this.state.paused) return;
        this.state.paused = true;
        this._pauseStart = Date.now();
        clearInterval(this._timerInterval);
        this._timerInterval = null;
    }

    onResume() {
        if (!this.state.running || !this.state.paused) return;
        if (this._pauseStart) {
            this.state.pausedSeconds += Math.round((Date.now() - this._pauseStart) / 1000);
            this._pauseStart = null;
        }
        this.state.paused = false;
        this._timerInterval = setInterval(() => {
            this.state._tick += 1;
        }, 1000);
    }

    async onStop() {
        if (!this.state.running) return;

        // Capture any in-progress pause
        if (this.state.paused && this._pauseStart) {
            this.state.pausedSeconds += Math.round((Date.now() - this._pauseStart) / 1000);
            this._pauseStart = null;
        }

        clearInterval(this._timerInterval);
        this._timerInterval = null;
        this.state.running = false;
        this.state.paused = false;

        const now = new Date();
        const startedAt = this.state.startedAt || now;
        const pauseMinutes = Math.round(this.state.pausedSeconds / 60 * 10) / 10;
        const diffMs = now - startedAt;
        const totalMinutes = diffMs > 0 ? Math.round(Math.max(0, diffMs / 60000 - pauseMinutes)) : 0;

        // Build a local entry object (no DB record yet)
        const fmt = (dt) => {
            const pad = (n) => String(n).padStart(2, "0");
            return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}:${pad(dt.getSeconds())}`;
        };
        const entry = {
            start_time: fmt(startedAt),
            stop_time: fmt(now),
            pause_minutes: pauseMinutes,
            total_minutes: totalMinutes,
            notes: "",
            is_outside_school_hours: false,
            subject_id: false,
            tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };

        await this._loadDialogDefaults();

        this.dialog.add(EnhancedTimerStopDialog, {
            entry,
            subjects: this.state.subjects,
            partnerId: this.state.partnerId,
            partnerName: this.state.partnerName,
            onSave: () => {
                this.state.startedAt = null;
                this.state._tick = 0;
                this.state.pausedSeconds = 0;
            },
            onDiscard: () => {
                this.state.startedAt = null;
                this.state._tick = 0;
                this.state.pausedSeconds = 0;
            },
        });
    }

    openTimeTrackingList() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.time.tracking",
            views: [[false, "list"], [false, "form"]],
            name: "Time Entries",
        });
    }
}

// Register in the systray
const systrayRegistry = registry.category("systray");
systrayRegistry.add(
    "aps_sis.timer",
    {
        Component: TimerSystrayItem,
        sequence: 1,
    },
    { sequence: 1 }
);
