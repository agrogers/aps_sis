import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class StudentMatrix extends Component {
    static template = "aps_sis.StudentMatrix";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this._STORAGE_KEY = "aps_student_matrix_class_selection";
        this._YEAR_STORAGE_KEY = "aps_student_matrix_year_selection";

        this.state = useState({
            loading: true,
            academicYears: [],
            selectedYearId: null,
            classes: [],
            selectedClassIds: [],
            students: [],
            subjects: [],
            cells: {},
            subjectColors: {},
            studentTotals: {},
            subjectTotals: {},
        });

        onWillStart(async () => {
            await this._loadAcademicYears();
            this._restoreYearSelection();
            await this._loadClasses();
            this._restoreSelection();
            this.state.loading = false;
        });
    }

    async _loadAcademicYears() {
        try {
            const years = await this.orm.call("aps.student.matrix", "get_academic_years", []);
            this.state.academicYears = years || [];
        } catch (err) {
            console.error("StudentMatrix: failed to load academic years", err);
            this.state.academicYears = [];
        }
    }

    _restoreYearSelection() {
        try {
            const raw = localStorage.getItem(this._YEAR_STORAGE_KEY);
            if (raw) {
                const savedId = JSON.parse(raw);
                const validIds = this.state.academicYears.map((y) => y.id);
                if (validIds.includes(savedId)) {
                    this.state.selectedYearId = savedId;
                    return;
                }
            }
        } catch (e) {}
        // Default to current academic year
        const current = this.state.academicYears.find((y) => y.is_current);
        this.state.selectedYearId = current ? current.id : (this.state.academicYears[0]?.id || null);
    }

    _saveYearSelection() {
        try {
            localStorage.setItem(this._YEAR_STORAGE_KEY, JSON.stringify(this.state.selectedYearId));
        } catch (e) {}
    }

    onYearChange(ev) {
        const yearId = parseInt(ev.target.value, 10);
        this.state.selectedYearId = yearId || null;
        this._saveYearSelection();
        // Clear class selection and reload classes for the new year
        this.state.selectedClassIds = [];
        this.state.students = [];
        this.state.subjects = [];
        this.state.cells = {};
        this.state.subjectColors = {};
        this.state.studentTotals = {};
        this.state.subjectTotals = {};
        this._saveSelection();
        this._loadClasses();
    }

    async _loadClasses() {
        try {
            const args = this.state.selectedYearId ? [this.state.selectedYearId] : [];
            const classes = await this.orm.call("aps.student.matrix", "get_home_classes", args);
            this.state.classes = classes || [];
        } catch (err) {
            console.error("StudentMatrix: failed to load classes", err);
            this.state.classes = [];
        }
    }

    _restoreSelection() {
        try {
            const raw = localStorage.getItem(this._STORAGE_KEY);
            if (!raw) return;
            const saved = JSON.parse(raw);
            if (Array.isArray(saved) && saved.length > 0) {
                const validIds = this.state.classes.map((c) => c.id);
                this.state.selectedClassIds = saved.filter((id) => validIds.includes(id));
                if (this.state.selectedClassIds.length > 0) {
                    this._loadMatrix();
                }
            }
        } catch (e) {}
    }

    _saveSelection() {
        try {
            localStorage.setItem(this._STORAGE_KEY, JSON.stringify(this.state.selectedClassIds));
        } catch (e) {}
    }

    onClassToggle(classId) {
        const idx = this.state.selectedClassIds.indexOf(classId);
        if (idx >= 0) {
            this.state.selectedClassIds.splice(idx, 1);
        } else {
            this.state.selectedClassIds.push(classId);
        }
        this._saveSelection();
        this._loadMatrix();
    }

    onSelectAll() {
        this.state.selectedClassIds = this.state.classes.map((c) => c.id);
        this._saveSelection();
        this._loadMatrix();
    }

    onClearAll() {
        this.state.selectedClassIds = [];
        this.state.students = [];
        this.state.subjects = [];
        this.state.cells = {};
        this.state.subjectColors = {};
        this.state.studentTotals = {};
        this.state.subjectTotals = {};
        this._saveSelection();
    }

    async _loadMatrix() {
        if (this.state.selectedClassIds.length === 0) {
            this.state.students = [];
            this.state.subjects = [];
            this.state.cells = {};
            this.state.subjectColors = {};
            this.state.studentTotals = {};
            this.state.subjectTotals = {};
            return;
        }
        try {
            const data = await this.orm.call(
                "aps.student.matrix",
                "get_matrix_data",
                [this.state.selectedClassIds, this.state.selectedYearId]
            );
            this.state.students = data.students || [];
            this.state.subjects = data.subjects || [];
            this.state.cells = data.cells || {};
            this.state.subjectColors = data.subject_colors || {};
            this.state.studentTotals = data.student_totals || {};
            this.state.subjectTotals = data.subject_totals || {};
        } catch (err) {
            console.error("StudentMatrix: failed to load matrix data", err);
        }
    }

    getCellValue(studentId, subjectId) {
        const cell = this.state.cells[`${studentId}_${subjectId}`];
        return cell ? cell.gcse : null;
    }

    hasCell(studentId, subjectId) {
        return this.getCellValue(studentId, subjectId) !== null;
    }

    getTickClass(studentId, subjectId) {
        const val = this.getCellValue(studentId, subjectId);
        if (val === null) return '';
        if (val >= 1) return 'tick-full';
        if (val > 0 && val < 1) return 'tick-partial';
        return 'tick-zero';
    }

    getTickSymbol(studentId, subjectId) {
        const val = this.getCellValue(studentId, subjectId);
        if (val === null) return '';
        if (val >= 1) return '🗹';
        return '🗸';
    }

    getSubjectColor(subjectId) {
        return this.state.subjectColors[subjectId] || "#888888";
    }

    getStudentTotal(studentId) {
        return this.state.studentTotals[studentId] || 0;
    }

    getSubjectTotal(subjectId) {
        return this.state.subjectTotals[subjectId] || 0;
    }

    isClassSelected(classId) {
        return this.state.selectedClassIds.includes(classId);
    }

    get grandTotal() {
        return this.state.students.length;
    }

    onPrint() {
        window.print();
    }
}

registry.category("actions").add("aps_student_matrix", StudentMatrix);