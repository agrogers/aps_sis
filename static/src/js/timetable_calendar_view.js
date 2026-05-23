import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { CalendarRenderer } from "@web/views/calendar/calendar_renderer";
import { calendarView } from "@web/views/calendar/calendar_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Extends the common renderer to restrict visible hours to 08:00–17:00
 * and to overlay school-calendar day labels (e.g. "T4-W6") as native
 * all-day FullCalendar events so they appear in the all-day row with
 * the correct colour from aps.school.calendar.color.
 */
class TimetableCalendarCommonRenderer extends CalendarCommonRenderer {

    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    get options() {
        return {
            ...super.options,
            slotMinTime: "08:00:00",
            slotMaxTime: "17:00:00",
            scrollTime: "08:00:00",
            slotDuration: "00:10:00",
            slotLabelInterval: "01:00:00",
            // School-calendar labels as a second FullCalendar event source.
            // They are all-day events so FullCalendar places them in the
            // all-day row automatically, with colour from aps.school.calendar.
            eventSources: [
                {
                    id: "school_calendar_labels",
                    events: async (fetchInfo, successCallback, failureCallback) => {
                        try {
                            const start = fetchInfo.start.toISOString().split("T")[0];
                            const end   = fetchInfo.end.toISOString().split("T")[0];
                            const records = await this.orm.searchRead(
                                "aps.school.calendar",
                                [["date", ">=", start], ["date", "<", end]],
                                ["date", "display_name", "color"],
                                { limit: 90 }
                            );
                            successCallback(
                                records.map(r => ({
                                    id: `sc_${r.id}`,
                                    title: r.display_name,
                                    start: r.date,
                                    allDay: true,
                                    // Use Odoo's color CSS classes so the colour
                                    // matches the school calendar view exactly.
                                    classNames: [`o_calendar_color_${r.color}`],
                                    editable: false,
                                    // "block" renders a solid banner like the school calendar view.
                                    display: "block",
                                }))
                            );
                        } catch (e) {
                            failureCallback(e);
                        }
                    },
                },
            ],
        };
    }
}

/**
 * Custom CalendarRenderer that uses TimetableCalendarCommonRenderer
 * for the day, week and month scales.
 */
class TimetableCalendarRenderer extends CalendarRenderer {}
TimetableCalendarRenderer.components = {
    ...CalendarRenderer.components,
    day: TimetableCalendarCommonRenderer,
    week: TimetableCalendarCommonRenderer,
    month: TimetableCalendarCommonRenderer,
};

registry.category("views").add("timetable_calendar", {
    ...calendarView,
    Renderer: TimetableCalendarRenderer,
});
