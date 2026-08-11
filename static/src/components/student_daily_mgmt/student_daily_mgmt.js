import { Component, onMounted, onPatched, onWillUnmount, onWillStart, useRef, useState } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { UniformInfringementDialog } from "./uniform_infringement_dialog";

const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
});
const SELECTED_CLASS_STORAGE_KEY = "aps_sis.student_daily_mgmt.selected_class";

export class StudentDailyMgmtDashboard extends Component {
    static template = "aps_sis.StudentDailyMgmtDashboard";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.root = useRef("root");
        let selectedClass = "all";
        try {
            selectedClass = window.localStorage.getItem(SELECTED_CLASS_STORAGE_KEY) || "all";
        } catch {
            // Local storage may be unavailable in private/restricted browser contexts.
        }
        this.state = useState({
            classes: [],
            students: [],
            selectedClass,
            selectedDate: this._today(),
            calendarOpen: false,
            calendarMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
            attendance: {},
            attendanceRecords: {},
            attendanceStatuses: [],
            isSchoolDay: false,
            submitting: false,
            attendanceHistory: {},
            schoolDays: [],
            uniformInfringements: {},
        });
        this.lottieAnimations = new Map();

        onMounted(() => this._mountCakeAnimations());
        onPatched(() => this._mountCakeAnimations());
        onWillUnmount(() => {
            for (const animation of this.lottieAnimations.values()) {
                animation.destroy();
            }
            this.lottieAnimations.clear();
        });

