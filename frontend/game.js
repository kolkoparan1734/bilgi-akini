// ============================================
// BİLGİ AKINI — oyun mantığı (dünya haritası + 2 kişilik mod)
// ============================================

const API_HOST = window.location.hostname;
const API_BASE = `http://${API_HOST}:5000/api`;
const SOCKET_BASE = `http://${API_HOST}:5000`;
const QUESTION_TIME = 15; // saniye

const state = {
  username: null,
  mode: null, // "solo" | "duo"
  eras: [],
  currentEra: null,
  countries: [], // ekranda çizilen, hesaplanmış liste (her iki mod da bunu kullanır)
  gold: 0,
  conqueredCount: 0,

  activeCountry: null,
  activeEvent: null, // {id, title, leader, questions?} — solo'da tam liste, duo'da tek soru akışı
  qIndex: 0,
  qTotal: 0,
  currentQuestion: null,
  answers: {}, // solo: question_id -> chosen key
  timerInterval: null,
  timeLeft: QUESTION_TIME,
  answered: false,

  // 2 kişilik mod
  socket: null,
  roomCode: null,
  opponentUsername: null,
  countriesRaw: null, // /api/countries/all — dönemden bağımsız ham liste
  duoEvents: new Map(), // event_id -> {id,country_id,era_key,title,leader,gold_reward,state,owner}
};

// ---------- DOM referansları ----------
const el = {
  loginScreen: document.getElementById("login-screen"),
  modeScreen: document.getElementById("mode-screen"),
  roomScreen: document.getElementById("room-screen"),
  mapScreen: document.getElementById("map-screen"),
  usernameInput: document.getElementById("username-input"),
  startBtn: document.getElementById("start-btn"),
  soloModeBtn: document.getElementById("solo-mode-btn"),
  duoModeBtn: document.getElementById("duo-mode-btn"),
  roomIdle: document.getElementById("room-idle"),
  roomWaiting: document.getElementById("room-waiting"),
  createRoomBtn: document.getElementById("create-room-btn"),
  joinCodeInput: document.getElementById("join-code-input"),
  joinRoomBtn: document.getElementById("join-room-btn"),
  roomError: document.getElementById("room-error"),
  roomCodeDisplay: document.getElementById("room-code-display"),
  map: document.getElementById("map"),
  eraTabs: document.getElementById("era-tabs"),
  mapHint: document.getElementById("map-hint"),
  goldCount: document.getElementById("gold-count"),
  conquerCount: document.getElementById("conquer-count"),
  enemyStat: document.querySelector(".enemy-stat"),
  enemyConquerCount: document.getElementById("enemy-conquer-count"),
  enemyName: document.getElementById("enemy-name"),

  eventSelectModal: document.getElementById("event-select-modal"),
  eventSelectCountry: document.getElementById("event-select-country"),
  eventList: document.getElementById("event-list"),
  eventSelectClose: document.getElementById("event-select-close"),

  emptyModal: document.getElementById("empty-modal"),
  emptyCountryName: document.getElementById("empty-country-name"),
  emptyCloseBtn: document.getElementById("empty-close-btn"),

  quizModal: document.getElementById("quiz-modal"),
  quizEventTitle: document.getElementById("quiz-event-title"),
  quizProgress: document.getElementById("quiz-progress"),
  quizText: document.getElementById("quiz-text"),
  quizOptions: document.getElementById("quiz-options"),
  quizFeedback: document.getElementById("quiz-feedback"),
  timerFill: document.getElementById("timer-fill"),

  resultModal: document.getElementById("result-modal"),
  resultEyebrow: document.getElementById("result-eyebrow"),
  resultTitle: document.getElementById("result-title"),
  resultDetail: document.getElementById("result-detail"),
  resultCloseBtn: document.getElementById("result-close-btn"),

  matchOverModal: document.getElementById("match-over-modal"),
  matchOverTitle: document.getElementById("match-over-title"),
  matchOverScores: document.getElementById("match-over-scores"),
  matchRestartBtn: document.getElementById("match-restart-btn"),
  opponentLeftModal: document.getElementById("opponent-left-modal"),
  opponentLeftBtn: document.getElementById("opponent-left-btn"),
};

