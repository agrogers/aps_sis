import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { SearchableSelect } from "@aps_sis/components/searchable_select/searchable_select";

export class StudentMatrix extends Component {
    static template = "aps_sis.StudentMatrix";
    static components = { SearchableSelect };
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this._YEAR_STORAGE_KEY = "aps_student_matrix_year_selection";
        this._SUBJECT_STORAGE_KEY = "aps_student_matrix_subject_selection";

        this.state = useState({
            loading: true,
            academicYears: [],
            selectedYearId: null,
            classes: [],
            selectedClassIds: [],
            subjectDropdownResetKey: 0,
            selectedStudentId: null,
            selectedSubjectIds: [],
            subjectGroupBy: "level",
            selectedCategoryKey: null,
            hiddenSubjectIds: [],
            hiddenCategoryKeys: [],
            displayMode: "selected_subjects",
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

    async onYearChange(ev) {
        const yearId = parseInt(ev.target.value, 10);
        this.state.selectedYearId = yearId || null;
        this._saveYearSelection();
        this.state.selectedClassIds = [];
        this.state.selectedStudentId = null;
        this.state.selectedSubjectIds = [];
        this.state.subjectDropdownResetKey += 1;
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
        this._saveSubjectSelection([]);
        await this._loadClasses();
    }

    async _loadClasses() {
        try {
            const args = this.state.selectedYearId ? [this.state.selectedYearId] : [];
            const classes = await this.orm.call("aps.student.matrix", "get_home_classes", args);
            this.state.classes = classes || [];
            this.state.selectedClassIds = this.state.classes.map((classItem) => classItem.id);
            await this._loadMatrix();
        } catch (err) {
            console.error("StudentMatrix: failed to load classes", err);
            this.state.classes = [];
            this.state.selectedClassIds = [];
        }
    }

    _saveSubjectSelection(subjectIds) {
        try {
            if (subjectIds.length) {
                localStorage.setItem(this._SUBJECT_STORAGE_KEY, JSON.stringify(subjectIds));
            } else {
                localStorage.removeItem(this._SUBJECT_STORAGE_KEY);
            }
        } catch (err) {
            console.warn("StudentMatrix: failed to save subject selection", err);
        }
    }

    _restoreSubjectSelection() {
        let savedSubjectIds = [];
        try {
            const raw = localStorage.getItem(this._SUBJECT_STORAGE_KEY);
            const saved = raw ? JSON.parse(raw) : [];
            savedSubjectIds = Array.isArray(saved) ? saved : saved ? [saved] : [];
        } catch (err) {
            console.warn("StudentMatrix: failed to restore subject selection", err);
            this._saveSubjectSelection([]);
            this.state.selectedSubjectIds = [];
            return;
        }
        const availableSubjectIds = new Set(
            this.state.subjects.map((subject) => subject.id)
        );
        this.state.selectedSubjectIds = [
            ...new Set(
                savedSubjectIds
                    .map(Number)
                    .filter(
                        (subjectId) =>
                            Number.isInteger(subjectId) &&
                            subjectId > 0 &&
                            availableSubjectIds.has(subjectId)
                    )
            ),
        ];
        this._saveSubjectSelection(this.state.selectedSubjectIds);
    }

    async _loadSubjectLevelsIfMissing() {
        if (
            !this.state.subjects.some(
                (subject) =>
                    !Object.prototype.hasOwnProperty.call(subject, "level_name") ||
                    !Object.prototype.hasOwnProperty.call(subject, "level_sequence")
            )
        ) {
            return;
        }
        try {
            const subjectIds = this.state.subjects.map((subject) => subject.id);
            const records = await this.orm.call(
                "aps.subject",
                "read",
                [subjectIds, ["level_id"]]
            );
            const levelBySubjectId = new Map(
                records.map((record) => [record.id, record.level_id])
            );
            const levelIds = [
                ...new Set(
                    records
                        .map((record) =>
                            Array.isArray(record.level_id)
                                ? record.level_id[0]
                                : record.level_id
                        )
                        .filter(Boolean)
                ),
            ];
            const levels = levelIds.length
                ? await this.orm.call("aps.level", "read", [levelIds, ["sequence"]])
                : [];
            const sequenceByLevelId = new Map(
                levels.map((level) => [level.id, level.sequence])
            );
            this.state.subjects = this.state.subjects.map((subject) => {
                const level = levelBySubjectId.get(subject.id);
                const levelId = Array.isArray(level) ? level[0] : level || false;
                return {
                    ...subject,
                    level_id: levelId,
                    level_name: subject.level_name ?? (
                        Array.isArray(level) ? level[1] : "Unassigned"
                    ),
                    level_sequence:
                        sequenceByLevelId.get(levelId) ?? subject.level_sequence ?? 999999,
                };
            });
        } catch (err) {
            console.error("StudentMatrix: failed to load subject levels", err);
        }
    }

    onSubjectChange(subjectIds) {
        this.state.selectedSubjectIds = [
            ...new Set((Array.isArray(subjectIds) ? subjectIds : []).map(Number)),
        ];
        this.state.selectedStudentId = null;
        this.state.selectedCategoryKey = null;
        this._saveSubjectSelection(this.state.selectedSubjectIds);
    }

    onSubjectGroupByChange(ev) {
        this.state.subjectGroupBy = ev.target.value === "category" ? "category" : "level";
    }

    async _loadMatrix() {
        if (this.state.selectedClassIds.length === 0) {
            this.state.selectedStudentId = null;
            this.state.selectedSubjectIds = [];
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
            this._saveSubjectSelection([]);
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
            this.state.selectedSubjectIds = [];
            this.state.selectedCategoryKey = null;
            this.state.hiddenSubjectIds = [];
            this.state.hiddenCategoryKeys = [];
            this.state.subjects = data.subjects || [];
            await this._loadSubjectLevelsIfMissing();
            this._restoreSubjectSelection();
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

    get isCategoryDisplay() {
        return (
            this.state.displayMode === "selected_categories" ||
            this.state.displayMode === "all_categories"
        );
    }

    get visibleStudents() {
        if (!this.state.selectedSubjectIds.length) {
            return [];
        }
        let students = this.state.students;
        const allSubjectsSelected = this.state.subjects.every((subject) =>
            this.state.selectedSubjectIds.includes(subject.id)
        );
        if (!allSubjectsSelected) {
            students = students.filter((student) =>
                this.state.selectedSubjectIds.some((subjectId) =>
                    this.hasCell(student.id, subjectId)
                )
            )
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
        const visibleStudentIds = new Set(
            this.visibleStudents.map((student) => student.id)
        );
        return this.state.subjects.filter((subject) =>
            [...visibleStudentIds].some((studentId) =>
                this.hasCell(studentId, subject.id)
            )
        ).filter((subject) =>
            (this.state.displayMode === "all_subjects" ||
                this.state.selectedSubjectIds.includes(subject.id)) &&
            !this.state.hiddenSubjectIds.includes(subject.id)
        );
    }

    get subjectOptions() {
        const groupByLevel = this.state.subjectGroupBy === "level";
        const options = this.state.subjects.map((subject) => ({
            value: subject.id,
            label: this.getSubjectDisplayName(subject),
            iconUrl: subject.icon_url || `/web/image/aps.subject/${subject.id}/icon`,
            fallbackIconUrl: subject.category_id
                ? `/web/image/aps.subject.category/${subject.category_id}/icon`
                : false,
            group: groupByLevel
                ? subject.level_name || "Unassigned"
                : subject.category_name || "Uncategorized",
            groupSequence: groupByLevel ? subject.level_sequence ?? 999999 : 0,
        }));
        return options.sort((first, second) => {
            if (groupByLevel) {
                const sequenceDifference = first.groupSequence - second.groupSequence;
                if (sequenceDifference) {
                    return sequenceDifference;
                }
            }
            return (
                first.group.localeCompare(second.group) ||
                first.label.localeCompare(second.label)
            );
        });
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
        const visibleStudentIds = new Set(
            this.visibleStudents.map((student) => student.id)
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
                    (this.state.displayMode === "all_categories" ||
                        category.subjects.some((subject) =>
                            this.state.selectedSubjectIds.includes(subject.id)
                        )) &&
                    !this.state.hiddenCategoryKeys.includes(category.categoryKey)
            );
    }

    get visibleColumns() {
        if (this.isCategoryDisplay) {
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
        return this.visibleStudents.reduce(
            (total, student) => total + this.getCategorySubjectCount(student.id, column),
            0
        );
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
            ? this.state.selectedSubjectIds.includes(column.id)
            : this.state.selectedCategoryKey === column.categoryKey;
    }

    onStudentClick(studentId) {
        this.state.selectedCategoryKey = null;
        this.state.selectedStudentId =
            this.state.selectedStudentId === studentId ? null : studentId;
    }

    onShowAllStudents() {
        this.state.selectedStudentId = null;
        this.state.selectedCategoryKey = null;
    }

    onDisplayModeChange(ev) {
        const validModes = [
            "selected_subjects",
            "all_subjects",
            "selected_categories",
            "all_categories",
        ];
        this.state.displayMode = validModes.includes(ev.target.value)
            ? ev.target.value
            : "selected_subjects";
        this.state.selectedCategoryKey = null;
        this.state.hiddenSubjectIds = [];
        this.state.hiddenCategoryKeys = [];
    }

    onColumnClick(column) {
        this.state.selectedStudentId = null;
        if (column.type === "subject") {
            this.state.selectedCategoryKey = null;
            const isOnlySelectedSubject =
                this.state.selectedSubjectIds.length === 1 &&
                this.state.selectedSubjectIds[0] === column.id;
            if (this.state.displayMode === "all_subjects") {
                this.state.displayMode = "selected_subjects";
                this.state.selectedSubjectIds = [column.id];
                this._saveSubjectSelection(this.state.selectedSubjectIds);
            } else if (isOnlySelectedSubject) {
                this.state.displayMode = "all_subjects";
            } else {
                this.state.selectedSubjectIds = [column.id];
                this._saveSubjectSelection(this.state.selectedSubjectIds);
            }
            this.state.hiddenSubjectIds = [];
            return;
        }
        this.state.selectedCategoryKey =
            this.state.selectedCategoryKey === column.categoryKey
                ? null
                : column.categoryKey;
    }

    onShowAllColumns() {
        this.state.displayMode = this.isCategoryDisplay
            ? "all_categories"
            : "all_subjects";
        this.state.selectedCategoryKey = null;
        this.state.hiddenSubjectIds = [];
        this.state.hiddenCategoryKeys = [];
    }

    onColumnTotalClick(column) {
        this.state.selectedStudentId = null;
        this.state.selectedCategoryKey = null;
        if (column.type === "subject") {
            if (!this.state.hiddenSubjectIds.includes(column.id)) {
                this.state.hiddenSubjectIds.push(column.id);
            }
            if (
                this.state.displayMode === "selected_subjects" &&
                this.state.selectedSubjectIds.length === 1 &&
                this.state.selectedSubjectIds[0] === column.id
            ) {
                this.state.displayMode = "all_subjects";
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