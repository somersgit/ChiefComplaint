const chatLog = document.getElementById('chat-log');
const form = document.getElementById('chat-form');
const input = document.getElementById('user-input');
const btnHistory = document.getElementById('btn-history');
const btnFinishHistory = document.getElementById('btn-finish-history');
const btnStartExam = document.getElementById('btn-start-exam');
const btnFinalize = document.getElementById('btn-finalize');
const btnReset = document.getElementById('btn-reset');
const btnStartTx = document.getElementById('btn-start-tx');
const btnFinalizeEncounter = document.getElementById('btn-finalize-encounter');

const stages = {
  HISTORY: 'HISTORY',
  HX_DISCUSS: 'HX_DISCUSS', // attending asks for differential after history
  EXAM: 'EXAM',             // resident asks attending about exam
  DX_DISCUSS: 'DX_DISCUSS', // attending asks for final dx
  FINAL: 'FINAL',            // final assessment/feedback
  TREATMENT: 'TREATMENT'
};

let state = { stage: stages.HISTORY, session_id: null };

function addMessage(text, role='sys') {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function api(path, payload={}) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, session_id: state.session_id })
  });
  const data = await res.json();
  if (data.session_id) state.session_id = data.session_id;
  return data;
}

function setStage(stage) {
  state.stage = stage;

  const stageButtonMap = {
    [stages.HISTORY]: btnHistory,
    [stages.HX_DISCUSS]: btnFinishHistory,
    [stages.EXAM]: btnStartExam,
    [stages.DX_DISCUSS]: btnFinalize,
    [stages.TREATMENT]: btnStartTx,
    [stages.FINAL]: btnFinalizeEncounter
  };

  [btnHistory, btnFinishHistory, btnStartExam, btnFinalize, btnStartTx, btnFinalizeEncounter]
    .forEach((button) => button.classList.remove('active-stage'));

  const activeButton = stageButtonMap[stage];
  if (activeButton) activeButton.classList.add('active-stage');
}

// Initialize session
(async () => {
  const data = await api('/api/session/start', {});
  setStage(stages.HISTORY);
  addMessage('Session started. You are speaking with the patient. Ask history questions to gather HPI, PMH, meds, allergies, ROS, and social/sexual/family history. When done, click "Page Attending".', 'sys');
})();

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
  state = { stage: stages.HISTORY, session_id: null };
  chatLog.innerHTML = '';
  await fetch('/api/session/reset', { method: 'POST' });
  location.reload();
});

btnStartTx.addEventListener('click', async () => {
  const resp = await api('/api/attending/start_treatment', { session_id: state.session_id });
  addMessage(resp.reply, 'attending');
  setStage(stages.TREATMENT);
  btnStartTx.disabled = true;
  btnFinalizeEncounter.disabled = false; // allow finalize after assessment
});
btnFinalizeEncounter.addEventListener('click', async () => {
  const resp = await api('/api/attending/finalize_encounter', { session_id: state.session_id });
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