// ---------- Başlangıç ----------
el.startBtn.addEventListener("click", handleStart);
el.usernameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") handleStart();
});
el.eventSelectClose.addEventListener("click", () => el.eventSelectModal.classList.add("hidden"));
el.emptyCloseBtn.addEventListener("click", () => el.emptyModal.classList.add("hidden"));
el.resultCloseBtn.addEventListener("click", () => {
  el.resultModal.classList.add("hidden");
  refreshMap();
});
el.matchRestartBtn.addEventListener("click", () => window.location.reload());
el.opponentLeftBtn.addEventListener("click", () => window.location.reload());

function safeStorageGet(key) {
  try { return localStorage.getItem(key); } catch (err) { return null; }
}
function safeStorageSet(key, value) {
  try { localStorage.setItem(key, value); } catch (err) { /* gizli sekme vb. — yok say */ }
}

const savedUser = safeStorageGet("bilgi_akini_user");
if (savedUser) {
  el.usernameInput.value = savedUser;
}

async function tryLockLandscape() {
  // Sadece Chrome/Android gibi tam ekran + Screen Orientation API destekleyen
  // ortamlarda çalışır (iOS Safari desteklemez) — bu yüzden sessizce yutulur,
  // asıl güvence CSS'teki "yatay çevir" uyarısıdır.
  try {
    if (document.documentElement.requestFullscreen) {
      await document.documentElement.requestFullscreen();
    }
    if (screen.orientation && screen.orientation.lock) {
      await screen.orientation.lock("landscape");
    }
  } catch (err) {
    /* desteklenmiyor — rotate-prompt zaten yedek olarak devrede */
  }
}

async function handleStart() {
  const username = el.usernameInput.value.trim();
  if (!username) {
    el.usernameInput.focus();
    return;
  }
  tryLockLandscape();
  state.username = username;
  safeStorageSet("bilgi_akini_user", username);

  try {
    const playerRes = await fetch(`${API_BASE}/player/${encodeURIComponent(username)}`);
    const player = await playerRes.json();
    state.gold = player.gold;
    state.conqueredCount = player.conquered_count;
    updateStatsUI();

    const erasRes = await fetch(`${API_BASE}/eras`);
    state.eras = await erasRes.json();
    state.currentEra = (state.eras.find((e) => e.key === "yukselis") || state.eras[0]).key;

    el.loginScreen.classList.add("hidden");
    el.modeScreen.classList.remove("hidden");
  } catch (err) {
    alert("Sunucuya bağlanılamadı. Backend çalışıyor mu? (" + err.message + ")");
  }
}

// ---------- Mod seçimi ----------
el.soloModeBtn.addEventListener("click", async () => {
  state.mode = "solo";
  el.modeScreen.classList.add("hidden");
  el.mapScreen.classList.remove("hidden");
  el.mapHint.textContent = "Bir ülkeye dokun, tarihi olayı fethet.";
  el.enemyStat.classList.add("hidden");
  renderEraTabs();
  await loadCountries();
});

el.duoModeBtn.addEventListener("click", () => {
  state.mode = "duo";
  ensureSocket();
  el.modeScreen.classList.add("hidden");
  el.roomScreen.classList.remove("hidden");
  el.roomIdle.classList.remove("hidden");
  el.roomWaiting.classList.add("hidden");
  el.roomError.classList.add("hidden");
});

// ---------- Oda kur / katıl ----------
el.createRoomBtn.addEventListener("click", () => {
  el.roomError.classList.add("hidden");
  state.socket.emit("create_room", { username: state.username });
});

el.joinRoomBtn.addEventListener("click", () => {
  const code = el.joinCodeInput.value.trim();
  el.roomError.classList.add("hidden");
  if (!/^\d{4}$/.test(code)) {
    el.roomError.textContent = "4 haneli oda kodunu gir.";
    el.roomError.classList.remove("hidden");
    return;
  }
  state.socket.emit("join_room_request", { username: state.username, code });
});

