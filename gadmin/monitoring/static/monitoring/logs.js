(() => {
    'use strict';
    const root = document.getElementById('log-viewer');
    if (!root) return;
    const form = document.getElementById('log-filters');
    const button = document.getElementById('log-refresh');
    const results = document.getElementById('log-results');
    const feedback = document.getElementById('log-feedback');
    const error = document.getElementById('log-request-error');
    const login = document.getElementById('log-login');
    const automatic = document.getElementById('log-auto');
    const paused = document.getElementById('log-auto-state');
    const parameters = () => new URLSearchParams(new FormData(form)).toString();
    let applied = parameters();
    let cursor = results.querySelector('.log-panel').dataset.nextCursor;
    let pagesRead = 1;
    let pending = false;
    let expired = false;
    let failedMore = false;
    let serial = 0;
    let controller;
    let observer;

    function bindResults() {
        observer?.disconnect();
        const more = results.querySelector('#log-more');
        more.addEventListener('click', () => fetchPage({append: true}));
        const content = results.querySelector('.log-content');
        content.addEventListener('scroll', () => {
            paused.hidden = pagesRead === 1 && content.scrollTop < 10;
        }, {passive: true});
        if ('IntersectionObserver' in window && cursor) {
            observer = new IntersectionObserver(entries => {
                if (entries.some(entry => entry.isIntersecting) && !failedMore && applied === parameters()) {
                    fetchPage({append: true});
                }
            }, {root: content, rootMargin: '0px 0px 100px 0px'});
            observer.observe(more);
        }
    }

    async function fetchPage({append = false, auto = false} = {}) {
        if (expired || (append && (pending || !cursor))) return;
        if (append && applied !== parameters()) return;
        const content = results.querySelector('.log-content');
        if (auto && (pending || applied !== parameters() || pagesRead > 1 || content.scrollTop > 10 ||
            results.contains(document.activeElement) || window.getSelection()?.toString())) return;
        const nextParameters = append || auto ? applied : parameters();
        const active = document.activeElement;
        const restoreFocus = active === button || active === results.querySelector('#log-more');
        controller?.abort();
        controller = new AbortController();
        const ownController = controller;
        const request = ++serial;
        pending = true;
        button.disabled = !append;
        button.textContent = append ? '조회' : '불러오는 중…';
        const more = results.querySelector('#log-more');
        more.disabled = true;
        if (append) more.textContent = '이전 로그 불러오는 중…';
        results.setAttribute('aria-busy', 'true');
        error.hidden = true;
        results.querySelector('#log-more-error').hidden = true;
        const timeout = setTimeout(() => ownController.abort(), 10000);
        const query = new URLSearchParams(nextParameters);
        if (append) query.set('cursor', cursor);
        try {
            const response = await fetch(`${root.dataset.refreshUrl}?${query}`, {
                credentials: 'same-origin', cache: 'no-store', signal: ownController.signal,
                headers: {Accept: 'application/json'},
            });
            if (request !== serial) return;
            if (response.redirected || response.status === 401 || response.status === 403) {
                expired = true;
                login.hidden = false;
                throw new Error('로그인이 만료되었거나 권한이 없습니다. 다시 로그인해 주세요.');
            }
            const data = await response.json();
            if (request !== serial) return;
            if (!response.ok) {
                if (data.error_field === 'start' || data.error_field === 'end') {
                    const field = form.elements.namedItem(data.error_field);
                    field.setAttribute('aria-invalid', 'true');
                    field.focus();
                }
                throw new Error(data.message || '로그를 조회하지 못했습니다. 다시 시도해 주세요.');
            }
            if (typeof data.next_cursor !== 'string' || typeof data.html !== 'string' || typeof data.page_html !== 'string') {
                throw new Error('로그 응답 형식이 올바르지 않습니다.');
            }
            cursor = data.next_cursor;
            failedMore = false;
            if (append) {
                const container = results.querySelector('#log-pages');
                container.insertAdjacentHTML('beforeend', data.page_html);
                pagesRead += 1;
                // Bound DOM memory while preserving the visible position at the bottom.
                if (container.children.length > 5) {
                    const oldestPage = container.firstElementChild;
                    const height = oldestPage.getBoundingClientRect().height;
                    const top = content.scrollTop;
                    oldestPage.remove();
                    content.scrollTop = Math.max(0, top - height);
                }
                const shown = container.querySelectorAll('.log-line').length;
                results.querySelector('#log-count').textContent = `${shown.toLocaleString('ko-KR')}줄 표시 · 누적 ${data.displayed_count.toLocaleString('ko-KR')}줄 조회`;
                more.hidden = !cursor;
                results.querySelector('#log-more-status').textContent = cursor ? `${data.count}줄을 더 불러왔습니다.` : '선택한 조건의 마지막 로그입니다.';
                paused.hidden = false;
                if (!cursor) observer?.disconnect();
            } else {
                observer?.disconnect();
                results.innerHTML = data.html;
                applied = nextParameters;
                pagesRead = 1;
                paused.hidden = true;
                history.replaceState(null, '', `${location.pathname}?${applied}`);
                bindResults();
            }
            feedback.textContent = `화면 갱신: ${data.refreshed_at} KST`;
        } catch (failure) {
            if (request !== serial) return;
            failedMore = append;
            const target = append ? results.querySelector('#log-more-error') : error;
            target.textContent = failure.name === 'AbortError' ? '응답 시간이 초과됐습니다. 현재 로그를 유지합니다. 다시 시도해 주세요.' :
                (failure instanceof TypeError ? '연결에 실패했습니다. 현재 로그를 유지합니다. 다시 시도해 주세요.' : failure.message);
            target.hidden = false;
        } finally {
            clearTimeout(timeout);
            if (request === serial) {
                pending = false;
                button.disabled = expired;
                button.textContent = '조회';
                const currentMore = results.querySelector('#log-more');
                currentMore.disabled = expired;
                currentMore.textContent = failedMore ? '이전 로그 다시 불러오기' : '이전 로그 더 보기';
                results.removeAttribute('aria-busy');
                if (restoreFocus && document.activeElement === document.body) {
                    (expired ? login.querySelector('a') : (append && !currentMore.hidden ? currentMore : button)).focus({preventScroll: true});
                }
            }
        }
    }
    form.addEventListener('submit', event => { event.preventDefault(); fetchPage(); });
    form.addEventListener('input', event => {
        event.target.removeAttribute('aria-invalid');
        if (pending) {
            serial += 1;
            controller?.abort();
            pending = false;
            button.disabled = expired;
            button.textContent = '조회';
            results.removeAttribute('aria-busy');
        }
        const more = results.querySelector('#log-more');
        more.disabled = applied !== parameters();
        more.textContent = '이전 로그 더 보기';
        feedback.textContent = '조건을 변경했습니다. 조회를 눌러 적용해 주세요.';
    });
    bindResults();
    setInterval(() => { if (automatic.checked && !document.hidden) fetchPage({auto: true}); }, 60000);
})();
