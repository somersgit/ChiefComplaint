const chatLog = document.getElementById('chat-log');
const form = document.getElementById('chat-form');
const input = document.getElementById('user-input');
const stageLabel = document.getElementById('stage-label');
const btnFinishHistory = document.getElementById('btn-finish-history');
const btnStartExam = document.getElementById('btn-start-exam');
const btnFinalize = document.getElementById('btn-finalize');
const btnReset = document.getElementById('btn-reset');
const btnStartTx = document.getElementById('btn-start-tx');
const btnFinalizeEncounter = document.getElementById('btn-finalize-encounter');
const caseSelect = document.getElementById('case-select');
const btnNewCase = document.getElementById('btn-new-case');
const caseFormSection = document.getElementById('case-form');
const newCaseForm = document.getElementById('new-case-form');
const caseTitleInput = document.getElementById('case-title');
const caseHistoryInput = document.getElementById('case-history');
const caseExamInput = document.getElementById('case-exam');
const caseDxInput = document.getElementById('case-dx');
const btnCancelCase = document.getElementById('btn-cancel-case');
const caseDownloads = document.getElementById('case-downloads');
const downloadHistoryTxt = document.getElementById('download-history-txt');
const downloadExamTxt = document.getElementById('download-exam-txt');
const downloadHistoryPdf = document.getElementById('download-history-pdf');
const downloadExamPdf = document.getElementById('download-exam-pdf');

const stages = {
  HISTORY: 'HISTORY',
  HX_DISCUSS: 'HX_DISCUSS', // attending asks for differential after history
  EXAM: 'EXAM',             // resident asks attending about exam
  DX_DISCUSS: 'DX_DISCUSS', // attending asks for final dx
  FINAL: 'FINAL',            // final assessment/feedback
  TREATMENT: 'TREATMENT'
};

let state = { stage: stages.HISTORY, session_id: null, case_id: 'default' };

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
    body: JSON.stringify({ ...payload, session_id: state.session_id, case_id: state.case_id })
  });
  const data = await res.json();
  if (data.session_id) state.session_id = data.session_id;
  if (data.case_id) state.case_id = data.case_id;
  return data;
}

function setStage(stage) {
  state.stage = stage;
  let label = 'History (Patient)';
  if (stage === stages.HX_DISCUSS) label = 'Attending: Discuss history & differential';
  if (stage === stages.EXAM) label = 'Attending: Physical exam Q&A';
  if (stage === stages.DX_DISCUSS) label = 'Attending: Final diagnosis discussion';
  if (stage === stages.FINAL) label = 'Final assessment';
  stageLabel.textContent = label;
}

function resetButtons() {
  btnStartExam.disabled = true;
  btnFinalize.disabled = true;
  btnStartTx.disabled = true;
  btnFinalizeEncounter.disabled = true;
}

async function startSession() {
  const data = await api('/api/session/start', {});
  setStage(stages.HISTORY);
  resetButtons();
  addMessage('Session started. You are speaking with the patient. Ask history questions to gather HPI, PMH, meds, allergies, ROS, and social/sexual/family history. When done, click "Page Attending".', 'sys');
  return data;
}

async function loadCases() {
  const res = await fetch('/api/cases/list', { method: 'POST' });
  const data = await res.json();
  caseSelect.innerHTML = '';
  data.cases.forEach((caseItem) => {
    const option = document.createElement('option');
    option.value = caseItem.id;
    option.textContent = caseItem.title;
    caseSelect.appendChild(option);
  });
  if (![...caseSelect.options].some((opt) => opt.value === state.case_id)) {
    state.case_id = caseSelect.options[0]?.value || 'default';
  }
  caseSelect.value = state.case_id;
}

// Initialize session
(async () => {
  await loadCases();
  await startSession();
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
  state = { stage: stages.HISTORY, session_id: null, case_id: state.case_id };
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

caseSelect.addEventListener('change', async (e) => {
  state.case_id = e.target.value;
  state.session_id = null;
  chatLog.innerHTML = '';
  await startSession();
});

btnNewCase.addEventListener('click', () => {
  caseFormSection.classList.remove('hidden');
  caseDownloads.classList.add('hidden');
});

btnCancelCase.addEventListener('click', () => {
  caseFormSection.classList.add('hidden');
});

newCaseForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    title: caseTitleInput.value.trim(),
    history_text: caseHistoryInput.value.trim(),
    exam_text: caseExamInput.value.trim(),
    assigned_diagnosis: caseDxInput.value.trim()
  };
  const res = await fetch('/api/cases/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  caseTitleInput.value = '';
  caseHistoryInput.value = '';
  caseExamInput.value = '';
  caseDxInput.value = '';
  await loadCases();
  state.case_id = data.case.id;
  caseSelect.value = data.case.id;
  downloadHistoryTxt.href = data.downloads.history_txt;
  downloadExamTxt.href = data.downloads.exam_txt;
  downloadHistoryPdf.href = data.downloads.history_pdf;
  downloadExamPdf.href = data.downloads.exam_pdf;
  caseDownloads.classList.remove('hidden');
  caseFormSection.classList.add('hidden');
  chatLog.innerHTML = '';
  await startSession();
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