function ensureSocket() {
  if (state.socket) return state.socket;
  const socket = io(SOCKET_BASE);
  state.socket = socket;

  socket.on("room_error", ({ message }) => {
    el.roomError.textContent = message;
    el.roomError.classList.remove("hidden");
  });

  socket.on("room_created", ({ code }) => {
    state.roomCode = code;
    el.roomIdle.classList.add("hidden");
    el.roomWaiting.classList.remove("hidden");
    el.roomCodeDisplay.textContent = code;
  });

  socket.on("match_start", async (data) => {
    state.roomCode = data.code;
    state.opponentUsername = data.players.find((p) => p !== state.username) || null;

    if (!state.countriesRaw) {
      const res = await fetch(`${API_BASE}/countries/all`);
      state.countriesRaw = await res.json();
    }
    state.duoEvents = new Map(data.events.map((e) => [e.id, e]));

    el.roomScreen.classList.add("hidden");
    el.mapScreen.classList.remove("hidden");
    el.enemyStat.classList.remove("hidden");
    el.enemyName.textContent = state.opponentUsername || "";
    el.mapHint.textContent = "Ülkelere saldır, rakibinden önce fethet!";

    renderEraTabs();
    refreshMap();
    updateDuoStatsUI();
  });

  socket.on("event_locked", ({ event_id, by }) => {
    const ev = state.duoEvents.get(event_id);
    if (ev) { ev.state = "locked"; ev.owner = by; }
    if (by !== state.username) refreshMap();
  });

  socket.on("attack_denied", ({ event_id }) => {
    if (state.activeEvent && state.activeEvent.id === event_id) {
      el.quizModal.classList.add("hidden");
    }
    refreshMap();
  });

  socket.on("question_ready", (data) => {
    // Bir önceki soruya doğru cevap verildiyse (advance), seçilen şıkkı
    // yeşille işaretleyip kısa bir bekleme sonrası yeni soruyu göster.
    const advancing = state.currentQuestion !== null;
    const lastChosen = state.lastChosenKey;

    state.activeEvent = { id: data.event_id, title: data.title, leader: data.leader };
    state.qIndex = data.index;
    state.qTotal = data.total;
    state.currentQuestion = { id: data.question_id, text: data.text, options: data.options };

    if (advancing) {
      const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
      buttons.forEach((b) => {
        b.classList.add("disabled");
        if (b.dataset.key === lastChosen) b.classList.add("correct");
      });
      setTimeout(() => renderQuizQuestion(), 1300);
    } else {
      el.quizModal.classList.remove("hidden");
      renderQuizQuestion();
    }
  });

  socket.on("event_result", (data) => {
    const { event_id, correct, owner, gold_reward, correct_option, by } = data;
    const ev = state.duoEvents.get(event_id);
    if (ev) {
      ev.state = correct ? "conquered" : "available";
      ev.owner = correct ? owner : null;
    }

    const iAmAttacker = by === state.username;
    if (iAmAttacker && state.activeEvent && state.activeEvent.id === event_id) {
      finishDuoEvent(correct, correct_option, gold_reward);
    } else {
      refreshMap();
      updateDuoStatsUI();
    }
  });

  socket.on("match_over", ({ scores }) => {
    const mine = scores[state.username] || 0;
    const enemy = scores[state.opponentUsername] || 0;
    let title;
    if (mine > enemy) title = "Zafer Senin!";
    else if (mine < enemy) title = "Rakip Kazandı";
    else title = "Berabere!";
    el.matchOverTitle.textContent = title;
    el.matchOverScores.textContent = `Sen: ${mine} bölge · Rakip: ${enemy} bölge`;
    el.matchOverModal.classList.remove("hidden");
  });

  socket.on("opponent_left", () => {
    el.quizModal.classList.add("hidden");
    el.opponentLeftModal.classList.remove("hidden");
  });

  return socket;
}

