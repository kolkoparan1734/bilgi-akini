// ============================================
// BİLGİ AKINI — oyun mantığı
// ============================================

// Sayfa hangi adresten açıldıysa (localhost, LAN IP, gerçek domain...) backend'e
// aynı host üzerinden bağlanır — telefon/başka cihazdan LAN IP ile açınca da çalışsın diye.
const API_HOST = window.location.hostname;
const API_BASE = `http://${API_HOST}:5000/api`; // Deploy edince gerekirse backend portunu/host'unu güncelle
const SOCKET_BASE = `http://${API_HOST}:5000`; // Socket.IO aynı sunucuya bağlanır
const QUESTION_TIME = 15; // saniye

const state = {
  username: null,
  mode: null, // "solo" | "duo"
  regions: [],
  gold: 0,
  conqueredCount: 0,
  activeRegion: null,
  activeQuestion: null,
  timerInterval: null,
  timeLeft: QUESTION_TIME,
  answered: false,
  lastChosenKey: null,
  // 2 kişilik mod
  socket: null,
  roomCode: null,
  opponentUsername: null,
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
  mapHint: document.getElementById("map-hint"),
  goldCount: document.getElementById("gold-count"),
  conquerCount: document.getElementById("conquer-count"),
  conquerTotal: document.getElementById("conquer-total"),
  enemyStat: document.querySelector(".enemy-stat"),
  enemyConquerCount: document.getElementById("enemy-conquer-count"),
  enemyName: document.getElementById("enemy-name"),
  quizModal: document.getElementById("quiz-modal"),
  quizRegionName: document.getElementById("quiz-region-name"),
  quizText: document.getElementById("quiz-text"),
  quizOptions: document.getElementById("quiz-options"),
  quizFeedback: document.getElementById("quiz-feedback"),
  timerFill: document.getElementById("timer-fill"),
  victoryModal: document.getElementById("victory-modal"),
  victoryGold: document.getElementById("victory-gold"),
  restartBtn: document.getElementById("restart-btn"),
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
el.restartBtn.addEventListener("click", () => window.location.reload());
el.matchRestartBtn.addEventListener("click", () => window.location.reload());
el.opponentLeftBtn.addEventListener("click", () => window.location.reload());

// Safari'nin gizli sekmesi gibi ortamlarda localStorage.setItem sessizce hata
// fırlatabilir (quota=0) — oyunun tamamen durmaması için try/catch ile sarılıyor.
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

async function handleStart() {
  const username = el.usernameInput.value.trim();
  if (!username) {
    el.usernameInput.focus();
    return;
  }
  state.username = username;
  safeStorageSet("bilgi_akini_user", username);

  try {
    const playerRes = await fetch(`${API_BASE}/player/${encodeURIComponent(username)}`);
    const player = await playerRes.json();
    state.gold = player.gold;
    state.conqueredCount = player.conquered_count;
    updateStatsUI();

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
  el.mapHint.textContent = "Bir bölgeye dokun, soruyu bil, fethet.";
  el.enemyStat.classList.add("hidden");
  el.conquerTotal.textContent = "/8";
  await loadRegions();
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

  socket.on("match_start", (data) => {
    state.roomCode = data.code;
    state.opponentUsername = data.players.find((p) => p !== state.username) || null;
    state.regions = data.regions;

    el.roomScreen.classList.add("hidden");
    el.mapScreen.classList.remove("hidden");
    el.enemyStat.classList.remove("hidden");
    el.enemyName.textContent = state.opponentUsername || "";
    el.mapHint.textContent = "Bölgelere saldır, rakibinden önce fethet!";
    el.conquerTotal.textContent = "/" + state.regions.length;

    renderMap();
    updateDuoStatsUI();
  });

  socket.on("region_locked", ({ region_id, by }) => {
    const region = state.regions.find((r) => r.id === region_id);
    if (region) {
      region.state = "locked";
      region.owner = by;
    }
    if (by !== state.username) {
      renderMap();
    }
  });

  socket.on("question_ready", (data) => {
    state.activeQuestion = { id: data.question_id, text: data.text, options: data.options };
    renderQuestion(state.activeQuestion);
    startTimer();
  });

  socket.on("attack_denied", ({ region_id }) => {
    if (state.activeRegion && state.activeRegion.id === region_id) {
      el.quizModal.classList.add("hidden");
    }
  });

  socket.on("region_result", (data) => {
    const { region_id, correct, owner, gold_reward, correct_option, by } = data;
    const region = state.regions.find((r) => r.id === region_id);
    if (region) {
      region.state = correct ? "conquered" : "available";
      region.owner = correct ? owner : null;
    }

    const iAmAnswerer = by === state.username;
    if (iAmAnswerer && state.activeRegion && state.activeRegion.id === region_id) {
      finishDuoAnswer(correct, correct_option, gold_reward);
    } else {
      renderMap();
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

// ---------- Harita (tek kişilik) ----------
async function loadRegions() {
  const res = await fetch(`${API_BASE}/regions?username=${encodeURIComponent(state.username)}`);
  state.regions = await res.json();
  renderMap();
  checkVictory();
}

function renderMap() {
  el.map.innerHTML = "";
  state.regions.forEach((region) => {
    const btn = document.createElement("button");
    const flag = document.createElement("div");
    flag.className = "region-flag";
    const label = document.createElement("div");
    label.className = "region-label";
    label.textContent = region.name;

    let statusClass = "";
    let flagContent = difficultyIcon(region.difficulty);
    let clickable = true;
    let ariaExtra = "";

    if (state.mode === "duo") {
      if (region.state === "conquered") {
        const mine = region.owner === state.username;
        statusClass = mine ? " conquered" : " enemy";
        flagContent = "⚑";
        clickable = false;
        ariaExtra = mine ? " (fethedildi)" : " (rakipte)";
      } else if (region.state === "locked") {
        statusClass = " locked";
        flagContent = "⏳";
        clickable = false;
        ariaExtra = " (kilitli)";
      }
    } else if (region.conquered) {
      statusClass = " conquered";
      flagContent = "⚑";
      clickable = false;
      ariaExtra = " (fethedildi)";
    }

    btn.className = "region-marker" + statusClass;
    btn.style.left = region.x + "%";
    btn.style.top = region.y + "%";
    btn.setAttribute("aria-label", region.name + ariaExtra);
    flag.textContent = flagContent;

    btn.appendChild(flag);
    btn.appendChild(label);
    if (clickable) {
      btn.addEventListener("click", () => openQuiz(region));
    }
    el.map.appendChild(btn);
  });
}

function difficultyIcon(difficulty) {
  if (difficulty === "zor") return "◆";
  if (difficulty === "normal") return "●";
  return "○";
}

function updateStatsUI() {
  el.goldCount.textContent = state.gold;
  el.conquerCount.textContent = state.conqueredCount;
}

function updateDuoStatsUI() {
  const mine = state.regions.filter((r) => r.state === "conquered" && r.owner === state.username).length;
  const enemy = state.regions.filter((r) => r.state === "conquered" && r.owner === state.opponentUsername).length;
  el.goldCount.textContent = state.gold;
  el.conquerCount.textContent = mine;
  el.enemyConquerCount.textContent = enemy;
}

// ---------- Soru akışı (ortak) ----------
async function openQuiz(region) {
  if (state.mode === "duo") {
    if (region.state !== "available") return;
  } else if (region.conquered) {
    return;
  }

  state.activeRegion = region;
  state.answered = false;
  state.lastChosenKey = null;
  el.quizFeedback.classList.add("hidden");
  el.quizRegionName.textContent = region.name;
  el.quizText.textContent = "Soru yükleniyor...";
  el.quizOptions.innerHTML = "";

  el.quizModal.classList.remove("hidden");

  if (state.mode === "duo") {
    state.socket.emit("attack_region", {
      code: state.roomCode,
      username: state.username,
      region_id: region.id,
    });
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/regions/${region.id}/question?username=${encodeURIComponent(state.username)}`);
    if (!res.ok) throw new Error("Soru alınamadı");
    const question = await res.json();
    state.activeQuestion = question;
    renderQuestion(question);
    startTimer();
  } catch (err) {
    el.quizText.textContent = "Bu bölge için soru bulunamadı.";
  }
}

function renderQuestion(question) {
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
      if (!state.answered) handleAnswer(null); // süre doldu, cevapsız say
    }
  }, 200);
}

function handleAnswer(chosenKey) {
  if (state.answered) return;
  if (state.mode === "duo") {
    handleAnswerDuo(chosenKey);
  } else {
    handleAnswerSolo(chosenKey);
  }
}

async function handleAnswerSolo(chosenKey) {
  state.answered = true;
  clearInterval(state.timerInterval);

  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => b.classList.add("disabled"));

  let result;
  try {
    const res = await fetch(`${API_BASE}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: state.username,
        question_id: state.activeQuestion.id,
        region_id: state.activeRegion.id,
        chosen: chosenKey,
      }),
    });
    result = await res.json();
  } catch (err) {
    el.quizFeedback.textContent = "Bağlantı hatası, tekrar dene.";
    el.quizFeedback.classList.remove("hidden", "win", "lose");
    el.quizFeedback.classList.add("lose");
    return;
  }

  // doğru/yanlış görsel geri bildirim
  buttons.forEach((b) => {
    if (b.dataset.key === result.correct_option) b.classList.add("correct");
    else if (b.dataset.key === chosenKey) b.classList.add("wrong");
  });

  el.quizFeedback.classList.remove("hidden", "win", "lose");
  if (result.correct) {
    el.quizFeedback.textContent = `Fetih tamam! +${state.activeRegion.gold_reward} akınca kazandın.`;
    el.quizFeedback.classList.add("win");
  } else {
    el.quizFeedback.textContent = chosenKey
      ? "Yanlış cevap. Bölge elden gitti, akıncı kaybı yaşandı."
      : "Süre doldu. Bölge fethedilemedi.";
    el.quizFeedback.classList.add("lose");
  }

  state.gold = result.gold;
  state.conqueredCount = result.conquered_count;
  updateStatsUI();

  setTimeout(async () => {
    el.quizModal.classList.add("hidden");
    await loadRegions();
  }, 1600);
}

function handleAnswerDuo(chosenKey) {
  state.answered = true;
  state.lastChosenKey = chosenKey;
  clearInterval(state.timerInterval);

  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => b.classList.add("disabled"));

  state.socket.emit("submit_answer", {
    code: state.roomCode,
    username: state.username,
    region_id: state.activeRegion.id,
    question_id: state.activeQuestion.id,
    chosen: chosenKey,
  });
}

function finishDuoAnswer(correct, correctOption, goldReward) {
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
      ? "Yanlış cevap. Bölge tekrar herkese açıldı."
      : "Süre doldu. Bölge tekrar herkese açıldı.";
    el.quizFeedback.classList.add("lose");
  }

  updateDuoStatsUI();

  setTimeout(() => {
    el.quizModal.classList.add("hidden");
    renderMap();
  }, 1600);
}

// ---------- Zafer (tek kişilik) ----------
function checkVictory() {
  if (state.mode === "solo" && state.regions.length > 0 && state.regions.every((r) => r.conquered)) {
    el.victoryGold.textContent = state.gold;
    el.victoryModal.classList.remove("hidden");
  }
}
