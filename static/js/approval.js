(() => {
    const loginSection = document.getElementById('loginSection');
    const managerSection = document.getElementById('managerSection');
    const managerInfo = document.getElementById('managerInfo');
    const pendingCount = document.getElementById('pendingCount');
    const lastUpdate = document.getElementById('lastUpdate');
    const requestsBody = document.getElementById('requestsBody');
    const requestsContainer = document.getElementById('requestsContainer');
    const requestsEmpty = document.getElementById('requestsEmpty');
    const loadingOverlay = document.getElementById('loadingOverlay');

    const userIdInput = document.getElementById('userIdInput');
    const passwordInput = document.getElementById('passwordInput');

    const loginBtn = document.getElementById('loginBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const logoutBtn = document.getElementById('logoutBtn');

    let authToken = null;
    let managerMeta = null;

    async function api(url, options = {}) {
        const headers = {
            'Content-Type': 'application/json',
            ...(options.headers || {})
        };

        if (authToken) {
            headers.Authorization = `Bearer ${authToken}`;
        }

        const response = await fetch(url, {
            ...options,
            headers
        });

        const result = await response.json();
        if (!response.ok || !result.success) {
            throw new Error(result.error || 'Errore richiesta');
        }
        return result;
    }

    function escapeHtml(value) {
        // Escape dei dati dal server prima dell'interpolazione in innerHTML (stored XSS)
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setLoading(isLoading) {
        loadingOverlay.style.display = isLoading ? 'flex' : 'none';
    }

    function showToast(message, isError = false) {
        const toastContainer = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast ${isError ? 'toast-error' : 'toast-success'}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);

        setTimeout(() => toast.classList.add('toast-show'), 20);
        setTimeout(() => {
            toast.classList.remove('toast-show');
            setTimeout(() => toast.remove(), 200);
        }, 2600);
    }

    function formatDate(value) {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleDateString('it-IT');
    }

    function formatDateTime(value) {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString('it-IT');
    }

    function setLastUpdateNow() {
        const now = new Date();
        lastUpdate.textContent = `Ultimo aggiornamento: ${now.toLocaleString('it-IT')}`;
    }

    function formatTimeRange(fromTime, toTime) {
        if (!fromTime || !toTime) return '-';
        return `${fromTime} - ${toTime}`;
    }

    function setManagerView(visible) {
        loginSection.style.display = visible ? 'none' : 'block';
        managerSection.style.display = visible ? 'block' : 'none';
    }

    function renderRequests(items) {
        requestsBody.innerHTML = '';

        if (!items.length) {
            requestsContainer.style.display = 'none';
            requestsEmpty.style.display = 'block';
            return;
        }

        requestsContainer.style.display = 'block';
        requestsEmpty.style.display = 'none';

        items.forEach((item) => {
            const tr = document.createElement('tr');
            const canTakeAction = item.can_take_action;
            const statusClass = String(item.status || 'pending').replace(/[^a-z0-9_-]/gi, '');

            tr.innerHTML = `
                <td>${escapeHtml(item.absence_request_id)}</td>
                <td>${escapeHtml(item.request_number || '-')}</td>
                <td>${escapeHtml(item.employee || '-')}</td>
                <td>${escapeHtml(item.request_type || '-')}</td>
                <td>${formatDate(item.date_start)} - ${formatDate(item.date_end)}</td>
                <td>${formatTimeRange(item.from_time, item.to_time)}</td>
                <td>${formatDateTime(item.date_sys)}</td>
                <td>
                    <div class="status-pill status-${statusClass}">${escapeHtml(item.status_text || 'În așteptare')}</div>
                </td>
                <td>
                    ${canTakeAction ? `
                        <div class="decision-controls" data-request-id="${escapeHtml(item.absence_request_id)}">
                            <label class="decision-option">
                                <input type="checkbox" class="decision-checkbox decision-accept" data-role="accept">
                                <span>Accetta</span>
                            </label>
                            <label class="decision-option">
                                <input type="checkbox" class="decision-checkbox decision-reject" data-role="reject">
                                <span>Rifiuta</span>
                            </label>
                            <input type="text" class="reject-motive" placeholder="Motivo rifiuto" style="display:none;">
                            <button class="btn-save-decision">Salva</button>
                        </div>
                    ` : `
                        <div class="read-only-note">Nessuna azione disponibile</div>
                    `}
                </td>
            `;

            requestsBody.appendChild(tr);
        });
    }

    async function loadRequests() {
        if (!authToken) {
            setManagerView(false);
            return;
        }

        setLoading(true);
        try {
            const result = await api('/api/manager/pending-requests');
            renderRequests(result.requests || []);
            pendingCount.textContent = `Richieste pending: ${result.total || 0}`;
            setLastUpdateNow();
        } catch (error) {
            showToast(error.message, true);
        } finally {
            setLoading(false);
        }
    }

    async function doLogin() {
        const userId = userIdInput.value.trim();
        const password = passwordInput.value.trim();

        if (!userId || !password) {
            showToast('Compila UserId e Password', true);
            return;
        }

        setLoading(true);
        try {
            const result = await api('/api/manager/login', {
                method: 'POST',
                headers: {},
                body: JSON.stringify({ userId, password })
            });

            authToken = result.token;
            managerMeta = result.manager;
            passwordInput.value = '';
            setManagerView(true);
            managerInfo.textContent = `${managerMeta.name} | FunctionCode: ${managerMeta.function_code || '-'} | MainCDC: ${managerMeta.main_cdc_id || '-'} ${managerMeta.main_cdc_description ? '- ' + managerMeta.main_cdc_description : ''}`;
            showToast('Login eseguito con successo');
            await loadRequests();
        } catch (error) {
            authToken = null;
            managerMeta = null;
            setManagerView(false);
            showToast(error.message, true);
        } finally {
            setLoading(false);
        }
    }

    async function doLogout() {
        if (!authToken) {
            setManagerView(false);
            return;
        }

        setLoading(true);
        try {
            await api('/api/manager/logout', { method: 'POST' });
            showToast('Logout effettuato');
        } catch (error) {
            showToast(error.message, true);
        } finally {
            authToken = null;
            managerMeta = null;
            setManagerView(false);
            requestsBody.innerHTML = '';
            pendingCount.textContent = 'Richieste pending: 0';
            lastUpdate.textContent = 'Ultimo aggiornamento: -';
            setLoading(false);
        }
    }

    async function processDecision(requestId, decision, motive = '') {
        if (decision === 'reject' && !motive.trim()) {
            showToast('Motivo rifiuto obbligatorio', true);
            return;
        }

        setLoading(true);
        try {
            await api('/api/manager/decision', {
                method: 'POST',
                body: JSON.stringify({
                    absenceRequestId: Number(requestId),
                    decision,
                    refuseMotive: motive.trim()
                })
            });

            showToast(decision === 'approve' ? 'Richiesta approvata' : 'Richiesta rifiutata');
            await loadRequests();
        } catch (error) {
            showToast(error.message, true);
        } finally {
            setLoading(false);
        }
    }

    loginBtn.addEventListener('click', doLogin);
    refreshBtn.addEventListener('click', loadRequests);
    logoutBtn.addEventListener('click', doLogout);

    requestsBody.addEventListener('click', async (event) => {
        const saveButton = event.target.closest('.btn-save-decision');
        if (!saveButton) return;

        const container = event.target.closest('.decision-controls');
        if (!container) return;

        const requestId = container.getAttribute('data-request-id');
        const acceptBox = container.querySelector('.decision-accept');
        const rejectBox = container.querySelector('.decision-reject');
        const motiveInput = container.querySelector('.reject-motive');

        const isAccept = acceptBox.checked;
        const isReject = rejectBox.checked;

        if (!isAccept && !isReject) {
            showToast('Seleziona Accetta o Rifiuta', true);
            return;
        }

        if (isAccept && isReject) {
            showToast('Seleziona una sola opzione', true);
            return;
        }

        if (isReject) {
            await processDecision(requestId, 'reject', motiveInput.value || '');
        } else {
            await processDecision(requestId, 'approve');
        }
    });

    requestsBody.addEventListener('change', (event) => {
        const input = event.target.closest('.decision-checkbox');
        if (!input) return;

        const container = input.closest('.decision-controls');
        if (!container) return;

        const acceptBox = container.querySelector('.decision-accept');
        const rejectBox = container.querySelector('.decision-reject');
        const motiveInput = container.querySelector('.reject-motive');

        if (input.dataset.role === 'accept' && input.checked) {
            rejectBox.checked = false;
            motiveInput.style.display = 'none';
            motiveInput.value = '';
        }

        if (input.dataset.role === 'reject' && input.checked) {
            acceptBox.checked = false;
            motiveInput.style.display = 'block';
        }

        if (!rejectBox.checked) {
            motiveInput.style.display = 'none';
            motiveInput.value = '';
        }
    });

    [userIdInput, passwordInput].forEach((input) => {
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                doLogin();
            }
        });
    });

    setManagerView(false);
})();