// ---------- Dönem sekmeleri ----------
function renderEraTabs() {
  el.eraTabs.innerHTML = "";
  state.eras.forEach((era) => {
    const btn = document.createElement("button");
    btn.className = "era-tab" + (era.key === state.currentEra ? " active" : "");
    btn.textContent = era.name;
    btn.addEventListener("click", async () => {
      if (state.currentEra === era.key) return;
      state.currentEra = era.key;
      renderEraTabs();
      await refreshMap();
    });
    el.eraTabs.appendChild(btn);
  });
}

// ---------- Harita (mod-agnostik render) ----------
async function refreshMap() {
  if (state.mode === "duo") {
    state.countries = computeDuoCountries();
    renderMap();
    updateDuoStatsUI();
  } else {
    await loadCountries();
  }
}

async function loadCountries() {
  const res = await fetch(
    `${API_BASE}/countries?era=${encodeURIComponent(state.currentEra)}&username=${encodeURIComponent(state.username)}`
  );
  state.countries = await res.json();
  renderMap();
}

function computeDuoCountries() {
  return state.countriesRaw.map((c) => {
    const events = [...state.duoEvents.values()].filter(
      (e) => e.country_id === c.id && e.era_key === state.currentEra
    );
    let status;
    if (events.length === 0) status = "empty";
    else if (events.every((e) => e.state === "conquered")) status = "conquered";
    else if (events.some((e) => e.state === "locked")) status = "locked";
    else status = "available";
    const mine = status === "conquered" && events.every((e) => e.owner === state.username);
    return { ...c, status, mine, events };
  });
}

function renderMap() {
  el.map.innerHTML = "";
  state.countries.forEach((country) => {
    const btn = document.createElement("button");
    let statusClass = country.status;
    if (country.status === "conquered" && state.mode === "duo" && !country.mine) {
      statusClass += " enemy";
    }
    btn.className = "country-marker " + statusClass;
    btn.style.left = country.x + "%";
    btn.style.top = country.y + "%";

    const badge = document.createElement("div");
    badge.className = "country-badge";
    badge.textContent = country.status === "conquered" ? "⚑" : country.status === "locked" ? "⏳" : "⛊";

    const label = document.createElement("div");
    label.className = "country-label";
    label.textContent = country.name;

    let ariaExtra = "";
    if (country.status === "conquered") ariaExtra = country.mine === false ? " (rakipte)" : " (fethedildi)";
    else if (country.status === "empty") ariaExtra = " (yakında)";
    else if (country.status === "locked") ariaExtra = " (kilitli)";
    btn.setAttribute("aria-label", country.name + ariaExtra);

    btn.appendChild(badge);
    btn.appendChild(label);

    const clickable = country.status === "empty" || country.status === "available";
    if (clickable) {
      btn.addEventListener("click", () => openCountry(country));
    }
    el.map.appendChild(btn);
  });
}

// ---------- Ülkeye tıklama → olay(lar) ----------
async function openCountry(country) {
  state.activeCountry = country;

  if (country.status === "empty") {
    el.emptyCountryName.textContent = country.name;
    el.emptyModal.classList.remove("hidden");
    return;
  }

  let events;
  if (state.mode === "duo") {
    events = country.events.filter((e) => e.state === "available");
  } else {
    const res = await fetch(
      `${API_BASE}/countries/${country.id}/events?era=${encodeURIComponent(state.currentEra)}&username=${encodeURIComponent(state.username)}`
    );
    events = await res.json();
  }

  if (events.length === 0) {
    el.emptyCountryName.textContent = country.name;
    el.emptyModal.classList.remove("hidden");
    return;
  }

  if (events.length === 1) {
    if (state.mode === "duo") attackEvent(events[0]);
    else openEvent(events[0]);
    return;
  }

  el.eventSelectCountry.textContent = country.name;
  el.eventList.innerHTML = "";
  events.forEach((ev) => {
    const item = document.createElement("button");
    item.className = "event-item" + (ev.conquered ? " conquered" : "");
    const title = document.createElement("span");
    title.className = "event-item-title";
    title.textContent = ev.title + (ev.conquered ? " ✓" : "");
    const leader = document.createElement("span");
    leader.className = "event-item-leader";
    leader.textContent = ev.leader || "";
    item.appendChild(title);
    item.appendChild(leader);
    item.addEventListener("click", () => {
      el.eventSelectModal.classList.add("hidden");
      if (state.mode === "duo") attackEvent(ev);
      else openEvent(ev);
    });
    el.eventList.appendChild(item);
  });
  el.eventSelectModal.classList.remove("hidden");
}

