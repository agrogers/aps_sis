import { Component, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

// ─── Global timer state — survives component remounts (e.g. app navigation) ──
const _timer = {
    running: false,
    paused: false,
    entryId: null,
    elapsedSeconds: 0,
    totalPausedSeconds: 0,  // accumulated seconds across all completed pauses
    pauseStartMs: null,     // Date.now() when the current pause began (null if not paused)
    interval: null,         // active setInterval handle (managed by the mounted component)
};

// ─── Stop Timer Dialog ────────────────────────────────────────────────────────

export class TimerStopDialog extends Component {
    static template = "aps_sis.TimerStopDialog";
    static components = { Dialog };
    static props = {
        entry: { type: Object },
        subjects: { type: Array },
        partners: { type: Array },
        pauseMinutes: { type: Number, optional: true },
        onSave: { type: Function },
        onDiscard: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        // Safely extract IDs from either [id, name] array or raw id
        const subjectId = Array.isArray(this.props.entry.subject_id)
            ? this.props.entry.subject_id[0]
            : (this.props.entry.subject_id || false);
        const partnerId = Array.isArray(this.props.entry.partner_id)
            ? this.props.entry.partner_id[0]
            : (this.props.entry.partner_id || false);
        this.state = useState({
            subject_id: subjectId,
            partner_id: partnerId,
            notes: this.props.entry.notes || "",
            // Pre-fill pause_minutes from the tracked pauses; user can override
            pause_minutes: this.props.pauseMinutes !== undefined
                ? this.props.pauseMinutes
                : (this.props.entry.pause_minutes || 0),
            is_outside_school_hours: this.props.entry.is_outside_school_hours || false,
            total_minutes: this.props.entry.total_minutes || 0,
        });
    }

    get formattedDuration() {
        const mins = Math.round(this.state.total_minutes);
        const h = Math.floor(mins / 60);
        const m = mins % 60;
        return h > 0 ? `${h}h ${m}m` : `${m}m`;
    }

    async onSave() {
        await this.orm.write("aps.time.tracking", [this.props.entry.id], {
            subject_id: this.state.subject_id || false,
            partner_id: this.state.partner_id || false,
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

// ─── System Tray Timer Component ──────────────────────────────────────────────

export class TimerSystrayItem extends Component {
    static template = "aps_sis.TimerSystrayItem";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.menuService = useService("menu");

        // Local reactive state mirrors the global _timer so OWL re-renders correctly
        this.state = useState({
            running: _timer.running,
            paused: _timer.paused,
            entryId: _timer.entryId,
            elapsedSeconds: _timer.elapsedSeconds,
            subjects: [],
            partners: [],
        });

        // If the timer was already running when this component mounted (e.g. after an
        // app-switch that remounted the navbar), restart the tick interval.
        if (_timer.running && !_timer.paused && !_timer.interval) {
            this._startInterval();
        }

        onWillUnmount(() => {
            // Persist the elapsed count into the global so a future remount picks it up
            _timer.elapsedSeconds = this.state.elapsedSeconds;
            // Stop the local interval — it will be restarted if the component remounts
            if (_timer.interval) {
                clearInterval(_timer.interval);
                _timer.interval = null;
            }
        });
    }

    // ── Visibility: only render UI when user is inside the APEX module ────────
    get isApexModule() {
        const app = this.menuService.currentApp;
        return app ? app.xmlid === "aps_sis.menu_apex_root" : false;
    }

    // ── Elapsed time label ────────────────────────────────────────────────────
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

    // ── Private interval helpers ──────────────────────────────────────────────
    _startInterval() {
        _timer.interval = setInterval(() => {
            this.state.elapsedSeconds += 1;
            _timer.elapsedSeconds = this.state.elapsedSeconds;
        }, 1000);
    }

    _stopInterval() {
        if (_timer.interval) {
            clearInterval(_timer.interval);
            _timer.interval = null;
        }
    }

    // ── Data helpers ──────────────────────────────────────────────────────────
    async _loadSubjectsAndPartners() {
        const [subjects, partners] = await Promise.all([
            this.orm.searchRead("op.subject", [], ["id", "name"], { order: "name asc" }),
            this.orm.searchRead(
                "res.partner",
                [["is_student", "=", true]],
                ["id", "name"],
                { order: "name asc" }
            ),
        ]);
        this.state.subjects = subjects;
        this.state.partners = partners;
    }

    // ── User actions ──────────────────────────────────────────────────────────

    async onStart() {
        if (_timer.running) return;

        await this._loadSubjectsAndPartners();

        const entryId = await this.orm.call("aps.time.tracking", "start_timer", [], {});

        Object.assign(_timer, {
            running: true,
            paused: false,
            entryId,
            elapsedSeconds: 0,
            totalPausedSeconds: 0,
            pauseStartMs: null,
        });
        this.state.running = true;
        this.state.paused = false;
        this.state.entryId = entryId;
        this.state.elapsedSeconds = 0;

        this._startInterval();
    }

    /** Pause: freeze the elapsed counter and record the wall-time pause start. */
    onPause() {
        if (!_timer.running || _timer.paused) return;
        this._stopInterval();
        _timer.paused = true;
        _timer.pauseStartMs = Date.now();
        this.state.paused = true;
    }

    /** Accumulate any active pause duration into `_timer.totalPausedSeconds`. */
    _finalizePause() {
        if (_timer.pauseStartMs !== null) {
            _timer.totalPausedSeconds += (Date.now() - _timer.pauseStartMs) / 1000;
            _timer.pauseStartMs = null;
        }
    }

    /** Resume: accumulate paused duration and restart the elapsed counter. */
    onResume() {
        if (!_timer.running || !_timer.paused) return;
        this._finalizePause();
        _timer.paused = false;
        this.state.paused = false;
        this._startInterval();
    }

    /** Stop: finalise pauses, stamp stop_time on the server, show the edit dialog. */
    async onStop() {
        if (!_timer.running || !_timer.entryId) return;

        // Close any active pause before stopping
        if (_timer.paused) {
            this._finalizePause();
        }
        this._stopInterval();

        const pauseMinutes = Math.round((_timer.totalPausedSeconds / 60) * 10) / 10;
        const entryId = _timer.entryId;

        Object.assign(_timer, {
            running: false,
            paused: false,
            entryId: null,
            elapsedSeconds: 0,
            totalPausedSeconds: 0,
        });
        this.state.running = false;
        this.state.paused = false;

        const entry = await this.orm.call(
            "aps.time.tracking",
            "stop_timer",
            [entryId],
            {}
        );

        await this._loadSubjectsAndPartners();

        this.dialog.add(TimerStopDialog, {
            entry,
            subjects: this.state.subjects,
            partners: this.state.partners,
            pauseMinutes,
            onSave: () => {
                this.state.entryId = null;
                this.state.elapsedSeconds = 0;
            },
            onDiscard: async () => {
                try {
                    await this.orm.unlink("aps.time.tracking", [entry.id]);
                } catch (e) {
                    console.warn("Timer: could not delete discarded entry", entry.id, e);
                }
                this.state.entryId = null;
                this.state.elapsedSeconds = 0;
            },
        });
    }
}

// Register in the systray.
// High sequence = far-left position in the Odoo systray (items sorted by sequence descending).
registry.category("systray").add(
    "aps_sis.timer",
    {
        Component: TimerSystrayItem,
        sequence: 9999,
    },
    { sequence: 9999 }
);