        onWillStart(async () => {
            await Promise.all([this._loadClasses(), this._loadStudents(), this._loadAttendanceStatuses()]);
            await this._loadAttendanceForDate();
            await this._loadUniformInfringements();
            await this._loadAttendanceHistory();
        });
    }

    async _mountCakeAnimations() {
        const root = this.root.el;
        if (!root) {
            return;
        }
        if (!window.lottie) {
            try {
                await loadJS("/aps_sis/static/src/lib/lottie/lottie.min.js");
            } catch {
                return;
            }
        }
        if (!window.lottie) {
            return;
        }
        const containers = root.querySelectorAll(".sdm-cake-lottie:not([data-lottie-mounted])");
        if (!containers.length) {
            return;
        }
        for (const container of containers) {
            if (container.dataset.lottieMounted) {
                continue;
            }
            const animation = window.lottie.loadAnimation({
                container,
                renderer: "svg",
                loop: true,
                autoplay: true,
                path: "/apex_core/static/img/balloons.json",
            });
            container.dataset.lottieMounted = "true";
            this.lottieAnimations.set(container, animation);
        }
    }

    _today() {
        return new Date().toISOString().slice(0, 10);
    }

    async _loadClasses() {
        this.state.classes = await this.orm.searchRead(
            "aps.class",
            [
                ["active", "=", true],
                ["academic_year_id.is_current", "=", true],
                // Home classes are identified by the Home Class/Pastoral Care
                // tag on the subject category.
                ["subject_id.category_id.tag_ids.name", "in", ["Home Class", "Pastoral Care Subject"]],
            ],
            ["name"],
            { order: "name" }
        );
        if (!this.state.classes.some((schoolClass) => String(schoolClass.id) === this.state.selectedClass)) {
            this.state.selectedClass = "all";
            this._saveSelectedClass();
        }
    }

    _saveSelectedClass() {
        try {
            window.localStorage.setItem(SELECTED_CLASS_STORAGE_KEY, this.state.selectedClass);
        } catch {
            // Local storage may be unavailable in private/restricted browser contexts.
        }
    }

    async _loadStudents() {
        this.state.students = await this.orm.searchRead(
            "aps.student",
            [["active", "=", true], ["enrollment_ids.state", "=", "enrolled"]],
            ["partner_id", "home_class_id", "birthday"],
            { order: "partner_id" }
        );
        const partnerIds = this.state.students.map((student) => student.partner_id[0]);
        if (partnerIds.length) {
            const partners = await this.orm.searchRead("res.partner", [["id", "in", partnerIds]], ["gender"]);
            const genderByPartner = Object.fromEntries(partners.map((partner) => [partner.id, partner.gender]));
            for (const student of this.state.students) {
                student.gender = genderByPartner[student.partner_id[0]] || false;
            }
        }
    }

    async _loadAttendanceStatuses() {
        this.state.attendanceStatuses = await this.orm.searchRead(
            "apex.attendance.status",
            [["active", "=", true]],
            ["name", "status_code", "icon", "default", "sequence"],
            { order: "sequence, id" },
        );
    }

    async _loadAttendanceForDate() {
        const calendar = await this.orm.searchRead(
            "aps.school.calendar",
            [["date", "=", this.state.selectedDate], ["date_type", "=", "school_day"]],
            ["id"],
            { limit: 1 },
        );
        this.state.isSchoolDay = Boolean(calendar.length);
        this.state.attendance = {};
        this.state.attendanceRecords = {};
        if (!this.state.isSchoolDay || !this.state.students.length) {
            return;
        }
        const records = await this.orm.searchRead(
            "apex.attendance",
            [
                ["student_id", "in", this.state.students.map((student) => student.id)],
                ["date", "=", this.state.selectedDate],
                ["attendance_type", "=", "daily"],
            ],
            ["id", "student_id", "status_id"],
        );
        const recordsByStudent = new Set();
        for (const record of records) {
            const studentId = record.student_id && record.student_id[0];
            if (studentId) {
                recordsByStudent.add(studentId);
                this.state.attendanceRecords[studentId] = record.id;
                this.state.attendance[studentId] = record.status_id ? record.status_id[0] : false;
            }
        }
        const defaultStatuses = this.state.attendanceStatuses.filter((status) => status.default);
        const defaultStatus = defaultStatuses[0];
        if (!defaultStatus) {
            return;
        }
        const missingStudents = this.state.students.filter((student) => !recordsByStudent.has(student.id));
        if (missingStudents.length) {
            const createdIds = await this.orm.create(
                "apex.attendance",
                missingStudents.map((student) => ({
                    date: this.state.selectedDate,
                    partner_id: student.partner_id[0],
                    attendance_type: "daily",
                    status_id: defaultStatus.id,
                })),
            );
            missingStudents.forEach((student, index) => {
                this.state.attendanceRecords[student.id] = createdIds[index];
                this.state.attendance[student.id] = defaultStatus.id;
            });
        }
    }

    async _loadAttendanceHistory() {
        const schoolDays = await this.orm.searchRead(
            "aps.school.calendar",
            [["date", "<=", this.state.selectedDate], ["date_type", "=", "school_day"]],
            ["date"],
            { order: "date desc", limit: 10 }
        );
        this.state.schoolDays = schoolDays.sort((left, right) => left.date.localeCompare(right.date));
        const studentIds = this.state.students.map((student) => student.id);
        if (!studentIds.length || !this.state.schoolDays.length) {
            this.state.attendanceHistory = {};
            return;
        }
        const records = await this.orm.searchRead(
            "apex.attendance",
            [
                ["student_id", "in", studentIds],
                ["date", "in", this.state.schoolDays.map((day) => day.date)],
                ["attendance_type", "=", "daily"],
            ],
            ["student_id", "date", "status_id"],
        );
        const history = {};
        for (const record of records) {
            const studentId = record.student_id && record.student_id[0];
            if (studentId) {
                history[studentId] = history[studentId] || {};
                history[studentId][record.date] = record.status_id ? record.status_id[1] : "";
            }
        }
        this.state.attendanceHistory = history;
    }

    async _loadUniformInfringements() {
        const partnerIds = this.state.students.map((student) => student.partner_id[0]);
        this.state.uniformInfringements = {};
        if (!partnerIds.length) {
            return;
        }
        const records = await this.orm.searchRead(
            "apex.uniform.infringement",
            [["partner_id", "in", partnerIds], ["date", "=", this.state.selectedDate]],
            ["partner_id", "infringement_type", "comment"],
        );
        for (const record of records) {
            const partnerId = record.partner_id && record.partner_id[0];
            if (partnerId) {
                this.state.uniformInfringements[partnerId] = this.state.uniformInfringements[partnerId] || [];
                this.state.uniformInfringements[partnerId].push({
                    id: record.id,
                    type: record.infringement_type,
                    comment: record.comment || "",
                });
            }
        }
    }

    get filteredStudents() {
        if (this.state.selectedClass === "all") {
            return this.state.students;
        }
        return this.state.students.filter(
            (student) => student.home_class_id && student.home_class_id[0] === Number(this.state.selectedClass)
        );
    }

    get selectedDateLabel() {
        const parts = Object.fromEntries(
            DATE_FORMATTER.formatToParts(new Date(`${this.state.selectedDate}T00:00:00`))
                .filter((part) => part.type !== "literal")
                .map((part) => [part.type, part.value])
        );
        return `${parts.weekday} ${parts.day}, ${parts.month} ${parts.year}`;
    }

    get calendarTitle() {
        return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(
            this.state.calendarMonth
        );
    }

    get calendarDays() {
        const year = this.state.calendarMonth.getFullYear();
        const month = this.state.calendarMonth.getMonth();
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const days = [];
        for (let index = 0; index < firstDay; index++) {
            days.push({ key: `empty-${index}`, empty: true });
        }
        for (let day = 1; day <= daysInMonth; day++) {
            const date = new Date(year, month, day);
            const isoDate = this._toIsoDate(date);
            days.push({
                key: isoDate,
                day,
                isoDate,
                isSelected: isoDate === this.state.selectedDate,
                hasBirthday: this._studentsWithBirthday(isoDate).length > 0,
            });
        }
        return days;
    }

    _toIsoDate(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    }

    _studentsWithBirthday(date) {
        const monthDay = date.slice(5);
        return this.state.students.filter((student) => student.birthday && student.birthday.slice(5) === monthDay);
    }

    birthdayStudentsForDate(date = this.state.selectedDate) {
        return this._studentsWithBirthday(date);
    }

    hasBirthday(student) {
        return Boolean(student.birthday && student.birthday.slice(5) === this.state.selectedDate.slice(5));
    }

    async selectDate(date) {
        this.state.selectedDate = date;
        this.state.calendarOpen = false;
        await this._loadAttendanceForDate();
        await this._loadUniformInfringements();
        await this._loadAttendanceHistory();
    }

    toggleCalendar() {
        this.state.calendarOpen = !this.state.calendarOpen;
    }

    previousMonth() {
        const current = this.state.calendarMonth;
        this.state.calendarMonth = new Date(current.getFullYear(), current.getMonth() - 1, 1);
    }

    nextMonth() {
        const current = this.state.calendarMonth;
        this.state.calendarMonth = new Date(current.getFullYear(), current.getMonth() + 1, 1);
    }

    attendanceStatus(student) {
        const statusId = this.state.attendance[student.id];
        return this.state.attendanceStatuses.find((status) => status.id === statusId) || null;
    }

    isAbsent(student) {
        const status = this.attendanceStatus(student);
        const code = String(status?.status_code || "").toLowerCase();
        const name = String(status?.name || "").toLowerCase();
        return code === "absent" || name === "absent";
    }

    attendanceIconUrl(status) {
        return status && status.icon
            ? `/web/image/apex.attendance.status/${status.id}/icon`
            : "";
    }

    photoBackgroundStyle(student) {
        const partnerId = student.partner_id && student.partner_id[0];
        return partnerId
            ? `background-image: url("/web/image/res.partner/${partnerId}/avatar_128");`
            : "";
    }

    uniformInfringementTypes(studentOrPartnerId) {
        const partnerId = typeof studentOrPartnerId === "object"
            ? studentOrPartnerId.partner_id[0]
            : studentOrPartnerId;
        return (this.state.uniformInfringements[partnerId] || []).map((record) => record.type);
    }

    uniformIconUrl(student) {
        if (!this.uniformInfringementTypes(student).length) {
            return "/apex_core/static/img/uniform.svg";
        }
        return student.gender === "female"
            ? "/apex_core/static/img/woman.svg"
            : "/apex_core/static/img/man.svg";
    }

    uniformInfringementMarkerClass(type) {
        return `sdm-uniform-x sdm-uniform-x-${type}`;
    }

    async openUniformInfringement(student) {
        this.dialog.add(UniformInfringementDialog, {
            studentId: student.partner_id[0],
            studentName: student.partner_id[1],
            date: this.state.selectedDate,
            existingRecords: this.state.uniformInfringements[student.partner_id[0]] || [],
            onSaved: () => this._loadUniformInfringements(),
        });
    }

    async cycleAttendance(student) {
        if (!this.state.isSchoolDay || !this.state.attendanceStatuses.length) {
            return;
        }
        const currentStatusId = this.state.attendance[student.id];
        const currentIndex = this.state.attendanceStatuses.findIndex((status) => status.id === currentStatusId);
        const nextStatus = this.state.attendanceStatuses[(currentIndex + 1) % this.state.attendanceStatuses.length];
        const values = { status_id: nextStatus.id };
        let recordId = this.state.attendanceRecords[student.id];
        if (recordId) {
            await this.orm.write("apex.attendance", [recordId], values);
        } else {
            const created = await this.orm.create("apex.attendance", [{
                date: this.state.selectedDate,
                partner_id: student.partner_id[0],
                attendance_type: "daily",
                ...values,
            }]);
            recordId = created[0];
            this.state.attendanceRecords[student.id] = recordId;
        }
        this.state.attendance[student.id] = nextStatus.id;
        this.state.attendanceHistory[student.id] = this.state.attendanceHistory[student.id] || {};
        this.state.attendanceHistory[student.id][this.state.selectedDate] = nextStatus.name;
    }

    async submitAttendance() {
        if (this.state.submitting || !this.state.isSchoolDay) {
            return;
        }
        const defaultStatuses = this.state.attendanceStatuses.filter((status) => status.default);
        if (!defaultStatuses.length) {
            this.notification.add("No default attendance statuses are configured.", { type: "warning" });
            return;
        }
        this.state.submitting = true;
        try {
            for (const student of this.filteredStudents) {
                const currentStatusId = this.state.attendance[student.id];
                const currentIndex = defaultStatuses.findIndex((status) => status.id === currentStatusId);
                if (currentIndex < 0 || currentIndex >= defaultStatuses.length - 1) {
                    continue;
                }
                const nextStatus = defaultStatuses[currentIndex + 1];
                const recordId = this.state.attendanceRecords[student.id];
                if (recordId) {
                    await this.orm.write("apex.attendance", [recordId], { status_id: nextStatus.id });
                    this.state.attendance[student.id] = nextStatus.id;
                }
            }
            this.notification.add("Default attendance statuses advanced.", { type: "success" });
        } finally {
            this.state.submitting = false;
        }
    }

    attendanceHistory(student) {
        const history = this.state.attendanceHistory[student.id] || {};
        return this.state.schoolDays.map((day) => ({
            date: day.date,
            status: history[day.date] || "",
            className: this._attendanceDotClass(history[day.date]),
        }));
    }

    _attendanceDotClass(status) {
        if (status === "Present") {
            return "is-present";
        }
        if (status === "Absent") {
            return "is-absent";
        }
        if (status === "Early Departure") {
            return "is-early-departure";
        }
        if (status === "Late Arrival") {
            return "is-late-arrival";
        }
        return "is-unrecorded";
    }

    openStudent(student) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.student",
            res_id: student.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("aps_student_daily_mgmt_dashboard", StudentDailyMgmtDashboard);
