import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";

export class PastPaperProgress extends Component {
    static template = "aps_sis.PastPaperProgress";
    static components = { PercentPie };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            loading: true,
            error: false,
            role: false,
            categories: [],
            students: [],
            papers: [],
            categoryId: 0,
            studentId: 0,
            paperFilter: "all",
            activePaperId: false,
            hoveredQuestionId: false,
            tooltipStyle: "",
            submissionViews: [],
        });
        this.onCategoryChange = this.onCategoryChange.bind(this);
        this.onStudentChange = this.onStudentChange.bind(this);
        this.onPaperFilterChange = this.onPaperFilterChange.bind(this);
        this.onPaperClick = this.onPaperClick.bind(this);
        this.onPaperKeydown = this.onPaperKeydown.bind(this);
        this.onQuestionMouseEnter = this.onQuestionMouseEnter.bind(this);
        this.onQuestionMouseLeave = this.onQuestionMouseLeave.bind(this);
        this.onQuestionClick = this.onQuestionClick.bind(this);
        this.onHistoryClick = this.onHistoryClick.bind(this);
        this.closePaperDialog = this.closePaperDialog.bind(this);
        this.stopDialogClick = this.stopDialogClick.bind(this);
        this.assignPaper = this.assignPaper.bind(this);
        onWillStart(() => this.load());
    }

    get visiblePapers() {
        if (this.state.paperFilter === "attempted") {
            return this.state.papers.filter((paper) => paper.has_attempts);
        }
        if (this.state.paperFilter === "new") {
            return this.state.papers.filter((paper) => !paper.has_attempts);
        }
        return this.state.papers;
    }

    get activePaper() {
        return this.state.papers.find(
            (paper) => paper.id === this.state.activePaperId
        );
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const categoryId = Number(this.state.categoryId) || false;
            const studentId = Number(this.state.studentId) || false;
            const data = await this.orm.call(
                "aps.resources",
                "get_past_paper_progress_data",
                [categoryId, studentId]
            );
            Object.assign(this.state, data, { loading: false, error: false });
        } catch (error) {
            this.state.loading = false;
            this.state.error = error.message || "Unable to load Past Paper progress.";
        }
    }

    async onCategoryChange(event) {
        this.state.categoryId = Number(event.target.value) || 0;
        this.state.studentId = 0;
        this.state.activePaperId = false;
        await this.load();
    }

    async onStudentChange(event) {
        this.state.studentId = Number(event.target.value) || 0;
        this.state.activePaperId = false;
        await this.load();
    }

    onPaperFilterChange(event) {
        this.state.paperFilter = event.target.value;
    }

    onPaperClick(event) {
        this.state.activePaperId = Number(event.currentTarget.dataset.paperId);
    }

    onPaperKeydown(event) {
        if (
            event.currentTarget === event.target
            && (event.key === "Enter" || event.key === " ")
        ) {
            event.preventDefault();
            this.state.activePaperId = Number(event.currentTarget.dataset.paperId);
        }
    }

    onQuestionMouseEnter(event) {
        this.state.hoveredQuestionId = Number(event.currentTarget.dataset.questionId);
        const rect = event.currentTarget.getBoundingClientRect();
        const width = Math.min(320, window.innerWidth - 16);
        let top = rect.bottom + 8;
        if (top + 180 > window.innerHeight) {
            top = Math.max(8, rect.top - 188);
        }
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
        this.state.tooltipStyle = `top: ${top}px; left: ${left}px;`;
    }

    onQuestionMouseLeave() {
        this.state.hoveredQuestionId = false;
    }

    async onQuestionClick(event) {
        event.stopPropagation();
        const questionId = Number(event.currentTarget.dataset.questionId);
        const question = this.activePaper?.questions.find(
            (item) => item.id === questionId
        );
        if (!question) {
            return;
        }
        await this.openSubmissions(
            `Question submissions: ${question.name}`,
            question.related_resource_ids
        );
    }

    async onHistoryClick(event) {
        event.stopPropagation();
        const index = Number(event.currentTarget.dataset.historyIndex);
        const history = this.activePaper?.history[index];
        if (!history) {
            return;
        }
        await this.openSubmissions(
            `Past Paper submissions: ${history.label}`,
            this.activePaper.related_resource_ids,
            history.submission_ids
        );
    }

    async openSubmissions(name, resourceIds, submissionIds = false) {
        const studentId = Number(this.state.student_id) || Number(this.state.studentId);
        const domain = [
            ["task_id.student_id", "=", studentId],
            ["task_id.resource_id", "in", resourceIds],
        ];
        if (submissionIds) {
            domain.push(["id", "in", submissionIds]);
        }
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "aps.resource.submission",
            views: this.state.submission_views,
            domain,
            context: {},
        });
    }

    closePaperDialog() {
        this.state.activePaperId = false;
        this.state.hoveredQuestionId = false;
    }

    stopDialogClick(event) {
        event.stopPropagation();
    }

    async assignPaper() {
        const paper = this.activePaper;
        if (!paper) {
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const action = await this.orm.call(
                "aps.resources",
                "action_assign_past_paper",
                [
                    paper.id,
                    Number(this.state.studentId) || false,
                    Number(this.state.categoryId) || false,
                ]
            );
            this.closePaperDialog();
            await this.actionService.doAction(action);
        } catch (error) {
            this.state.loading = false;
            this.state.error = error.message || "Unable to start this Past Paper.";
        }
    }

    questionStyle(question) {
        const attempts = Number(question.attempts) || 0;
        const opacity = attempts ? Math.min((10 + attempts * 10) / 100, 0.8) : 0;
        const score = Number(question.weighted_result);
        const borderColor = attempts
            && question.weighted_result !== false
            && Number.isFinite(score)
            ? getColorForPercent(score)
            : "#cbd2d9";
        const borderWidth = question.has_children ? 2 : 1;
        return [
            `--attempt-opacity: ${opacity}`,
            `border: ${borderWidth}px solid ${borderColor}`,
        ].join(";");
    }

    paperStyle(paper) {
        const attempts = Number(paper.attempts) || 0;
        const opacity = attempts ? Math.min((10 + attempts * 10) / 100, 0.8) : 0;
        return `--paper-progress-opacity: ${opacity}`;
    }
}

registry.category("actions").add("aps_sis_past_paper_progress", PastPaperProgress);
