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

            document.getElementById('av-modal-cat-name').textContent = this._categoryName;
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
                this._isStaffRound = this._candidates.length > 0 && this._candidates.every(c => c.is_staff === true);
                this._populateLevelFilter();
                this._populateSubjectCatFilter(result.subject_cats || []);
                this._applySearch();
                this._renderTable();
            }).catch(() => {
                document.getElementById('av-candidate-list').innerHTML =
                    '<tr><td colspan="7" class="av-no-results">Failed to load candidates. Please try again.</td></tr>';
            });
        },

        _populateLevelFilter() {
            if (this._isStaffRound) {
                // For staff rounds show department filter instead of level
                const levels = [...new Set(this._candidates.map(c => c.department).filter(Boolean))].sort();
                const sel = document.getElementById('av-filter-level');
                const saved = localStorage.getItem('av_filter_level') || '';
                sel.innerHTML = '<option value="">All Departments</option>' +
                    levels.map(l => `<option value="${l}"${l === saved ? ' selected' : ''}>${l}</option>`).join('');
                // Update column header
                const levelTh = document.querySelector('.av-th-level');
                if (levelTh) levelTh.textContent = 'Department';
            } else {
                const levels = [...new Set(this._candidates.map(c => c.level).filter(Boolean))].sort();
                const sel = document.getElementById('av-filter-level');
                const saved = localStorage.getItem('av_filter_level') || '';
                sel.innerHTML = '<option value="">All Year Levels</option>' +
                    levels.map(l => `<option value="${l}"${l === saved ? ' selected' : ''}>${l}</option>`).join('');
                const levelTh = document.querySelector('.av-th-level');
                if (levelTh) levelTh.textContent = 'Level';
            }
        },

        // ----------------------------------------------------------------
        // Search filter
        // ----------------------------------------------------------------
        filterSearch() {
            localStorage.setItem('av_filter_level',
                document.getElementById('av-filter-level').value);
            localStorage.setItem('av_filter_subject_cat',
                document.getElementById('av-filter-subject-cat').value);
            this._applySearch();
            this._renderTable();
        },

        _applySearch() {
            const q = (document.getElementById('av-search').value || '').toLowerCase();
            const levelOrDept = document.getElementById('av-filter-level').value;
            const subCatId = parseInt(document.getElementById('av-filter-subject-cat').value || '0', 10);

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
                return nameMatch && levelMatch && subCatMatch;
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
            if (!this._filtered.length) {
                tbody.innerHTML = `<tr><td colspan="7" class="av-no-results">No ${this._isStaffRound ? 'staff' : 'students'} found.</td></tr>`;
                return;
            }

            const atLimit = this._voteLimit > 0 && this._selected.size >= this._voteLimit;

            const rows = [];
            for (const c of this._filtered) {
                const sel = this._selected.has(c.id);
                const photo = c.image
                    ? `<img src="data:image/png;base64,${c.image}" alt="${this._esc(c.name)}">`
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
                    <td class="av-td-level">${levelOrDept}</td>
                    <td class="av-td-times">${c.times_awarded}</td>
                    <td class="av-td-last">${lastDate}</td>
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
                submitBtn.textContent = count === 1
                    ? `Submit Vote for ${names}`
                    : `Submit ${count} Votes`;
                submitBtn.style.display = 'inline-block';
            } else {
                summary.style.display = 'none';
                submitBtn.style.display = 'none';
            }
        },

        // ----------------------------------------------------------------
        // Submit
        // ----------------------------------------------------------------
        submitVote() {
            if (!this._selected.size) return;

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
            btn.textContent = 'Submitting…';

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
        // Delete / revert history vote
        // ----------------------------------------------------------------
        deleteVote(btn) {
            const voteId = parseInt(btn.dataset.voteId, 10);
            const token = btn.dataset.token;
            const hasDue = btn.dataset.hasDue === '1';
            const msg = hasDue
                ? 'Undo this vote? It will be reverted to Open so you can re-submit.'
                : 'Permanently delete this vote?';
            if (!confirm(msg)) return;

            btn.disabled = true;
            btn.textContent = '…';

            this._jsonRpc(`/awards/vote/${token}/vote/${voteId}/delete`, {}).then(result => {
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
