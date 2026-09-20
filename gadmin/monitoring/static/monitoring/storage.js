(() => {
    'use strict';
    const root = document.getElementById('storage-monitor');
    if (!root) return;
    const button = document.getElementById('storage-refresh');
    const panels = document.getElementById('storage-panels');
    const feedback = document.getElementById('storage-feedback');
    const error = document.getElementById('storage-request-error');
    const login = document.getElementById('storage-login');
    let pending = false;
    let expired = false;

    async function refresh() {
        if (pending || expired) return;
        const hadFocus = document.activeElement === button;
        pending = true;
        button.disabled = true;
        button.textContent = '불러오는 중…';
        panels.setAttribute('aria-busy', 'true');
        error.hidden = true;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch(root.dataset.refreshUrl, {
                credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
                headers: {Accept: 'application/json'},
            });
            if (response.redirected || response.status === 401 || response.status === 403) {
                expired = true;
                login.hidden = false;
                throw new Error('로그인이 만료되었거나 접근 권한이 없습니다. 다시 로그인해 주세요.');
            }
            if (!response.ok) throw new Error('측정 결과를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.');
            const data = await response.json();
            if (typeof data.html !== 'string' || typeof data.refreshed_at !== 'string') throw new Error('측정 결과 형식이 올바르지 않습니다.');
            panels.innerHTML = data.html;
            feedback.textContent = `화면 갱신: ${data.refreshed_at} KST · 최신 수집 결과를 불러왔습니다.`;
        } catch (failure) {
            error.textContent = failure.name === 'AbortError' ? '응답 시간이 초과됐습니다. 마지막 화면을 유지합니다.' :
                (failure instanceof TypeError ? '연결에 실패했습니다. 네트워크를 확인하고 새로고침해 주세요.' : failure.message);
            error.hidden = false;
        } finally {
            clearTimeout(timeout);
            pending = false;
            button.disabled = expired;
            button.textContent = '새로고침';
            panels.removeAttribute('aria-busy');
            if (hadFocus && document.activeElement === document.body) {
                (expired ? login.querySelector('a') : button).focus({preventScroll: true});
            }
        }
    }
    button.form.addEventListener('submit', event => { event.preventDefault(); refresh(); });
    setInterval(() => { if (!document.hidden) refresh(); }, 60000);
})();
