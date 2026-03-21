import { Component, useState, useRef, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

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
            elapsedSeconds: 0,
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
        const s = this.state.elapsedSeconds;
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
        this.state.elapsedSeconds = 0;
        this.state.pausedSeconds = 0;
        this._pauseStart = null;

        this._timerInterval = setInterval(() => {
            this.state.elapsedSeconds += 1;
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
            this.state.elapsedSeconds += 1;
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

        this.dialog.add(TimerStopDialog, {
            entry,
            subjects: this.state.subjects,
            partnerId: this.state.partnerId,
            partnerName: this.state.partnerName,
            onSave: () => {
                this.state.startedAt = null;
                this.state.elapsedSeconds = 0;
                this.state.pausedSeconds = 0;
            },
            onDiscard: () => {
                this.state.startedAt = null;
                this.state.elapsedSeconds = 0;
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
