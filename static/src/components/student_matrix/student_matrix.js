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
            selectedStudentId: null,
            selectedSubjectId: null,
            selectedCategoryKey: null,
            hiddenSubjectIds: [],
            hiddenCategoryKeys: [],
            displayMode: "subject",
            students: [],
            subjects: [],
            cells: {},
            subjectColors: {},
            studentTotals: {},
            subjectTotals: {},
            categoryTotals: {},
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
        this.state.selectedStudentId = null;
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
        this.state.hiddenSubjectIds = [];
        this.state.hiddenCategoryKeys = [];
        this.state.students = [];
        this.state.subjects = [];
        this.state.cells = {};
        this.state.subjectColors = {};
        this.state.studentTotals = {};
        this.state.subjectTotals = {};
        this.state.categoryTotals = {};
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
        this.state.selectedStudentId = null;
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
        this.state.hiddenSubjectIds = [];
        this.state.hiddenCategoryKeys = [];
        this.state.students = [];
        this.state.subjects = [];
        this.state.cells = {};
        this.state.subjectColors = {};
        this.state.studentTotals = {};
        this.state.subjectTotals = {};
        this.state.categoryTotals = {};
        this._saveSelection();
    }

    async _loadMatrix() {
        if (this.state.selectedClassIds.length === 0) {
            this.state.selectedStudentId = null;
            this.state.selectedSubjectId = null;
            this.state.selectedCategoryKey = null;
            this.state.hiddenSubjectIds = [];
            this.state.hiddenCategoryKeys = [];
            this.state.students = [];
            this.state.subjects = [];
            this.state.cells = {};
            this.state.subjectColors = {};
            this.state.studentTotals = {};
            this.state.subjectTotals = {};
            this.state.categoryTotals = {};
            return;
        }
        try {
            const data = await this.orm.call(
                "aps.student.matrix",
                "get_matrix_data",
                [this.state.selectedClassIds, this.state.selectedYearId]
            );
            this.state.students = data.students || [];
            this.state.selectedStudentId = null;
            this.state.selectedSubjectId = null;
            this.state.selectedCategoryKey = null;
            this.state.hiddenSubjectIds = [];
            this.state.hiddenCategoryKeys = [];
            this.state.subjects = data.subjects || [];
            this.state.cells = data.cells || {};
            this.state.subjectColors = data.subject_colors || {};
            this.state.studentTotals = data.student_totals || {};
            this.state.subjectTotals = data.subject_totals || {};
            this.state.categoryTotals = data.category_totals || {};
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

    getGcseSuperscript(studentId, subjectId) {
        const val = this.getCellValue(studentId, subjectId);
        if (val === null || val === 0 || val === 1) return '';
        return String(val);
    }

    getSubjectColor(subjectId) {
        return this.state.subjectColors[subjectId] || "#888888";
    }

    getSubjectDisplayName(subject) {
        return (subject.name || "").replace(/\s*\(IGCSE\)\s*$/i, "").trim();
    }

    getTickClassForValue(val) {
        if (val === null) return "";
        if (val >= 1) return "tick-full";
        if (val > 0 && val < 1) return "tick-partial";
        return "tick-zero";
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

    get visibleStudents() {
        let students = this.state.students;
        if (this.state.selectedSubjectId) {
            students = students.filter((student) =>
                this.hasCell(student.id, this.state.selectedSubjectId)
            );
        }
        if (this.state.selectedCategoryKey) {
            const category = this.categories.find(
                (item) => item.categoryKey === this.state.selectedCategoryKey
            );
            students = students.filter(
                (student) =>
                    category && this.getCategorySubjectCount(student.id, category) > 0
            );
        }
        if (this.state.selectedStudentId) {
            students = students.filter(
                (student) => student.id === this.state.selectedStudentId
            );
        }
        return students;
    }

    get visibleSubjects() {
        const studentsForSubjects = this.state.selectedStudentId
            ? this.state.students.filter(
                  (student) => student.id === this.state.selectedStudentId
              )
            : this.state.students;
        const visibleStudentIds = new Set(studentsForSubjects.map((student) => student.id));
        return this.state.subjects.filter((subject) =>
            [...visibleStudentIds].some((studentId) =>
                this.hasCell(studentId, subject.id)
            )
        ).filter((subject) =>
            (!this.state.selectedSubjectId || subject.id === this.state.selectedSubjectId) &&
            !this.state.hiddenSubjectIds.includes(subject.id)
        );
    }

    get categories() {
        const categoriesByKey = new Map();
        for (const subject of this.state.subjects) {
            const categoryKey = subject.category_key || "uncategorized";
            if (!categoriesByKey.has(categoryKey)) {
                categoriesByKey.set(categoryKey, {
                    categoryKey,
                    key: `category:${categoryKey}`,
                    name: subject.category_name || "Uncategorized",
                    color: subject.category_color || "#888888",
                    subjects: [],
                });
            }
            categoriesByKey.get(categoryKey).subjects.push(subject);
        }
        return [...categoriesByKey.values()].sort((a, b) =>
            a.name.localeCompare(b.name)
        );
    }

    get visibleCategories() {
        const studentsForCategories = this.state.selectedStudentId
            ? this.state.students.filter(
                  (student) => student.id === this.state.selectedStudentId
              )
            : this.state.students;
        const visibleStudentIds = new Set(
            studentsForCategories.map((student) => student.id)
        );
        return this.categories
            .filter((category) =>
                [...visibleStudentIds].some(
                    (studentId) => this.getCategorySubjectCount(studentId, category) > 0
                )
            )
            .filter(
                (category) =>
                    (!this.state.selectedCategoryKey ||
                        category.categoryKey === this.state.selectedCategoryKey) &&
                    !this.state.hiddenCategoryKeys.includes(category.categoryKey)
            );
    }

    get visibleColumns() {
        if (this.state.displayMode === "category") {
            return this.visibleCategories.map((category) => ({
                ...category,
                type: "category",
                label: category.name,
            }));
        }
        return this.visibleSubjects.map((subject) => ({
            ...subject,
            type: "subject",
            key: `subject:${subject.id}`,
            label: this.getSubjectDisplayName(subject),
        }));
    }

    getCategorySubjectCount(studentId, category) {
        return category.subjects.filter((subject) =>
            this.hasCell(studentId, subject.id)
        ).length;
    }

    getColumnTotal(column) {
        if (column.type === "subject") {
            return this.getSubjectTotal(column.id);
        }
        return this.state.categoryTotals[column.categoryKey] || 0;
    }

    getColumnSubjectCount(studentId, column) {
        if (column.type === "subject") {
            return this.hasCell(studentId, column.id) ? 1 : 0;
        }
        return this.getCategorySubjectCount(studentId, column);
    }

    getColumnValue(studentId, column) {
        if (column.type === "subject") {
            return this.getCellValue(studentId, column.id);
        }
        const enrolledSubjects = column.subjects.filter((subject) =>
            this.hasCell(studentId, subject.id)
        );
        if (!enrolledSubjects.length) return null;
        return enrolledSubjects.reduce(
            (total, subject) => total + this.getCellValue(studentId, subject.id),
            0
        );
    }

    hasColumnCell(studentId, column) {
        return this.getColumnSubjectCount(studentId, column) > 0;
    }

    getColumnTickClass(studentId, column) {
        if (column.type === "subject") {
            return this.getTickClass(studentId, column.id);
        }
        return this.getTickClassForValue(this.getColumnValue(studentId, column));
    }

    getColumnTickSymbol(studentId, column) {
        if (column.type === "subject") {
            return this.getTickSymbol(studentId, column.id);
        }
        const val = this.getColumnValue(studentId, column);
        if (val === null) return "";
        return val >= 1 ? "🗹" : "🗸";
    }

    getColumnSuperscript(studentId, column) {
        if (column.type === "subject") {
            return this.getGcseSuperscript(studentId, column.id);
        }
        const subjectCount = this.getCategorySubjectCount(studentId, column);
        if (subjectCount > 1) return String(subjectCount);
        const subject = column.subjects.find((item) =>
            this.hasCell(studentId, item.id)
        );
        return subject ? this.getGcseSuperscript(studentId, subject.id) : "";
    }

    isColumnSelected(column) {
        return column.type === "subject"
            ? this.state.selectedSubjectId === column.id
            : this.state.selectedCategoryKey === column.categoryKey;
    }

    onStudentClick(studentId) {
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
        this.state.selectedStudentId =
            this.state.selectedStudentId === studentId ? null : studentId;
    }

    onShowAllStudents() {
        this.state.selectedStudentId = null;
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
    }

    onDisplayModeChange(ev) {
        this.state.displayMode = ev.target.value;
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
        this.state.hiddenSubjectIds = [];
        this.state.hiddenCategoryKeys = [];
    }

    onColumnClick(column) {
        this.state.selectedStudentId = null;
        if (column.type === "subject") {
            this.state.selectedCategoryKey = null;
            this.state.selectedSubjectId =
                this.state.selectedSubjectId === column.id ? null : column.id;
            return;
        }
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey =
            this.state.selectedCategoryKey === column.categoryKey
                ? null
                : column.categoryKey;
    }

    onShowAllColumns() {
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
        this.state.hiddenSubjectIds = [];
        this.state.hiddenCategoryKeys = [];
    }

    onColumnTotalClick(column) {
        this.state.selectedStudentId = null;
        this.state.selectedSubjectId = null;
        this.state.selectedCategoryKey = null;
        if (column.type === "subject") {
            if (!this.state.hiddenSubjectIds.includes(column.id)) {
                this.state.hiddenSubjectIds.push(column.id);
            }
            return;
        }
        if (!this.state.hiddenCategoryKeys.includes(column.categoryKey)) {
            this.state.hiddenCategoryKeys.push(column.categoryKey);
        }
    }

    get grandTotal() {
        return this.visibleStudents.length;
    }

    onPrint() {
        window.print();
    }
}

registry.category("actions").add("aps_student_matrix", StudentMatrix);