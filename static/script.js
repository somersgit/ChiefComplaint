const chatLog = document.getElementById('chat-log');
const form = document.getElementById('chat-form');
const input = document.getElementById('user-input');
const btnFinishHistory = document.getElementById('btn-finish-history');
const btnStartExam = document.getElementById('btn-start-exam');
const btnFinalize = document.getElementById('btn-finalize');
const btnReset = document.getElementById('btn-reset');
const btnStartTx = document.getElementById('btn-start-tx');
const btnFinalizeEncounter = document.getElementById('btn-finalize-encounter');
const stageHistory = document.getElementById('stage-history');
const caseSelect = document.getElementById('case-select');

const stages = {
  HISTORY: 'HISTORY',
  HX_DISCUSS: 'HX_DISCUSS',
  EXAM: 'EXAM',
  DX_DISCUSS: 'DX_DISCUSS',
  FINAL: 'FINAL',
  TREATMENT: 'TREATMENT'
};

let state = { stage: stages.HISTORY, session_id: null, case_id: null };

function isNearBottom(threshold = 56) {
  const remaining = chatLog.scrollHeight - chatLog.scrollTop - chatLog.clientHeight;
  return remaining <= threshold;
}

function scrollChatToBottom(behavior = 'auto') {
  const composerOffset = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--composer-offset'), 10) || 0;
  chatLog.scrollTo({ top: chatLog.scrollHeight + composerOffset, behavior });
}

function updateComposerOffset() {
  const rect = form.getBoundingClientRect();
  const safeInset = 4;
  const keyboardOffset = window.visualViewport
    ? Math.max(0, window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop)
    : 0;

  const safeOffset = Math.ceil(rect.height + keyboardOffset + safeInset);
  document.documentElement.style.setProperty('--composer-offset', `${safeOffset}px`);
  document.documentElement.style.setProperty('--keyboard-offset', `${Math.ceil(keyboardOffset)}px`);
  document.body.classList.toggle('keyboard-open', keyboardOffset > 0);
}

function syncViewportLayout({ keepBottom = false, smooth = false } = {}) {
  const shouldStick = keepBottom || isNearBottom();
  updateComposerOffset();
  if (!shouldStick) return;

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      scrollChatToBottom(smooth ? 'smooth' : 'auto');
    });
  });
}

function addMessage(text, role='sys') {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  chatLog.appendChild(div);
  syncViewportLayout({ keepBottom: true });
}

function apiGet(path) {
  return fetch(path).then((res) => res.json());
}

async function api(path, payload={}) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, session_id: state.session_id, case_id: state.case_id })
  });
  const data = await res.json();
  if (data.session_id) state.session_id = data.session_id;
  if (data.case_id) state.case_id = data.case_id;
  return data;
}

function setStage(stage) {
  state.stage = stage;

  const stageButtonMap = {
    [stages.HISTORY]: stageHistory,
    [stages.HX_DISCUSS]: btnFinishHistory,
    [stages.EXAM]: btnStartExam,
    [stages.DX_DISCUSS]: btnFinalize,
    [stages.TREATMENT]: btnStartTx,
    [stages.FINAL]: btnFinalizeEncounter
  };

  [stageHistory, btnFinishHistory, btnStartExam, btnFinalize, btnStartTx, btnFinalizeEncounter]
    .forEach((control) => control.classList.remove('active-stage'));

  const activeButton = stageButtonMap[stage];
  if (activeButton) activeButton.classList.add('active-stage');
}

function resetWorkflowControls() {
  btnStartExam.disabled = true;
  btnFinalize.disabled = true;
  btnStartTx.disabled = true;
  btnFinalizeEncounter.disabled = true;
}

async function startSession(caseId) {
  state = { stage: stages.HISTORY, session_id: null, case_id: caseId };
  resetWorkflowControls();
  chatLog.innerHTML = '';

  const data = await api('/api/session/start', { case_id: caseId });
  state.case_id = data.case_id;
  setStage(stages.HISTORY);
  addMessage(`Session started for ${data.case_label}. You are speaking with the patient. Ask history questions to gather HPI, PMH, meds, allergies, ROS, and social/sexual/family history. When done, click "Page Attending".`, 'sys');
}

