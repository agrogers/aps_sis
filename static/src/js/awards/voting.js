(function () {
    'use strict';

    const AwardsVoting = {
        // ----------------------------------------------------------------
        // State
        // ----------------------------------------------------------------
        _token: null,
        _categoryId: null,
        _categoryName: null,
        _voteId: null,
        _candidates: [],       // full list from server
        _filtered: [],         // after search + filter
        _selected: new Set(),  // selected partner IDs
        _comments: new Map(),  // per-student comments, keyed by partner id
        _subCategories: [],    // [{id, name}] for the current category
        _subCategorySelections: new Map(), // per-student sub-category id
        _subjectCats: [],      // [{id, name}] for the current category
        _sortKey: 'name',
        _sortAsc: true,
        _voteLimit: 0,         // 0 = no limit; >0 = max allowed selections
        _isStaffRound: false,  // true when all candidates are staff (department-based)
        _limitToOwnStudents: 'no',    // 'no' | 'yes' | 'optional'
        _ownStudentPartnerIds: null,  // Set of partner IDs for the voter's own students
        _ownStudentsOnly: false,      // active state of the optional toggle
        _allowNoVote: false,          // voter may submit with no recipient selected

        // ----------------------------------------------------------------
        // Modal open / close
        // ----------------------------------------------------------------
        openModal(btn) {
            this._token        = btn.dataset.token;
            this._categoryId   = parseInt(btn.dataset.categoryId, 10) || 0;
            this._categoryName = btn.dataset.categoryName;
            this._voteId       = btn.dataset.voteId ? parseInt(btn.dataset.voteId, 10) : null;
            const imgSrc       = btn.dataset.categoryImg || '';
            this._selected.clear();
            this._comments.clear();
            this._subCategories = [];
            this._subCategorySelections.clear();
            this._subjectCats = [];
            this._sortKey = 'name';
            this._sortAsc = true;
            this._voteLimit = 0;
            this._isStaffRound = false;
            this._showTimesAwarded = true;
            this._showLastAwarded = true;
            this._showLevelDept = true;
            this._limitToOwnStudents = 'no';
            this._ownStudentPartnerIds = null;
            this._ownStudentsOnly = false;
            this._allowNoVote = false;
            this._removeOwnStudentsToggle();

            // Collapse the filter panel each time the modal opens
            const filterPanel = document.getElementById('av-filters');
            const filterToggle = document.getElementById('av-filter-toggle');
            if (filterPanel) filterPanel.classList.remove('av-filters--open');
            if (filterToggle) filterToggle.classList.remove('av-filter-toggle--active');

            document.getElementById('av-modal-cat-name').textContent = this._categoryName;

            const shortDesc = btn.dataset.shortDescription || '';
            const descEl = document.getElementById('av-modal-cat-short-desc');
            descEl.textContent = shortDesc;
            descEl.style.display = shortDesc ? '' : 'none';

            const desc = btn.dataset.description || '';
            const fullDescEl = document.getElementById('av-modal-cat-desc');
            fullDescEl.textContent = desc;
            fullDescEl.style.display = desc ? '' : 'none';

            const modalImg = document.getElementById('av-modal-cat-img');
            if (imgSrc) {
                modalImg.src = imgSrc;
                modalImg.style.display = 'block';
            } else {
                modalImg.src = '';
                modalImg.style.display = 'none';
            }
            document.getElementById('av-modal-selection-summary').style.display = 'none';
            document.getElementById('av-submit-btn').style.display = 'none';
            document.getElementById('av-submit-error').style.display = 'none';
            document.getElementById('av-search').value = '';
            const desktopSearch = document.getElementById('av-search-desktop');
            if (desktopSearch) desktopSearch.value = '';
            document.getElementById('av-candidate-list').innerHTML =
                '<tr><td colspan="6" class="av-loading">Loading candidates…</td></tr>';

            document.getElementById('av-modal').style.display = 'flex';
            document.body.style.overflow = 'hidden';

            this._populateFilters();
            this.loadCandidates();
        },

        closeModal() {
            document.getElementById('av-modal').style.display = 'none';
            document.body.style.overflow = '';
        },

        overlayClick(e) {
            if (e.target === document.getElementById('av-modal')) this.closeModal();
        },

        // ----------------------------------------------------------------
        // Filters — populate from candidate data returned by server
        // ----------------------------------------------------------------
        _populateFilters() {
            document.getElementById('av-filter-level').innerHTML =
                '<option value="">All Year Levels</option>';
            document.getElementById('av-filter-subject-cat').innerHTML =
                '<option value="">All Subject Categories</option>';
        },

        // ----------------------------------------------------------------
        // Own-students toggle (shown only when rule == 'optional')
        // ----------------------------------------------------------------
        _setupOwnStudentsToggle() {
            this._removeOwnStudentsToggle();
            if (this._limitToOwnStudents !== 'optional') return;

            const makeBtn = (id) => {
                const btn = document.createElement('button');
                btn.id = id;
                btn.className = 'av-filter-toggle' + (this._ownStudentsOnly ? ' av-filter-toggle--active' : '');
                btn.title = 'Toggle between your students and all eligible candidates';
                btn.textContent = this._ownStudentsOnly ? '\uD83D\uDC64 My Students' : '\uD83D\uDC65 All Students';
                return btn;
            };

            const syncBtns = () => {
                ['av-own-students-toggle', 'av-own-students-toggle-desktop'].forEach(id => {
                    const b = document.getElementById(id);
                    if (!b) return;
                    b.className = 'av-filter-toggle' + (this._ownStudentsOnly ? ' av-filter-toggle--active' : '');
                    b.textContent = this._ownStudentsOnly ? '\uD83D\uDC64 My Students' : '\uD83D\uDC65 All Students';
                });
            };

            const onClick = () => {
                this._ownStudentsOnly = !this._ownStudentsOnly;
                syncBtns();
                this._populateLevelFilter(this._getVisibleCandidatePool());
                this._applySearch();
                this._renderTable();
            };

            // Mobile bar
            const bar = document.getElementById('av-filters-bar');
            if (bar) {
                const btn = makeBtn('av-own-students-toggle');
                btn.addEventListener('click', onClick);
                bar.insertBefore(btn, bar.firstChild);
            }

            // Desktop filters panel
            const panel = document.getElementById('av-filters');
            if (panel) {
                const btnD = makeBtn('av-own-students-toggle-desktop');
                btnD.addEventListener('click', onClick);
                panel.insertBefore(btnD, panel.firstChild);
            }
        },

        _removeOwnStudentsToggle() {
            ['av-own-students-toggle', 'av-own-students-toggle-desktop'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.remove();
            });
        },

        _getSearchValue() {
            const mobile = document.getElementById('av-search');
            const desktop = document.getElementById('av-search-desktop');
            const m = mobile ? (mobile.value || '') : '';
            const d = desktop ? (desktop.value || '') : '';
            return (d || m).toLowerCase();
        },

        _populateSubjectCatFilter(subjectCats) {
            this._subjectCats = subjectCats || [];
            const sel = document.getElementById('av-filter-subject-cat');
            const saved = localStorage.getItem('av_filter_subject_cat') || '';
            if (this._subjectCats.length === 0) {
                sel.innerHTML = '<option value="">All Subject Categories</option>';
                return;
            }
            sel.innerHTML = '<option value="">All Subject Categories</option>' +
                this._subjectCats.map(sc =>
                    `<option value="${sc.id}"${String(sc.id) === saved ? ' selected' : ''}>${this._esc(sc.name)}</option>`
                ).join('');
        },

        // ----------------------------------------------------------------
        // Load candidates via JSON RPC (no filters — filtering is client-side)
        // ----------------------------------------------------------------
        loadCandidates() {
            this._jsonRpc(
                `/awards/vote/${this._token}/candidates/${this._categoryId}`,
                { vote_id: this._voteId }
            ).then(result => {
                if (result.error) {
                    this._showError('Could not load candidates: ' + result.error);
                    return;
                }
                this._candidates = result.candidates || [];
                this._subCategories = result.sub_categories || [];
                this._voteLimit = result.vote_limit || 0;
                this._showTimesAwarded = result.show_times_awarded !== false;
                this._showLastAwarded  = result.show_last_awarded  !== false;
                this._showLevelDept    = result.show_level_dept    !== false;
                this._isStaffRound = this._candidates.length > 0 && this._candidates.every(c => c.is_staff === true);
                this._limitToOwnStudents = result.limit_candidates_to_own_students || 'no';
                this._ownStudentPartnerIds = new Set(result.own_student_partner_ids || []);
                this._allowNoVote = result.allow_no_vote === true;
                // Default the optional toggle to ON (show only own students)
                this._ownStudentsOnly = this._limitToOwnStudents === 'optional';
                this._populateLevelFilter(this._getVisibleCandidatePool());
                this._applyColumnVisibility();
                this._populateSubjectCatFilter(result.subject_cats || []);
                this._setupOwnStudentsToggle();
                this._updateSelectionUI();
                this._applySearch();
                this._renderTable();
            }).catch(() => {
                document.getElementById('av-candidate-list').innerHTML =
                    '<tr><td colspan="7" class="av-no-results">Failed to load candidates. Please try again.</td></tr>';
            });
        },

        _populateLevelFilter(candidates) {
            const pool = candidates || this._candidates;
            const subCatSel = document.getElementById('av-filter-subject-cat');
            if (this._isStaffRound) {
                // For staff rounds show department filter instead of level
                const levels = [...new Set(pool.map(c => c.department).filter(Boolean))].sort();
                const sel = document.getElementById('av-filter-level');
                const saved = localStorage.getItem('av_filter_level') || '';
                sel.innerHTML = '<option value="">All Departments</option>' +
                    levels.map(l => `<option value="${l}"${l === saved ? ' selected' : ''}>${l}</option>`).join('');
                // Update column header
                const levelTh = document.querySelector('.av-th-level');
                if (levelTh) levelTh.textContent = 'Department';
                // Hide subject category filter — not relevant for staff rounds
                if (subCatSel) subCatSel.style.display = 'none';
            } else {
                if (subCatSel) subCatSel.style.display = '';
                const levels = [...new Set(pool.map(c => c.level).filter(Boolean))].sort();
                const sel = document.getElementById('av-filter-level');
                const saved = localStorage.getItem('av_filter_level') || '';
                sel.innerHTML = '<option value="">All Year Levels</option>' +
                    levels.map(l => `<option value="${l}"${l === saved ? ' selected' : ''}>${l}</option>`).join('');
                const levelTh = document.querySelector('.av-th-level');
                if (levelTh) levelTh.textContent = 'Level';
            }
        },

        _getVisibleCandidatePool() {
            if (this._ownStudentsOnly && this._ownStudentPartnerIds && this._ownStudentPartnerIds.size > 0) {
                return this._candidates.filter(c => this._ownStudentPartnerIds.has(c.id));
            }
            return this._candidates;
        },

        // ----------------------------------------------------------------
        // Column visibility
        // ----------------------------------------------------------------
        _applyColumnVisibility() {
            const setCol = (thClass, show) => {
                const th = document.querySelector(thClass);
                if (th) th.style.display = show ? '' : 'none';
            };
            setCol('.av-th-level', this._showLevelDept);
            setCol('.av-th-times', this._showTimesAwarded);
            setCol('.av-th-last',  this._showLastAwarded);
        },

        // ----------------------------------------------------------------
        // Filter panel toggle (mobile)
        // ----------------------------------------------------------------
        toggleFilters() {
            const panel  = document.getElementById('av-filters');
            const btn    = document.getElementById('av-filter-toggle');
            const isOpen = panel.classList.toggle('av-filters--open');
            btn.classList.toggle('av-filter-toggle--active', isOpen);
        },

        // ----------------------------------------------------------------
        // Search filter
        // ----------------------------------------------------------------
        filterSearch() {
            localStorage.setItem('av_filter_level',
                document.getElementById('av-filter-level').value);
            localStorage.setItem('av_filter_subject_cat',
                document.getElementById('av-filter-subject-cat').value);
            const mobile = document.getElementById('av-search');
            const desktop = document.getElementById('av-search-desktop');
            if (mobile && desktop) {
                if (document.activeElement === desktop) mobile.value = desktop.value;
                else if (document.activeElement === mobile) desktop.value = mobile.value;
            }
            this._applySearch();
            this._renderTable();
        },

        _applySearch() {
            const q = this._getSearchValue();
            const levelOrDept = document.getElementById('av-filter-level').value;
            const subCatId = parseInt(document.getElementById('av-filter-subject-cat').value || '0', 10);

            const ownStudentsActive = this._ownStudentsOnly &&
                this._ownStudentPartnerIds && this._ownStudentPartnerIds.size > 0;

            this._filtered = this._candidates.filter(c => {
                const nameMatch = !q || c.name.toLowerCase().includes(q);
                let levelMatch;
                if (this._isStaffRound) {
                    levelMatch = !levelOrDept || c.department === levelOrDept;
                } else {
                    levelMatch = !levelOrDept || c.level === levelOrDept;
                }
                // Whitelisted students (explicitly selected in eligible_candidates) always
                // pass the subject-category filter — they were hand-picked regardless of class.
                const subCatMatch = !subCatId || c.whitelisted ||
                    (c.subject_cat_ids && c.subject_cat_ids.includes(subCatId));
                const ownStudentMatch = !ownStudentsActive || this._ownStudentPartnerIds.has(c.id);
                return nameMatch && levelMatch && subCatMatch && ownStudentMatch;
            });

            this._sortCandidates();
        },

        // ----------------------------------------------------------------
        // Sorting
        // ----------------------------------------------------------------
        sortBy(key) {
            if (this._sortKey === key) {
                this._sortAsc = !this._sortAsc;
            } else {
                this._sortKey = key;
                this._sortAsc = key === 'name' || key === 'level';
            }
            this._sortCandidates();
            this._renderTable();
        },

        _sortCandidates() {
            const key = this._sortKey;
            const asc = this._sortAsc ? 1 : -1;
            this._filtered.sort((a, b) => {
                let va = a[key], vb = b[key];
                if (key === 'times_awarded') { va = va || 0; vb = vb || 0; }
                else if (key === 'last_awarded') {
                    va = va || '0000-00-00'; vb = vb || '0000-00-00';
                }
                else { va = (va || '').toString().toLowerCase(); vb = (vb || '').toString().toLowerCase(); }
                if (va < vb) return -1 * asc;
                if (va > vb) return  1 * asc;
                return 0;
            });
        },

        // ----------------------------------------------------------------
        // Render candidate table
        // ----------------------------------------------------------------
        _renderTable() {
            const tbody = document.getElementById('av-candidate-list');
            const colCount = 3 + (this._showLevelDept ? 1 : 0) + (this._showTimesAwarded ? 1 : 0) + (this._showLastAwarded ? 1 : 0);
            if (!this._filtered.length) {
                tbody.innerHTML = `<tr><td colspan="${colCount}" class="av-no-results">No ${this._isStaffRound ? 'staff' : 'students'} found.</td></tr>`;
                return;
            }

            const atLimit = this._voteLimit > 0 && this._selected.size >= this._voteLimit;

            const rows = [];
            for (const c of this._filtered) {
                const sel = this._selected.has(c.id);
                const photo = c.image_url
                    ? `<img src="${this._esc(c.image_url)}" alt="${this._esc(c.name)}" loading="lazy" decoding="async">`
                    : c.image
                    ? `<img src="data:image/png;base64,${c.image}" alt="${this._esc(c.name)}" loading="lazy" decoding="async">`
                    : `<div class="av-initials">${this._initials(c.name)}</div>`;
                const lastDate = c.last_awarded
                    ? new Date(c.last_awarded).toLocaleDateString()
                    : '—';
                const levelOrDept = this._isStaffRound
                    ? this._esc(c.department || '')
                    : this._esc(c.level || '');

                // Disable unselected rows when at the vote limit
                const rowDisabled = !sel && atLimit;
                const rowClass = sel ? 'av-selected' : (rowDisabled ? 'av-disabled' : '');
                const clickHandler = rowDisabled ? '' : `onclick="AwardsVoting.toggleSelect(${c.id})"`;

                rows.push(`<tr class="${rowClass}" data-id="${c.id}" ${clickHandler}>
                    <td class="av-td-photo">${photo}</td>
                    <td class="av-td-name">${this._esc(c.name)}</td>
                    ${this._showLevelDept    ? `<td class="av-td-level">${levelOrDept}</td>` : ''}
                    ${this._showTimesAwarded ? `<td class="av-td-times">${c.times_awarded}</td>` : ''}
                    ${this._showLastAwarded  ? `<td class="av-td-last">${lastDate}</td>` : ''}
                    <td class="av-td-select"><div class="av-select-check">${sel ? '\u2713' : ''}</div></td>
                </tr>`);

                if (sel) {
                    const existingComment = this._esc(this._comments.get(c.id) || '');
                    const hasSubs = this._subCategories.length > 0;
                    const selectedSub = this._subCategorySelections.get(c.id) || '';
                    let extraCells = '';
                    if (hasSubs) {
                        const options = this._subCategories.map(sc =>
                            `<option value="${sc.id}"${sc.id === selectedSub ? ' selected' : ''}>${this._esc(sc.name)}</option>`
                        ).join('');
                        extraCells += `<div class="av-sub-cat-wrap">
                            <label class="av-sub-cat-label">Sub-category <span class="av-required">*</span></label>
                            <select class="av-sub-cat-select"
                                    onchange="AwardsVoting.saveSubCategory(${c.id}, this.value)"
                                    onclick="event.stopPropagation()">
                                <option value="">— select —</option>
                                ${options}
                            </select>
                        </div>`;
                    }
                    extraCells += `<div class="av-comment-wrap">
                        <textarea class="av-row-comment"
                                  placeholder="Comment for ${this._esc(c.name)} (optional)"
                                  oninput="AwardsVoting.saveComment(${c.id}, this.value)"
                                  onclick="event.stopPropagation()">${existingComment}</textarea>
                    </div>`;
                    rows.push(`<tr class="av-comment-row" data-comment-for="${c.id}">
                        <td colspan="7" class="av-td-comment">${extraCells}</td>
                    </tr>`);
                }
            }
            tbody.innerHTML = rows.join('');
        },

        saveComment(id, value) {
            if (value.trim()) {
                this._comments.set(id, value);
            } else {
                this._comments.delete(id);
            }
        },

        saveSubCategory(id, value) {
            if (value) {
                this._subCategorySelections.set(id, parseInt(value, 10));
            } else {
                this._subCategorySelections.delete(id);
            }
            // Remove error highlight from this select
            const row = document.querySelector(`tr.av-comment-row[data-comment-for="${id}"]`);
            if (row) {
                const sel = row.querySelector('.av-sub-cat-select');
                if (sel) sel.classList.remove('av-sub-cat-error');
            }
            // If no more missing sub-categories, clear the error message
            const stillMissing = [...this._selected].some(
                sid => !this._subCategorySelections.has(sid)
            );
            if (!stillMissing) {
                document.getElementById('av-submit-error').style.display = 'none';
            }
        },

        // ----------------------------------------------------------------
        // Toggle student selection
        // ----------------------------------------------------------------
        toggleSelect(id) {
            if (this._selected.has(id)) {
                this._selected.delete(id);
                this._comments.delete(id);
                this._subCategorySelections.delete(id);
            } else {
                // Enforce vote limit
                if (this._voteLimit > 0 && this._selected.size >= this._voteLimit) {
                    this._showToast(
                        `You can only vote for ${this._voteLimit} ${this._voteLimit === 1 ? 'person' : 'people'} in this round.`,
                        'error'
                    );
                    return;
                }
                this._selected.add(id);
            }
            this._updateSelectionUI();
            this._renderTable();
        },

        _updateSelectionUI() {
            const count = this._selected.size;
            const summary = document.getElementById('av-modal-selection-summary');
            const submitBtn = document.getElementById('av-submit-btn');

            if (count > 0) {
                const names = [...this._selected].map(id => {
                    const c = this._candidates.find(x => x.id === id);
                    return c ? c.name : 'Unknown';
                }).join(', ');

                let summaryText = `Selected: ${names}`;
                if (this._voteLimit > 0) {
                    summaryText += ` (${count}/${this._voteLimit})`;
                }
                summary.textContent = summaryText;
                summary.style.display = 'block';
                summary.classList.toggle('av-summary-max', this._voteLimit > 0 && count >= this._voteLimit);
                submitBtn.textContent = count === 1
                    ? `Submit Vote for ${names}`
                    : `Submit ${count} Votes`;
                submitBtn.style.color = '';
                submitBtn.style.background = '';
                submitBtn.style.display = 'inline-block';
            } else if (this._allowNoVote) {
                summary.style.display = 'none';
                submitBtn.textContent = "Don't Submit A Vote";
                submitBtn.style.background = '#e67e22';
                submitBtn.style.color = '#fff';
                submitBtn.style.display = 'inline-block';
            } else {
                summary.style.display = 'none';
                submitBtn.style.display = 'none';
                submitBtn.style.color = '';
                submitBtn.style.background = '';
            }
        },

        // ----------------------------------------------------------------
        // Submit
        // ----------------------------------------------------------------
        submitVote() {
            if (!this._selected.size && !this._allowNoVote) return;

            // Validate sub-category if this category has any
            if (this._subCategories.length > 0) {
                const missing = new Set(
                    [...this._selected].filter(id => !this._subCategorySelections.has(id))
                );
                if (missing.size) {
                    // 1. Show only selected rows so the user can see what needs fixing
                    this._filtered = this._candidates.filter(c => this._selected.has(c.id));
                    this._sortCandidates();
                    this._renderTable();

                    // 2. Highlight the empty sub-category selects in red
                    missing.forEach(id => {
                        const row = document.querySelector(
                            `tr.av-comment-row[data-comment-for="${id}"]`
                        );
                        if (row) {
                            const sel = row.querySelector('.av-sub-cat-select');
                            if (sel) sel.classList.add('av-sub-cat-error');
                        }
                    });

                    // 3. Show an inline error message below the submit button
                    const errEl = document.getElementById('av-submit-error');
                    const names = [...missing].map(id => {
                        const c = this._candidates.find(x => x.id === id);
                        return c ? c.name : 'Unknown';
                    }).join(', ');
                    errEl.textContent =
                        `⚠️ Sub-category required for: ${names}`;
                    errEl.style.display = 'block';
                    return;
                }
            }

            // Flush any textarea values still in the DOM (in case oninput hasn't fired)
            document.querySelectorAll('.av-row-comment').forEach(ta => {
                const id = parseInt(ta.closest('tr').dataset.commentFor, 10);
                if (ta.value.trim()) this._comments.set(id, ta.value);
            });

            const recipients = [...this._selected].map(id => ({
                id,
                comment: this._comments.get(id) || '',
                sub_category_id: this._subCategorySelections.get(id) || null,
            }));

            const btn = document.getElementById('av-submit-btn');
            btn.disabled = true;
            btn.textContent = 'Submitting…';            btn.style.background = '';
            btn.style.color = '';
            this._jsonRpc(`/awards/vote/${this._token}/submit`, {
                category_id: this._categoryId,
                vote_id: this._voteId,
                recipients,
            }).then(result => {
                if (result.error) {
                    this._showToast('Error: ' + result.error, 'error');
                    btn.disabled = false;
                    this._updateSelectionUI();
                } else {
                    this._showToast('Vote submitted! 🎉', 'success');
                    this.closeModal();
                    // Refresh page stats after short delay
                    setTimeout(() => window.location.reload(), 1800);
                }
            }).catch(() => {
                this._showToast('Submission failed. Please try again.', 'error');
                btn.disabled = false;
                this._updateSelectionUI();
            });
        },

        // ----------------------------------------------------------------
        // Custom confirm dialog (replaces browser confirm())
        // ----------------------------------------------------------------
        _confirm(title, message, { isUndo = false } = {}) {
            return new Promise(resolve => {
                const overlay = document.createElement('div');
                overlay.className = 'av-confirm-overlay';
                const iconClass = isUndo ? 'av-confirm-icon av-confirm-icon--undo' : 'av-confirm-icon';
                const iconGlyph = isUndo ? '↩' : '🗑';
                const okClass = isUndo ? 'av-confirm-btn av-confirm-btn--ok' : 'av-confirm-btn av-confirm-btn--ok danger';
                const okLabel = isUndo ? 'Undo' : 'Delete';
                overlay.innerHTML = `
                    <div class="av-confirm-box">
                        <div style="display:flex;align-items:flex-start;gap:.85rem">
                            <div class="${iconClass}">${iconGlyph}</div>
                            <div>
                                <div class="av-confirm-title">${title}</div>
                                <div class="av-confirm-msg">${message}</div>
                            </div>
                        </div>
                        <div class="av-confirm-actions">
                            <button class="av-confirm-btn av-confirm-btn--cancel">Cancel</button>
                            <button class="${okClass}">${okLabel}</button>
                        </div>
                    </div>`;
                const [cancelBtn, okBtn] = overlay.querySelectorAll('.av-confirm-btn');
                const cleanup = (result) => { overlay.remove(); resolve(result); };
                cancelBtn.addEventListener('click', () => cleanup(false));
                okBtn.addEventListener('click', () => cleanup(true));
                overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(false); });
                document.body.appendChild(overlay);
                okBtn.focus();
            });
        },

        // ----------------------------------------------------------------
        // Delete / revert history vote
        // ----------------------------------------------------------------
        deleteVote(btn) {
            const voteIds = (btn.dataset.voteIds || btn.dataset.voteId || '')
                .split(',').map(s => parseInt(s.trim(), 10)).filter(Boolean);
            const token = btn.dataset.token;
            const hasDue = btn.dataset.hasDue === '1';
            const count = voteIds.length;
            const isUndo = hasDue;
            const title = isUndo
                ? (count > 1 ? `Undo ${count} votes` : 'Undo vote')
                : (count > 1 ? `Delete ${count} votes` : 'Delete vote');
            const msg = isUndo
                ? (count > 1
                    ? `Undo all ${count} votes in this round? They will be reverted to Open so you can re-submit.`
                    : 'Undo this vote? It will be reverted to Open so you can re-submit.')
                : (count > 1
                    ? `Permanently delete all ${count} votes in this round?`
                    : 'Permanently delete this vote?');
            this._confirm(title, msg, { isUndo }).then(confirmed => {
                if (!confirmed) return;

            btn.disabled = true;
            btn.textContent = '…';
            this._jsonRpc(`/awards/vote/${token}/votes/delete`, { vote_ids: voteIds }).then(result => {
                if (result.error) {
                    this._showToast('Error: ' + result.error, 'error');
                    btn.disabled = false;
                    btn.textContent = hasDue ? '↩ Undo' : '✕ Delete';
                } else {
                    const row = btn.closest('.av-history-row');
                    row.style.transition = 'opacity .3s';
                    row.style.opacity = '0';
                    setTimeout(() => {
                        row.remove();
                        setTimeout(() => window.location.reload(), 400);
                    }, 300);
                }
            }).catch(() => {
                this._showToast('Request failed. Please try again.', 'error');
                btn.disabled = false;
                btn.textContent = hasDue ? '↩ Undo' : '✕ Delete';
            });
            }); // end _confirm
        },

        // ----------------------------------------------------------------
        // JSON-RPC helper
        // ----------------------------------------------------------------
        _jsonRpc(url, params) {
            return fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    id: Date.now(),
                    params: params,
                }),
            }).then(r => r.json()).then(r => r.result !== undefined ? r.result : r);
        },

        // ----------------------------------------------------------------
        // Helpers
        // ----------------------------------------------------------------
        _esc(str) {
            return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        },

        _initials(name) {
            return (name || '?').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
        },

        _showToast(msg, type = 'success') {
            const t = document.createElement('div');
            t.className = `av-toast av-toast--${type}`;
            t.textContent = msg;
            document.body.appendChild(t);
            setTimeout(() => t.remove(), 3500);
        },

        _showError(msg) {
            document.getElementById('av-candidate-list').innerHTML =
                `<tr><td colspan="6" class="av-no-results">${this._esc(msg)}</td></tr>`;
        },
    };

    window.AwardsVoting = AwardsVoting;
})();