// ---------- Olay / çok soruluk quiz akışı — TEK KİŞİLİK ----------
async function openEvent(eventSummary) {
  const res = await fetch(`${API_BASE}/events/${eventSummary.id}?username=${encodeURIComponent(state.username)}`);
  const event = await res.json();

  state.activeEvent = event;
  state.qIndex = 0;
  state.qTotal = event.questions.length;
  state.currentQuestion = event.questions[0];
  state.answers = {};

  el.quizModal.classList.remove("hidden");
  renderQuizQuestion();
}

// ---------- Olay saldırısı — 2 KİŞİLİK ----------
function attackEvent(eventSummary) {
  state.activeEvent = { id: eventSummary.id, title: eventSummary.title, leader: eventSummary.leader };
  state.currentQuestion = null;
  state.lastChosenKey = null;
  state.socket.emit("attack_event", {
    code: state.roomCode,
    username: state.username,
    event_id: eventSummary.id,
  });
}

// ---------- Ortak soru render / zamanlayıcı ----------
function renderQuizQuestion() {
  const event = state.activeEvent;
  const question = state.mode === "solo" ? event.questions[state.qIndex] : state.currentQuestion;

  state.answered = false;
  el.quizFeedback.classList.add("hidden");
  el.quizEventTitle.textContent = event.title + (event.leader ? " · " + event.leader : "");
  el.quizProgress.textContent = `Soru ${state.qIndex + 1}/${state.qTotal}`;
  el.quizText.textContent = question.text;
  el.quizOptions.innerHTML = "";

  Object.entries(question.options).forEach(([key, label]) => {
    const btn = document.createElement("button");
    btn.className = "option-btn";
    btn.textContent = label;
    btn.dataset.key = key;
    btn.addEventListener("click", () => handleAnswer(key));
    el.quizOptions.appendChild(btn);
  });

  startTimer();
}

function startTimer() {
  state.timeLeft = QUESTION_TIME;
  el.timerFill.style.width = "100%";
  el.timerFill.classList.remove("warn");
  clearInterval(state.timerInterval);

  state.timerInterval = setInterval(() => {
    state.timeLeft -= 0.2;
    const pct = Math.max(0, (state.timeLeft / QUESTION_TIME) * 100);
    el.timerFill.style.width = pct + "%";
    if (pct < 30) el.timerFill.classList.add("warn");

    if (state.timeLeft <= 0) {
      clearInterval(state.timerInterval);
      if (!state.answered) handleAnswer(null);
    }
  }, 200);
}

function handleAnswer(chosenKey) {
  if (state.answered) return;
  if (state.mode === "duo") handleAnswerDuo(chosenKey);
  else handleAnswerSolo(chosenKey);
}

