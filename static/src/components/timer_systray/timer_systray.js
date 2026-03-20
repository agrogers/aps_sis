import { Component, useState, useRef } from "@odoo/owl";
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
        partners: { type: Array },
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
            pause_minutes: this.props.entry.pause_minutes || 0,
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
            entryId: null,
            elapsedSeconds: 0,
            subjects: [],
            partners: [],
        });

        this._timerInterval = null;
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

    async onStart() {
        if (this.state.running) return;

        await this._loadSubjectsAndPartners();

        const entryId = await this.orm.call("aps.time.tracking", "start_timer", [], {});
        this.state.entryId = entryId;
        this.state.running = true;
        this.state.elapsedSeconds = 0;

        this._timerInterval = setInterval(() => {
            this.state.elapsedSeconds += 1;
        }, 1000);
    }

    async onStop() {
        if (!this.state.running || !this.state.entryId) return;

        clearInterval(this._timerInterval);
        this._timerInterval = null;
        this.state.running = false;

        const entry = await this.orm.call(
            "aps.time.tracking",
            "stop_timer",
            [this.state.entryId],
            {}
        );

        await this._loadSubjectsAndPartners();

        this.dialog.add(TimerStopDialog, {
            entry,
            subjects: this.state.subjects,
            partners: this.state.partners,
            onSave: () => {
                this.state.entryId = null;
                this.state.elapsedSeconds = 0;
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
