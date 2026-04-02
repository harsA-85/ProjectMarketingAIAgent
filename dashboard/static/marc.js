/**
 * Marc Andreessen — Cofounder AI chat overlay
 * Drop <script src="/static/marc.js"></script> on any page.
 */
(function () {
    'use strict';

    // ── CSS ───────────────────────────────────────────────────────────────────
    const CSS = `
    .marc-prompt-bar {
        position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
        z-index: 8000; width: min(600px, calc(100vw - 260px));
        background: rgba(20,20,22,0.95); backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(255,149,0,0.25);
        border-radius: 14px; padding: 11px 14px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,149,0,0.08);
        display: flex; flex-direction: column; gap: 7px;
        transition: left 0.25s ease, transform 0.25s ease, width 0.25s ease;
    }
    .marc-panel-open .marc-prompt-bar {
        left: calc(50% - 190px);
        transform: translateX(-50%);
    }
    .marc-prompt-top { display: flex; align-items: center; gap: 10px; }
    .marc-prompt-avatar {
        width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
        background: linear-gradient(135deg, #ff9500, #ff6b00);
        display: flex; align-items: center; justify-content: center; font-size: 12px;
    }
    .marc-prompt-input {
        flex: 1; background: none; border: none; outline: none;
        font-size: 13px; color: #fff; font-family: inherit;
    }
    .marc-prompt-input::placeholder { color: rgba(255,255,255,0.35); }
    .marc-prompt-send {
        width: 28px; height: 28px; border-radius: 7px; border: none; flex-shrink: 0;
        background: rgba(255,149,0,0.2); color: #ff9500; cursor: pointer;
        font-size: 13px; display: flex; align-items: center; justify-content: center;
        transition: background 0.15s;
    }
    .marc-prompt-send:hover { background: rgba(255,149,0,0.35); }
    .marc-prompt-send:disabled { opacity: 0.38; cursor: default; }
    .marc-prompt-actions { display: flex; align-items: center; gap: 10px; padding-left: 34px; flex-wrap: wrap; }
    .marc-action-btn {
        font-size: 10px; font-weight: 600; color: rgba(255,255,255,0.42);
        background: none; border: none; cursor: pointer; padding: 0;
        transition: color 0.15s; display: flex; align-items: center; gap: 4px;
    }
    .marc-action-btn:hover { color: rgba(255,255,255,0.82); }

    /* Task dispatch badge */
    .marc-dispatch-badge {
        display: flex; align-items: center; gap: 8px; padding: 6px 10px;
        background: rgba(52,199,89,0.1); border: 1px solid rgba(52,199,89,0.25);
        border-radius: 8px; font-size: 11px; color: rgba(255,255,255,0.8);
        animation: marc-fade-in 0.3s ease;
    }
    .marc-dispatch-badge strong { color: #34c759; }
    .marc-dispatch-badge a { color: #ff9500; text-decoration: none; font-weight: 700; }
    .marc-dispatch-badge a:hover { text-decoration: underline; }
    .marc-dispatch-approve-all {
        margin-left: auto; font-size: 10px; font-weight: 700;
        padding: 3px 8px; border-radius: 6px; border: none; cursor: pointer;
        background: rgba(52,199,89,0.2); color: #34c759; transition: background 0.15s;
    }
    .marc-dispatch-approve-all:hover { background: rgba(52,199,89,0.35); }
    .marc-dispatch-email {
        font-size: 10px; font-weight: 700;
        padding: 3px 8px; border-radius: 6px; border: none; cursor: pointer;
        background: rgba(255,149,0,0.15); color: #ff9500; transition: background 0.15s;
    }
    .marc-dispatch-email:hover { background: rgba(255,149,0,0.3); }

    @keyframes marc-fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

    /* Side panel */
    .marc-side-panel {
        position: fixed; top: 0; right: 0; bottom: 0; z-index: 7999;
        width: 390px;
        background: #f7f7f8; border-left: 1px solid rgba(0,0,0,0.09);
        display: flex; flex-direction: column; overflow: hidden;
        transform: translateX(100%);
        transition: transform 0.25s cubic-bezier(0.4,0,0.2,1);
        box-shadow: -6px 0 28px rgba(0,0,0,0.1);
    }
    .marc-side-panel.open { transform: translateX(0); }
    .marc-panel-header {
        display: flex; align-items: center; gap: 10px;
        padding: 13px 16px; border-bottom: 1px solid rgba(0,0,0,0.07);
        background: #fff; flex-shrink: 0;
    }
    .marc-panel-avatar {
        width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
        background: linear-gradient(135deg, #ff9500, #ff6b00);
        display: flex; align-items: center; justify-content: center; font-size: 16px;
    }
    .marc-panel-info { flex: 1; min-width: 0; }
    .marc-panel-name { font-size: 13px; font-weight: 700; color: #1c1c1e; }
    .marc-panel-role { font-size: 10px; color: #aeaeb2; }
    .marc-panel-plan-btn {
        font-size: 10px; font-weight: 700; padding: 4px 10px; border-radius: 100px;
        border: 1px solid #ff9f0a; background: rgba(255,159,10,0.07);
        color: #ff9f0a; cursor: pointer; white-space: nowrap; margin-right: 4px;
        transition: background 0.15s;
    }
    .marc-panel-plan-btn:hover { background: rgba(255,159,10,0.18); }
    .marc-panel-close {
        background: none; border: none; cursor: pointer; font-size: 16px;
        color: #aeaeb2; padding: 4px; line-height: 1; transition: color 0.15s;
    }
    .marc-panel-close:hover { color: #1c1c1e; }

    /* Pending tasks strip inside panel */
    .marc-pending-strip {
        background: #fff; border-bottom: 1px solid #f0f0f2;
        padding: 10px 14px; flex-shrink: 0; display: none;
    }
    .marc-pending-strip-title {
        font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
        color: #ff9500; margin-bottom: 7px;
    }
    .marc-pending-task-row {
        display: flex; align-items: center; gap: 8px;
        padding: 5px 0; border-bottom: 1px solid #f5f5f7; font-size: 12px; color: #3c3c43;
    }
    .marc-pending-task-row:last-child { border-bottom: none; }
    .marc-pending-task-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .marc-pending-task-pri {
        font-size: 9px; font-weight: 700; text-transform: uppercase; padding: 2px 5px;
        border-radius: 4px; flex-shrink: 0;
    }
    .marc-pending-task-pri.high { background: rgba(255,59,48,0.1); color: #ff3b30; }
    .marc-pending-task-pri.medium { background: rgba(255,149,0,0.1); color: #ff9500; }
    .marc-pending-task-pri.low { background: rgba(52,199,89,0.1); color: #34c759; }
    .marc-approve-btn {
        font-size: 10px; padding: 2px 7px; border-radius: 5px; border: none;
        background: rgba(52,199,89,0.12); color: #34c759; cursor: pointer; font-weight: 600;
        flex-shrink: 0; transition: background 0.15s;
    }
    .marc-approve-btn:hover { background: rgba(52,199,89,0.25); }
    .marc-pending-footer {
        display: flex; gap: 6px; margin-top: 7px; padding-top: 6px; border-top: 1px solid #f0f0f2;
    }
    .marc-pending-footer-btn {
        flex: 1; font-size: 10px; font-weight: 700; padding: 5px 8px; border-radius: 7px;
        border: none; cursor: pointer; text-align: center; transition: background 0.15s;
    }
    .marc-footer-approve { background: rgba(52,199,89,0.12); color: #34c759; }
    .marc-footer-approve:hover { background: rgba(52,199,89,0.25); }
    .marc-footer-inbox { background: rgba(0,122,255,0.07); color: #007aff; }
    .marc-footer-inbox:hover { background: rgba(0,122,255,0.15); }

    .marc-panel-messages {
        flex: 1; overflow-y: auto; padding: 14px 16px;
        display: flex; flex-direction: column; gap: 10px;
        background: #f7f7f8;
    }
    .marc-msg {
        max-width: 88%; padding: 9px 13px; border-radius: 12px;
        font-size: 13px; line-height: 1.5; word-wrap: break-word;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    }
    .marc-msg.user { align-self: flex-end; background: #007aff; color: #fff; border-bottom-right-radius: 3px; }
    .marc-msg.ai { align-self: flex-start; background: #fff; color: #1c1c1e; border-bottom-left-radius: 3px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.07); }
    .marc-msg-label { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #aeaeb2; margin-bottom: 4px; }
    /* Task dispatch card inside a message */
    .marc-task-card {
        margin-top: 8px; padding: 8px 10px; border-radius: 8px;
        background: rgba(52,199,89,0.06); border: 1px solid rgba(52,199,89,0.2);
        font-size: 11px;
    }
    .marc-task-card-title { font-weight: 700; color: #1c1c1e; font-size: 12px; }
    .marc-task-card-meta { color: #636366; margin-top: 2px; }
    .marc-typing { align-self: flex-start; background: #fff; border-radius: 12px; border-bottom-left-radius: 3px; padding: 10px 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.07); }
    .marc-typing span { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #c7c7cc; margin: 0 1px; animation: marc-blink 1.2s infinite; }
    .marc-typing span:nth-child(2) { animation-delay: 0.2s; }
    .marc-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes marc-blink { 0%,80%,100% { opacity: 0.2; } 40% { opacity: 1; } }
    .marc-msg p { margin: 0 0 6px; } .marc-msg p:last-child { margin: 0; }
    .marc-msg ul { margin: 4px 0 4px 16px; padding: 0; }
    .marc-msg li { margin-bottom: 2px; }
    .marc-msg strong { font-weight: 700; }
    .marc-msg em { font-style: italic; }
    .marc-msg a { color: #007aff; }

    /* Minimized state */
    .marc-prompt-bar.marc-hidden { display: none !important; }
    .marc-side-panel.marc-hidden { display: none !important; }
    .marc-mini-fab {
        position: fixed; bottom: 22px; right: 22px; z-index: 8000;
        width: 44px; height: 44px; border-radius: 50%;
        background: linear-gradient(135deg, #ff9500, #ff6b00);
        border: none; cursor: pointer;
        display: none; align-items: center; justify-content: center;
        font-size: 20px; color: #fff;
        box-shadow: 0 4px 16px rgba(255,149,0,0.4), 0 2px 6px rgba(0,0,0,0.15);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .marc-mini-fab:hover { transform: scale(1.1); box-shadow: 0 6px 24px rgba(255,149,0,0.5); }
    .marc-mini-fab.visible { display: flex; }
    .marc-mini-tooltip {
        position: absolute; bottom: 52px; right: 0; white-space: nowrap;
        background: rgba(20,20,22,0.92); color: #fff; font-size: 11px; font-weight: 600;
        padding: 5px 10px; border-radius: 7px; pointer-events: none;
        opacity: 0; transition: opacity 0.2s;
    }
    .marc-mini-fab:hover .marc-mini-tooltip { opacity: 1; }
    `;

    // ── HTML ──────────────────────────────────────────────────────────────────
    const HTML = `
    <div class="marc-side-panel" id="marc-side-panel">
        <div class="marc-panel-header">
            <div class="marc-panel-avatar">🚀</div>
            <div class="marc-panel-info">
                <div class="marc-panel-name">Marc Andreessen</div>
                <div class="marc-panel-role">Cofounder &amp; Chief Strategist</div>
            </div>
            <button class="marc-panel-plan-btn" onclick="marcProposePlan()">📋 Dispatch Plan</button>
            <button class="marc-panel-close" onclick="marcToggle()">✕</button>
        </div>
        <div class="marc-pending-strip" id="marc-pending-strip">
            <div class="marc-pending-strip-title">⏳ Awaiting Your Approval</div>
            <div id="marc-pending-list"></div>
            <div class="marc-pending-footer">
                <button class="marc-pending-footer-btn marc-footer-approve" onclick="marcApproveAll()">✓ Approve All</button>
                <button class="marc-pending-footer-btn marc-footer-inbox" onclick="window.location='/inbox'">📥 Review in Inbox</button>
            </div>
        </div>
        <div class="marc-panel-messages" id="marc-messages"></div>
    </div>

    <div class="marc-prompt-bar" id="marc-prompt-bar">
        <div class="marc-prompt-top">
            <div class="marc-prompt-avatar">🚀</div>
            <input class="marc-prompt-input" id="marc-input" placeholder="Ask Marc Andreessen..." autocomplete="off" />
            <button class="marc-prompt-send" id="marc-send-btn" onclick="marcSend()">↑</button>
        </div>
        <div class="marc-prompt-actions" id="marc-actions-bar">
            <button class="marc-action-btn" onclick="marcProposePlan()">📋 Dispatch Plan</button>
            <span style="color:rgba(255,255,255,0.15)">·</span>
            <button class="marc-action-btn" onclick="marcToggle()">⇄ Panel</button>
            <span style="color:rgba(255,255,255,0.15)">·</span>
            <button class="marc-action-btn" onclick="window.location='/inbox'">📥 Inbox</button>
            <span style="color:rgba(255,255,255,0.15)">·</span>
            <button class="marc-action-btn" onclick="marcMinimize()">▼ Hide</button>
        </div>
    </div>
    <button class="marc-mini-fab" id="marc-mini-fab" onclick="marcRestore()">
        🚀
        <div class="marc-mini-tooltip">Bring back Marc</div>
    </button>`;

    // ── Inject ────────────────────────────────────────────────────────────────
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const wrap = document.createElement('div');
    wrap.innerHTML = HTML;
    document.body.appendChild(wrap);

    // ── State ─────────────────────────────────────────────────────────────────
    let _marcOpen = false;
    let _marcMinimized = false;

    function marcToggle() {
        if (_marcMinimized) { marcRestore(); return; }
        _marcOpen = !_marcOpen;
        document.getElementById('marc-side-panel').classList.toggle('open', _marcOpen);
        document.body.classList.toggle('marc-panel-open', _marcOpen);
        if (_marcOpen) {
            document.getElementById('marc-input').focus();
            marcLoadPending();
        }
    }

    function marcMinimize() {
        _marcMinimized = true;
        // Close panel if open
        _marcOpen = false;
        document.getElementById('marc-side-panel').classList.remove('open');
        document.getElementById('marc-side-panel').classList.add('marc-hidden');
        document.body.classList.remove('marc-panel-open');
        // Hide prompt bar
        document.getElementById('marc-prompt-bar').classList.add('marc-hidden');
        // Show FAB
        document.getElementById('marc-mini-fab').classList.add('visible');
    }

    function marcRestore() {
        _marcMinimized = false;
        document.getElementById('marc-side-panel').classList.remove('marc-hidden');
        document.getElementById('marc-prompt-bar').classList.remove('marc-hidden');
        document.getElementById('marc-mini-fab').classList.remove('visible');
        document.getElementById('marc-input').focus();
    }

    // ── Format AI markdown ────────────────────────────────────────────────────
    function _marcFmt(raw) {
        if (!raw) return '';
        let s = raw
            .replace(/```[\s\S]*?```/g, '')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/^\s*[-•]\s+(.+)$/gm, '<li>$1</li>')
            .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
            .replace(/\n{2,}/g, '</p><p>')
            .replace(/\n/g, '<br>');
        return '<p>' + s + '</p>';
    }

    function marcAppend(role, text, tasksCreated) {
        const msgs = document.getElementById('marc-messages');
        const div = document.createElement('div');
        div.className = 'marc-msg ' + role;
        if (role === 'ai') {
            let html = '<div class="marc-msg-label">Marc Andreessen</div>' + _marcFmt(text);
            // If tasks were created, show them as cards in the message
            if (tasksCreated && tasksCreated.length > 0) {
                html += `<div style="margin-top:10px;font-size:11px;font-weight:700;color:#34c759;margin-bottom:5px">
                    ✅ ${tasksCreated.length} task${tasksCreated.length > 1 ? 's' : ''} dispatched — awaiting your approval:
                </div>`;
                tasksCreated.forEach(t => {
                    const pri = (t.priority || 'medium').toLowerCase();
                    const priColor = pri==='high'?'#ff3b30':pri==='medium'?'#ff9500':'#34c759';
                    html += `<div class="marc-task-card">
                        <div style="display:flex;align-items:center;gap:6px">
                            <span style="font-size:9px;font-weight:800;color:${priColor};text-transform:uppercase;border:1px solid ${priColor};border-radius:3px;padding:1px 4px">${pri}</span>
                            <div class="marc-task-card-title">${t.title}</div>
                        </div>
                        <div class="marc-task-card-meta" style="margin-top:3px">→ ${t.assignee || 'Team'}</div>
                    </div>`;
                });
                html += `<div style="margin-top:8px;display:flex;gap:6px">
                    <button onclick="marcApproveAll()" style="font-size:10px;font-weight:700;padding:4px 10px;border-radius:7px;border:none;cursor:pointer;background:rgba(52,199,89,0.12);color:#34c759;transition:background 0.15s">✓ Approve All</button>
                    <button onclick="marcSendApprovalEmail()" style="font-size:10px;font-weight:700;padding:4px 10px;border-radius:7px;border:none;cursor:pointer;background:rgba(255,149,0,0.12);color:#ff9500;transition:background 0.15s">📬 Send to Email</button>
                    <a href="/inbox" style="font-size:10px;font-weight:700;padding:4px 10px;border-radius:7px;background:rgba(0,122,255,0.07);color:#007aff;text-decoration:none">📥 Review</a>
                </div>`;
            }
            div.innerHTML = html;
        } else {
            div.textContent = text;
        }
        msgs.appendChild(div);
        msgs.scrollTop = msgs.scrollHeight;
    }

    async function marcSend() {
        const input = document.getElementById('marc-input');
        const msg = input.value.trim();
        if (!msg) return;
        input.value = '';

        // Check if user wants to hide Marc
        const hidePatterns = /\b(hide|minimize|go away|close|shut up|dismiss|later|bye|disappear|get out|leave me|step back)\b/i;
        if (hidePatterns.test(msg)) {
            marcAppend('user', msg);
            marcAppend('ai', "Got it — I'll step back. Click the 🚀 button anytime you need me.\n\n*\"The best cofounders know when to give you space.\"*");
            setTimeout(marcMinimize, 1500);
            return;
        }

        if (!_marcOpen) marcToggle();
        marcAppend('user', msg);

        const btn = document.getElementById('marc-send-btn');
        btn.disabled = true;

        const msgs = document.getElementById('marc-messages');
        const typing = document.createElement('div');
        typing.className = 'marc-typing';
        typing.innerHTML = '<span></span><span></span><span></span>';
        msgs.appendChild(typing);
        msgs.scrollTop = msgs.scrollHeight;

        try {
            const r = await fetch('/api/inbox/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg, entity_type: 'team_member', entity_key: 'cofounder' })
            });
            const data = await r.json();
            typing.remove();
            const tasks = data.tasks_created || [];
            marcAppend('ai', data.reply || data.error || 'Error.', tasks);

            // If tasks were created, show dispatch badge in prompt bar + refresh pending strip
            if (tasks.length > 0) {
                _showDispatchBadge(tasks);
                marcLoadPending();
            }
        } catch (e) {
            typing.remove();
            marcAppend('ai', 'Connection error. Is the server running?');
        } finally {
            btn.disabled = false;
            document.getElementById('marc-input').focus();
        }
    }

    function _showDispatchBadge(tasks) {
        // Remove any existing badge
        const old = document.getElementById('marc-dispatch-badge');
        if (old) old.remove();

        const bar = document.getElementById('marc-prompt-bar');
        const badge = document.createElement('div');
        badge.id = 'marc-dispatch-badge';
        badge.className = 'marc-dispatch-badge';
        badge.innerHTML = `<strong>✅ ${tasks.length} task${tasks.length>1?'s':''} dispatched</strong>
            <span style="opacity:0.6">— awaiting your approval</span>
            <button class="marc-dispatch-approve-all" onclick="marcApproveAll()">✓ Approve All</button>
            <button class="marc-dispatch-email" onclick="marcSendApprovalEmail()">📬 Email</button>
            <a href="/inbox" style="font-size:10px;font-weight:700;color:#007aff;text-decoration:none;margin-left:2px">→ Inbox</a>`;
        bar.appendChild(badge);

        // Auto-hide after 12 seconds
        setTimeout(() => { if (badge.parentNode) badge.remove(); }, 12000);
    }

    async function marcProposePlan() {
        if (!_marcOpen) marcToggle();
        document.getElementById('marc-input').value =
            "Analyze our current state — vision, team, active workflows, and gaps. Then dispatch a concrete action plan: the 5-7 highest-priority tasks we need RIGHT NOW. Assign each to the right team member with specific instructions. Create the tasks JSON immediately.";
        marcSend();
    }

    // ── Live task dashboard in panel ─────────────────────────────────────────
    let _lastPulseStats = null;

    async function marcLoadPending() {
        try {
            // Fetch pending approvals, in-progress, and recently completed tasks
            const [pendingRes, activeRes, doneRes] = await Promise.all([
                fetch('/api/tasks/pending_approval'),
                fetch('/api/tasks?status=in_progress&all=1&_t=' + Date.now()),
                fetch('/api/tasks?status=done&_t=' + Date.now()),
            ]);
            const pendingData = pendingRes.ok ? await pendingRes.json() : { tasks: [] };
            const activeData  = activeRes.ok ? await activeRes.json() : { tasks: [] };
            const doneData    = doneRes.ok ? await doneRes.json() : { tasks: [] };

            const pending = (pendingData.tasks || []).filter(t => t.status !== 'rejected');
            const inProgress = (activeData.tasks || []);
            const recentDone = (doneData.tasks || []).slice(0, 5);  // last 5 completed

            const strip = document.getElementById('marc-pending-strip');
            const list = document.getElementById('marc-pending-list');

            if (pending.length === 0 && inProgress.length === 0 && recentDone.length === 0) {
                strip.style.display = 'none';
                return;
            }
            strip.style.display = 'block';

            let html = '';

            // In-progress tasks (being executed by team — show cascade sub-task progress)
            if (inProgress.length > 0) {
                // Separate parent cascade tasks from regular sub-tasks
                const parentTasks = inProgress.filter(t => !t.parent_id);
                html += `<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#007aff;margin-bottom:5px">🔄 Working Now (${parentTasks.length} task${parentTasks.length!==1?'s':''})</div>`;
                parentTasks.slice(0, 6).forEach(t => {
                    const hasSubs = t.subtask_count > 0;
                    const subProg = hasSubs ? ` <span style="font-size:9px;color:#34c759;font-weight:600">${t.subtasks_done}/${t.subtask_count} done</span>` : '';
                    const borderStyle = hasSubs ? 'border-left:2px solid #007aff;padding-left:6px;' : '';
                    html += `<div class="marc-pending-task-row" style="opacity:0.85;${borderStyle}">
                        <span style="width:6px;height:6px;border-radius:50%;background:#007aff;flex-shrink:0;animation:marc-blink 1.2s infinite"></span>
                        <div class="marc-pending-task-title" style="color:#007aff;font-size:11px">${t.title}${subProg}</div>
                        <span style="font-size:9px;color:#8e8e93;flex-shrink:0">${t.assignee_name||''}</span>
                    </div>`;
                });
                if (parentTasks.length > 6) html += `<div style="font-size:10px;color:#8e8e93;padding:2px 0;text-align:center">+${parentTasks.length-6} more executing…</div>`;
            }

            // Pending approval tasks
            if (pending.length > 0) {
                html += `<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#ff9500;margin:${inProgress.length?'8':'0'}px 0 5px">⏳ Awaiting Approval (${pending.length})</div>`;
                pending.slice(0, 5).forEach(t => {
                    const pri = (t.priority || 'medium').toLowerCase();
                    html += `<div class="marc-pending-task-row">
                        <span class="marc-pending-task-pri ${pri}">${pri.toUpperCase()}</span>
                        <div class="marc-pending-task-title" title="${(t.title||'').replace(/"/g,'&quot;')}">${t.title}</div>
                        <span style="font-size:10px;color:#8e8e93;flex-shrink:0;max-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.assignee_name||''}</span>
                        <button class="marc-approve-btn" onclick="marcApproveOne(${t.id}, this)">✓</button>
                    </div>`;
                });
                if (pending.length > 5) html += `<div style="font-size:10px;color:#8e8e93;padding:2px 0;text-align:center">+${pending.length-5} more → <a href="/inbox" style="color:#ff9500">Inbox</a></div>`;
            }

            // Recently completed tasks (history)
            if (recentDone.length > 0) {
                html += `<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#34c759;margin:8px 0 5px">✅ Recently Done (${recentDone.length})</div>`;
                recentDone.slice(0, 4).forEach(t => {
                    const ago = t.completed_at ? _timeAgo(t.completed_at) : '';
                    const hasSubs = t.subtask_count > 0;
                    const subLabel = hasSubs ? ` <span style="font-size:9px;color:#8e8e93">(${t.subtask_count} sub-tasks)</span>` : '';
                    html += `<div class="marc-pending-task-row" style="opacity:0.6">
                        <span style="font-size:11px;flex-shrink:0">✅</span>
                        <div class="marc-pending-task-title" style="font-size:11px;text-decoration:line-through;color:#8e8e93">${t.title}${subLabel}</div>
                        <span style="font-size:9px;color:#8e8e93;flex-shrink:0">${ago}</span>
                    </div>`;
                });
            }

            list.innerHTML = html;
        } catch(e) {}
    }

    function _timeAgo(isoStr) {
        if (!isoStr) return '';
        const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff/60) + 'm ago';
        if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
        return Math.floor(diff/86400) + 'd ago';
    }

    async function marcApproveOne(id, btn) {
        btn.disabled = true; btn.textContent = '…';
        try {
            await fetch(`/api/tasks/${id}/approve`, { method: 'POST' });
            btn.textContent = '✓'; btn.style.color = '#34c759';
            await marcLoadPending();
        } catch(e) { btn.disabled = false; btn.textContent = '✓'; }
    }

    async function marcApproveAll() {
        try {
            const r = await fetch('/api/tasks/approve_all', { method: 'POST' });
            const d = await r.json();
            await marcLoadPending();
            if (d.approved > 0) {
                marcAppend('ai', `🚀 All ${d.approved} task${d.approved>1?'s':''} approved and dispatched. Every team member is executing RIGHT NOW. Track progress in your [📥 Inbox](/inbox).`);
            }
        } catch(e) {}
    }

    // ── Send approval email ───────────────────────────────────────────────────
    async function marcSendApprovalEmail() {
        try {
            const r = await fetch('/api/cofounder/approval_email_body');
            const d = await r.json();
            if (d.count === 0) { marcAppend('ai', 'No pending tasks.'); return; }
            const mailto = `mailto:?subject=${encodeURIComponent(d.subject)}&body=${encodeURIComponent(d.body)}`;
            window.open(mailto, '_blank');
            marcAppend('ai', `📬 Email prepared with ${d.count} tasks for review.`);
        } catch(e) {
            marcAppend('ai', 'Email failed — review tasks in [📥 Inbox](/inbox).');
        }
    }
    window.marcSendApprovalEmail = marcSendApprovalEmail;

    // ── PROACTIVE PULSE — Marc never sleeps ──────────────────────────────────
    let _pulseRunning = false;

    async function marcPulse() {
        if (_pulseRunning || _marcMinimized) return;
        _pulseRunning = true;
        try {
            const r = await fetch('/api/cofounder/pulse', { method: 'POST' });
            const d = await r.json();
            _lastPulseStats = d.stats || {};

            if (d.action === 'dispatched' && d.new_tasks > 0) {
                // Marc auto-generated tasks — show notification in prompt bar
                const badge = document.getElementById('marc-dispatch-badge');
                if (badge) badge.remove();

                const bar = document.getElementById('marc-prompt-bar');
                const newBadge = document.createElement('div');
                newBadge.id = 'marc-dispatch-badge';
                newBadge.className = 'marc-dispatch-badge';
                newBadge.innerHTML = `<strong>🚀 Marc auto-dispatched ${d.new_tasks} new task${d.new_tasks>1?'s':''}</strong>
                    <span style="opacity:0.6">— approve to execute</span>
                    <button class="marc-dispatch-approve-all" onclick="marcApproveAll()">✓ Approve All</button>
                    <a href="/inbox" style="font-size:10px;font-weight:700;color:#007aff;text-decoration:none;margin-left:4px">→ Inbox</a>`;
                bar.appendChild(newBadge);
                setTimeout(() => { if (newBadge.parentNode) newBadge.remove(); }, 15000);

                // Refresh pending strip
                marcLoadPending();
            }
        } catch(e) {
            // Silent fail — pulse is background activity
        } finally {
            _pulseRunning = false;
        }
    }

    // Pulse every 90 seconds — Marc is always working
    let _pulseInterval = setInterval(marcPulse, 90000);
    // Also refresh pending strip every 15s
    setInterval(marcLoadPending, 15000);

    // ── Load history ──────────────────────────────────────────────────────────
    async function marcInit() {
        try {
            const r = await fetch('/api/inbox/thread_for_entity?entity_type=team_member&entity_key=cofounder');
            const d = await r.json();
            const msgs = d.messages || [];
            if (msgs.length > 0) {
                msgs.forEach(m => {
                    const role = (m.from_type === 'user' || m.from_key === 'supervisor') ? 'user' : 'ai';
                    marcAppend(role, m.body);
                });
                // Load pending strip
                marcLoadPending();
                return;
            }
        } catch (e) {}

        // No history — check vision
        try {
            const r = await fetch('/api/vision');
            const d = await r.json();
            const hasMission = d.vision && d.vision.mission && d.vision.mission.trim().length > 0;
            if (!hasMission) {
                marcAppend('ai', "Before we can do anything meaningful, we need a North Star.\n\nRight now you have no vision. No mission. No \"why\". That's dangerous — your team is executing without direction.\n\n**Go to [🚀 Vision](/vision) and let's establish what you're building, why you're building it, and where this is going.**\n\nWho are you? What problem are you solving? What does winning look like in 5 years?");
            } else {
                marcAppend('ai', `Vision locked in: **"${d.vision.mission}"**\n\nGood. What do you want to tackle — I'll dispatch the work immediately.`);
            }
        } catch (e) {
            marcAppend('ai', "Ready when you are. Tell me what we need to build and I'll dispatch the team.");
        }
    }

    // ── Keyboard ──────────────────────────────────────────────────────────────
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && document.activeElement === document.getElementById('marc-input')) {
            e.preventDefault();
            marcSend();
        }
    });

    // ── Expose globals ────────────────────────────────────────────────────────
    window.marcToggle = marcToggle;
    window.marcSend = marcSend;
    window.marcProposePlan = marcProposePlan;
    window.marcApproveAll = marcApproveAll;
    window.marcApproveOne = marcApproveOne;
    window.marcLoadPending = marcLoadPending;
    window.marcMinimize = marcMinimize;
    window.marcRestore = marcRestore;

    // ── Boot ──────────────────────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', marcInit);
    } else {
        marcInit();
    }
})();