// ---------- Cevap işleme — TEK KİŞİLİK ----------
async function handleAnswerSolo(chosenKey) {
  state.answered = true;
  clearInterval(state.timerInterval);

  const event = state.activeEvent;
  const question = event.questions[state.qIndex];
  state.answers[question.id] = chosenKey;

  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => b.classList.add("disabled"));

  let check;
  try {
    const res = await fetch(`${API_BASE}/questions/${question.id}/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chosen: chosenKey }),
    });
    check = await res.json();
  } catch (err) {
    check = { correct: false, correct_option: null };
  }

  buttons.forEach((b) => {
    if (b.dataset.key === check.correct_option) b.classList.add("correct");
    else if (b.dataset.key === chosenKey) b.classList.add("wrong");
  });

  const isLast = state.qIndex === event.questions.length - 1;

  setTimeout(() => {
    if (!check.correct) {
      finishSoloEvent(false);
    } else if (isLast) {
      finishSoloEvent(true);
    } else {
      state.qIndex += 1;
      renderQuizQuestion();
    }
  }, 1300);
}

async function finishSoloEvent() {
  const event = state.activeEvent;

  let result;
  try {
    const res = await fetch(`${API_BASE}/events/${event.id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: state.username, answers: state.answers }),
    });
    result = await res.json();
  } catch (err) {
    result = null;
  }

  el.quizModal.classList.add("hidden");

  if (result) {
    state.gold = result.gold;
    state.conqueredCount = result.conquered_count;
    updateStatsUI();

    if (result.all_correct) {
      el.resultEyebrow.textContent = "Fetih Tamam";
      el.resultTitle.textContent = event.title + " Fethedildi!";
      el.resultDetail.textContent = result.already_conquered
        ? "Bu olayı zaten fethetmiştin."
        : `+${result.gold_reward} akınca kazandın.`;
    } else {
      el.resultEyebrow.textContent = "Sefer Başarısız";
      el.resultTitle.textContent = "Bu Sefer Olmadı";
      el.resultDetail.textContent = "Yanlış cevap ya da süre doldu. Tekrar deneyebilirsin.";
    }
  } else {
    el.resultEyebrow.textContent = "Bağlantı Hatası";
    el.resultTitle.textContent = "Sunucuya Ulaşılamadı";
    el.resultDetail.textContent = "Lütfen tekrar dene.";
  }

  el.resultModal.classList.remove("hidden");
}

// ---------- Cevap işleme — 2 KİŞİLİK ----------
function handleAnswerDuo(chosenKey) {
  state.answered = true;
  state.lastChosenKey = chosenKey;
  clearInterval(state.timerInterval);

  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => b.classList.add("disabled"));

  state.socket.emit("submit_answer", {
    code: state.roomCode,
    username: state.username,
    event_id: state.activeEvent.id,
    question_id: state.currentQuestion.id,
    chosen: chosenKey,
  });
}

function finishDuoEvent(correct, correctOption, goldReward) {
  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => {
    b.classList.add("disabled");
    if (b.dataset.key === correctOption) b.classList.add("correct");
    else if (b.dataset.key === state.lastChosenKey) b.classList.add("wrong");
  });

  el.quizFeedback.classList.remove("hidden", "win", "lose");
  if (correct) {
    state.gold += goldReward;
    el.quizFeedback.textContent = `Fetih tamam! +${goldReward} akınca kazandın.`;
    el.quizFeedback.classList.add("win");
  } else {
    el.quizFeedback.textContent = state.lastChosenKey
      ? "Yanlış cevap. Bu olay tekrar herkese açıldı."
      : "Süre doldu. Bu olay tekrar herkese açıldı.";
    el.quizFeedback.classList.add("lose");
  }

  updateStatsUI();
  updateDuoStatsUI();
  state.currentQuestion = null;

  setTimeout(() => {
    el.quizModal.classList.add("hidden");
    refreshMap();
  }, 1600);
}

// ---------- İstatistikler ----------
function updateStatsUI() {
  el.goldCount.textContent = state.gold;
  el.conquerCount.textContent = state.conqueredCount;
}

function updateDuoStatsUI() {
  const mine = [...state.duoEvents.values()].filter((e) => e.state === "conquered" && e.owner === state.username).length;
  const enemy = [...state.duoEvents.values()].filter((e) => e.state === "conquered" && e.owner === state.opponentUsername).length;
  el.goldCount.textContent = state.gold;
  el.conquerCount.textContent = mine;
  el.enemyConquerCount.textContent = enemy;
}
