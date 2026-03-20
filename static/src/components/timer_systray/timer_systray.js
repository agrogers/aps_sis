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
        // datetime-local inputs need "T" separator
        const startTime = (this.props.entry.start_time || "").replace(" ", "T");
        const stopTime = (this.props.entry.stop_time || "").replace(" ", "T");
        this.state = useState({
            subject_id: subjectId,
            start_time: startTime,
            stop_time: stopTime,
            notes: this.props.entry.notes || "",
            pause_minutes: this.props.entry.pause_minutes || 0,
            is_outside_school_hours: this.props.entry.is_outside_school_hours || false,
            total_minutes: this.props.entry.total_minutes || 0,
            subjectError: false,
        });
    }

    _recomputeDuration() {
        if (this.state.start_time && this.state.stop_time) {
            const start = new Date(this.state.start_time);
            const stop = new Date(this.state.stop_time);
            const diffMs = stop - start;
            if (diffMs > 0) {
                this.state.total_minutes = Math.max(0, diffMs / 60000 - (parseFloat(this.state.pause_minutes) || 0));
            } else {
                this.state.total_minutes = 0;
            }
        }
    }

    onTimeChange() {
        this._recomputeDuration();
    }

    get formattedDuration() {
        const mins = Math.round(this.state.total_minutes);
        const h = Math.floor(mins / 60);
        const m = mins % 60;
        return h > 0 ? `${h}h ${m}m` : `${m}m`;
    }

    async onSave() {
        if (!this.state.subject_id) {
            this.state.subjectError = true;
            return;
        }
        this.state.subjectError = false;
        // Convert local times back to UTC for Odoo
        const tz = this.props.entry.tz || "UTC";
        const toUTC = (localStr) => {
            if (!localStr) return false;
            // Parse as local time in the user's timezone
            const dt = new Date(localStr.replace(" ", "T"));
            return dt.toISOString().replace("T", " ").slice(0, 19);
        };
        await this.orm.write("aps.time.tracking", [this.props.entry.id], {
            subject_id: parseInt(this.state.subject_id),
            partner_id: this.props.partnerId,
            start_time: toUTC(this.state.start_time),
            stop_time: toUTC(this.state.stop_time),
            notes: this.state.notes,
            pause_minutes: parseFloat(this.state.pause_minutes) || 0,
            is_outside_school_hours: this.state.is_outside_school_hours,
        });
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
            entryId: null,
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

        const entryId = await this.orm.call("aps.time.tracking", "start_timer", [], {});
        this.state.entryId = entryId;
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
        if (!this.state.running || !this.state.entryId) return;

        // Capture any in-progress pause
        if (this.state.paused && this._pauseStart) {
            this.state.pausedSeconds += Math.round((Date.now() - this._pauseStart) / 1000);
            this._pauseStart = null;
        }

        clearInterval(this._timerInterval);
        this._timerInterval = null;
        this.state.running = false;
        this.state.paused = false;

        const pauseMinutes = Math.round(this.state.pausedSeconds / 60 * 10) / 10;

        const entry = await this.orm.call(
            "aps.time.tracking",
            "stop_timer",
            [this.state.entryId],
            {}
        );

        // Apply accumulated pause to entry before showing dialog
        entry.pause_minutes = pauseMinutes;
        // Recompute total after pause
        if (entry.start_time && entry.stop_time) {
            const start = new Date(entry.start_time.replace(" ", "T"));
            const stop = new Date(entry.stop_time.replace(" ", "T"));
            const diffMs = stop - start;
            entry.total_minutes = diffMs > 0 ? Math.max(0, diffMs / 60000 - pauseMinutes) : 0;
        }

        await this._loadDialogDefaults();

        this.dialog.add(TimerStopDialog, {
            entry,
            subjects: this.state.subjects,
            partnerId: this.state.partnerId,
            partnerName: this.state.partnerName,
            onSave: () => {
                this.state.entryId = null;
                this.state.elapsedSeconds = 0;
                this.state.pausedSeconds = 0;
            },
            onDiscard: async () => {
                // Delete the entry if discarded
                try {
                    await this.orm.unlink("aps.time.tracking", [entry.id]);
                } catch (e) {
                    console.warn("Timer: could not delete discarded entry", entry.id, e);
                }
                this.state.entryId = null;
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