async function initCaseSelector() {
  const payload = await apiGet('/api/cases');
  caseSelect.innerHTML = '';

  for (const c of payload.cases) {
    const option = document.createElement('option');
    option.value = c.id;
    option.textContent = c.label;
    if (c.id === payload.default_case_id) option.selected = true;
    caseSelect.appendChild(option);
  }

  caseSelect.addEventListener('change', async (e) => {
    await startSession(e.target.value);
  });

  await startSession(payload.default_case_id);
}

// Initialize session
initCaseSelector();

syncViewportLayout({ keepBottom: true });
window.addEventListener('resize', () => syncViewportLayout({ keepBottom: true }));
window.addEventListener('orientationchange', () => syncViewportLayout({ keepBottom: true }));

if (window.visualViewport) {
  const syncWithViewport = () => {
    syncViewportLayout({ keepBottom: true });
    if (document.activeElement === input) {
      form.scrollIntoView({ block: 'end', inline: 'nearest' });
    }
  };

  window.visualViewport.addEventListener('resize', syncWithViewport);
  window.visualViewport.addEventListener('scroll', syncWithViewport);
}

if (window.ResizeObserver) {
  const composerObserver = new ResizeObserver(() => syncViewportLayout({ keepBottom: true }));
  composerObserver.observe(form);
}

input.addEventListener('focus', () => {
  setTimeout(() => {
    syncViewportLayout({ keepBottom: true, smooth: true });
  }, 200);
});

// Buttons
btnFinishHistory.addEventListener('click', async () => {
  setStage(stages.HX_DISCUSS);
  btnStartExam.disabled = false;
  addMessage('You paged the attending.', 'sys');
  const resp = await api('/api/attending/open', {});
  addMessage(resp.reply, 'attending');
});

btnStartExam.addEventListener('click', async () => {
  setStage(stages.EXAM);
  btnFinalize.disabled = false;
  addMessage('You started the physical exam phase. Ask the attending for exam findings.', 'sys');
  const intro = await api('/api/attending/exam_intro', {});
  addMessage(intro.reply, 'attending');
});

btnFinalize.addEventListener('click', async () => {
  setStage(stages.DX_DISCUSS);
  addMessage('Share your leading diagnosis and differentials. Then submit here to get the final assessment.', 'sys');
  const prompt = await api('/api/attending/final_prompt', {});
  addMessage(prompt.reply, 'attending');
});

btnReset.addEventListener('click', async () => {
  await fetch('/api/session/reset', { method: 'POST' });
  await startSession(caseSelect.value);
});

btnStartTx.addEventListener('click', async () => {
  const resp = await api('/api/attending/start_treatment', {});
  addMessage(resp.reply, 'attending');
  setStage(stages.TREATMENT);
  btnStartTx.disabled = true;
  btnFinalizeEncounter.disabled = false;
});

btnFinalizeEncounter.addEventListener('click', async () => {
  const resp = await api('/api/attending/finalize_encounter', {});
  addMessage(resp.reply, 'attending');
});

// Chat submit
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMessage(text, 'you');

  let endpoint = '/api/patient/chat';
  if (state.stage === stages.HX_DISCUSS) endpoint = '/api/attending/history_discuss';
  if (state.stage === stages.EXAM) endpoint = '/api/attending/exam_chat';
  if (state.stage === stages.DX_DISCUSS) endpoint = '/api/attending/final_collect';
  if (state.stage === stages.FINAL) endpoint = '/api/attending/final_followups';
  if (state.stage === stages.TREATMENT) endpoint = '/api/attending/treatment_assess';

  const resp = await api(endpoint, { message: text });
  const role = resp.role || (state.stage === stages.HISTORY ? 'patient' : 'attending');
  addMessage(resp.reply, role);
  syncViewportLayout({ keepBottom: true });

  if (endpoint === '/api/attending/final_collect') {
    btnStartTx.disabled = false;
  }

  if (resp.advance_to) {
    setStage(resp.advance_to);
    if (state.stage === stages.FINAL) {
      btnFinalize.disabled = true;
    }
  }
});
