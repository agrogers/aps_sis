import { deserializeDateTime } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";

import { EnhancedTimerStopDialog } from "../timer_systray/timer_systray";

const DATETIME_FIELDS = [
    "subject_id",
    "partner_id",
    "start_time",
    "stop_time",
    "pause_minutes",
    "total_minutes",
    "notes",
    "is_outside_school_hours",
    "date",
];

class TimeTrackingListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    async openRecord(record, force = false) {
        const dirty = await record.isDirty();
        if (dirty && !(await record.save())) {
            return;
        }

        const [entry] = await this.orm.read(
            "aps.time.tracking",
            [record.resId],
            DATETIME_FIELDS
        );
        if (!entry) {
            return;
        }

        const defaults = await this.orm.call(
            "aps.time.tracking",
            "get_timer_dialog_defaults",
            [],
            {}
        );
        const subjects = this._subjectsWithCurrentEntry(
            defaults.subjects || [],
            entry.subject_id
        );
        const partner = Array.isArray(entry.partner_id) ? entry.partner_id : [];

        this.dialogService.add(EnhancedTimerStopDialog, {
            entry: this._dialogEntry(entry),
            subjects,
            partnerId: partner[0] || defaults.partner_id,
            partnerName: partner[1] || defaults.partner_name || "",
            onSave: async () => {
                await this.model.load();
            },
            onDiscard: async () => {},
        });
    }

    _dialogEntry(entry) {
        return {
            ...entry,
            start_time: this._toLocalDateTime(entry.start_time),
            stop_time: this._toLocalDateTime(entry.stop_time),
        };
    }

    _toLocalDateTime(value) {
        return value
            ? deserializeDateTime(value).toFormat("yyyy-MM-dd HH:mm:ss")
            : false;
    }

    _subjectsWithCurrentEntry(subjects, subjectValue) {
        if (!Array.isArray(subjectValue) || !subjectValue[0]) {
            return subjects;
        }
        if (subjects.some((subject) => Number(subject.id) === Number(subjectValue[0]))) {
            return subjects;
        }
        return [
            ...subjects,
            {
                id: subjectValue[0],
                name: subjectValue[1] || "Selected subject",
                category_name: "",
                color: "#64748b",
            },
        ];
    }
}

registry.category("views").add("aps_time_tracking_enhanced_list", {
    ...listView,
    Controller: TimeTrackingListController,
});
