// ============================================
// BİLGİ AKINI — oyun mantığı (dünya haritası + 2 kişilik mod)
// ============================================

// Sunucu adresi: config.js'te elle verilmişse o (Capacitor), yoksa sayfanın
// açıldığı sunucu (Flask frontend'i de servis ediyor). Eski usul 5500
// portundan açılırsa API'yi aynı makinenin 5000 portunda ara.
function resolveServer() {
  if (window.BILGI_AKINI_SERVER) return window.BILGI_AKINI_SERVER.replace(/\/$/, "");
  const loc = window.location;
  if (!loc.protocol.startsWith("http")) return "http://localhost:5000";
  if (loc.port === "5500") return `${loc.protocol}//${loc.hostname}:5000`;
  return loc.origin;
}
const SERVER = resolveServer();
const API_BASE = `${SERVER}/api`;
const SOCKET_BASE = SERVER;
const QUESTION_TIME = 15; // saniye

// ---------- Kumandanlar (karakter seçimi — sadece kozmetik) ----------
// key değerleri backend'deki ALLOWED_CHARACTERS ile birebir eşleşmeli.
// portrait: assets/characters/ altına konacak dosya adı. Dosya henüz yoksa
// (404) otomatik olarak icon (emoji) rozetine düşer — bkz. applyPortrait().
const CHARACTERS = [
  { key: "mete_han", name: "Mete Han", title: "Büyük Hun Hakanı", icon: "🏹", theme: "theme-gold", portrait: "mete_han.webp" },
  { key: "attila", name: "Attila", title: "Hunların Batı Hükümdarı", icon: "🐎", theme: "theme-red", portrait: "attila.webp" },
  { key: "cengiz_han", name: "Cengiz Han", title: "Moğol İmparatorluğu Kurucusu", icon: "🐺", theme: "theme-purple", portrait: "cengiz_han.webp" },
  { key: "timur", name: "Timur", title: "Türk-Moğol Fatihi", icon: "⚔", theme: "theme-teal", portrait: "timur.webp" },
  { key: "iskender", name: "Büyük İskender", title: "Makedonya Kralı", icon: "🛡", theme: "theme-gold", portrait: "iskender.webp" },
  { key: "jul_sezar", name: "Jül Sezar", title: "Roma Cumhuriyeti Generali", icon: "🦅", theme: "theme-red", portrait: "jul_sezar.webp" },
  { key: "fatih", name: "Fatih Sultan Mehmed", title: "Osmanlı Padişahı", icon: "🏰", theme: "theme-purple", portrait: "fatih.webp" },
  { key: "napolyon", name: "Napolyon Bonapart", title: "Fransız İmparatoru", icon: "🎖", theme: "theme-teal", portrait: "napolyon.webp" },
];
function findCharacter(key) {
  return CHARACTERS.find((c) => c.key === key) || null;
}

// Bir .character-icon kabına portre görselini koymaya çalışır; görsel dosyası
// henüz eklenmediyse (404) ya da yüklenemezse emoji rozete geri döner.
function applyPortrait(container, char) {
  container.textContent = "";
  if (!char.portrait) {
    container.textContent = char.icon;
    return;
  }
  const img = document.createElement("img");
  img.className = "character-portrait";
  img.alt = char.name;
  img.onerror = () => {
    container.textContent = char.icon;
  };
  img.src = "assets/characters/" + char.portrait;
  container.appendChild(img);
}

const state = {
  username: null,
  character: null, // seçilen kumandanın key'i (kozmetik)
  opponentCharacter: null,
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
  characterScreen: document.getElementById("character-screen"),
  characterGrid: document.getElementById("character-grid"),
  characterStat: document.getElementById("character-stat"),
  characterBadgeIcon: document.getElementById("character-badge-icon"),
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

  serverError: document.getElementById("server-error"),
  serverErrorText: document.getElementById("server-error-text"),
  serverRetryBtn: document.getElementById("server-retry-btn"),
  connBanner: document.getElementById("conn-banner"),
  characterBackBtn: document.getElementById("character-back-btn"),
  modeBackBtn: document.getElementById("mode-back-btn"),
  roomBackBtn: document.getElementById("room-back-btn"),

  musicToggleBtn: document.getElementById("music-toggle-btn"),
  musicIcon: document.getElementById("music-icon"),
};

// ---------- Fon müziği (Web Audio API ile anlık üretilen savaş temposu) ----------
// Telifli/harici bir müzik dosyasına ihtiyaç duymadan, tarayıcıda basit bir
// davul+boru döngüsü sentezler. Tarayıcıların otomatik oynatma kısıtı
// yüzünden ilk kullanıcı dokunuşunda (Sefere Başla) başlatılır.
const music = {
  ctx: null,
  muted: safeStorageGet("bilgi_akini_music_muted") === "1",
  playing: false,
  nextNoteTime: 0,
  beat: 0,
  schedulerTimer: null,
};

const MUSIC_TEMPO = 92; // BPM — ağır bir savaş yürüyüşü temposu
const MUSIC_BEAT = 60 / MUSIC_TEMPO;
const MUSIC_SCHEDULE_AHEAD = 0.25; // saniye
const MUSIC_LOOKAHEAD_MS = 60;

function playTone(time, { freq, endFreq, duration, gain, type }) {
  if (music.muted) return;
  const ctx = music.ctx;
  const osc = ctx.createOscillator();
  const gainNode = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, time);
  if (endFreq) osc.frequency.exponentialRampToValueAtTime(endFreq, time + duration);
  gainNode.gain.setValueAtTime(0.0001, time);
  gainNode.gain.exponentialRampToValueAtTime(gain, time + 0.02);
  gainNode.gain.exponentialRampToValueAtTime(0.0001, time + duration);
  osc.connect(gainNode).connect(ctx.destination);
  osc.start(time);
  osc.stop(time + duration + 0.05);
}

function scheduleMusic() {
  const ctx = music.ctx;
  while (music.nextNoteTime < ctx.currentTime + MUSIC_SCHEDULE_AHEAD) {
    const step = music.beat % 8;
    const t = music.nextNoteTime;
    // ağır davul: her vuruşta
    playTone(t, { freq: 90, endFreq: 42, duration: 0.28, gain: 0.22, type: "sine" });
    // aksan davulu: ölçünün başında daha güçlü
    if (step === 0 || step === 4) {
      playTone(t, { freq: 65, endFreq: 34, duration: 0.4, gain: 0.28, type: "sine" });
    }
    // uzak boru/drone: her iki ölçüde bir, atmosfer için
    if (step === 2 && music.beat % 16 === 2) {
      playTone(t, { freq: 110, duration: MUSIC_BEAT * 3, gain: 0.045, type: "sawtooth" });
    }
    music.nextNoteTime += MUSIC_BEAT;
    music.beat++;
  }
  music.schedulerTimer = setTimeout(scheduleMusic, MUSIC_LOOKAHEAD_MS);
}

function startMusic() {
  if (music.playing) return;
  try {
    if (!music.ctx) {
      music.ctx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (music.ctx.state === "suspended") music.ctx.resume();
    music.playing = true;
    music.nextNoteTime = music.ctx.currentTime + 0.1;
    music.beat = 0;
    scheduleMusic();
  } catch (err) {
    /* Web Audio API desteklenmiyor — sessizce oyuna devam */
  }
  updateMusicButtonUI();
}

function toggleMusic() {
  music.muted = !music.muted;
  safeStorageSet("bilgi_akini_music_muted", music.muted ? "1" : "0");
  if (!music.muted && !music.playing) startMusic();
  updateMusicButtonUI();
}

function updateMusicButtonUI() {
  el.musicIcon.textContent = music.muted ? "🔇" : "🔊";
  el.musicToggleBtn.classList.toggle("muted", music.muted);
}

el.musicToggleBtn.addEventListener("click", toggleMusic);
updateMusicButtonUI();

// ---------- Ses efektleri (aynı Web Audio API altyapısı, müzikle aynı sesi paylaşır) ----------
function playSfxClick() {
  if (!music.ctx) return;
  playTone(music.ctx.currentTime, { freq: 700, duration: 0.05, gain: 0.08, type: "square" });
}

function playSfxCorrect() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  playTone(t, { freq: 523.25, duration: 0.12, gain: 0.18, type: "triangle" });
  playTone(t + 0.09, { freq: 783.99, duration: 0.18, gain: 0.18, type: "triangle" });
}

function playSfxWrong() {
  if (!music.ctx) return;
  playTone(music.ctx.currentTime, { freq: 180, endFreq: 90, duration: 0.28, gain: 0.22, type: "sawtooth" });
}

function playSfxConquer() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  [523.25, 659.25, 783.99, 1046.5].forEach((freq, i) => {
    playTone(t + i * 0.11, { freq, duration: 0.28, gain: 0.2, type: "triangle" });
  });
}

// Osmanlı/Türkiye fethedildiğinde çalan, mehter esintili kısa bir ezgi.
// Telifli bir kayıt kullanmıyoruz — zurna+davul hissi veren kendi sentezimiz.
function playMehterFanfare() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  const noteDur = 0.16;
  const melody = [392.00, 392.00, 440.00, 466.16, 440.00, 392.00, 349.23, 392.00]; // G4 G4 A4 Bb4 A4 G4 F4 G4
  melody.forEach((freq, i) => {
    const nt = t + i * noteDur;
    playTone(nt, { freq, duration: noteDur * 0.95, gain: 0.22, type: "sawtooth" }); // zurna hissi
    playTone(nt, { freq: 75, endFreq: 38, duration: noteDur * 0.7, gain: 0.2, type: "sine" }); // davul
  });
  const end = t + melody.length * noteDur;
  playTone(end, { freq: 523.25, duration: 0.4, gain: 0.26, type: "sawtooth" });
  playTone(end, { freq: 60, endFreq: 30, duration: 0.5, gain: 0.3, type: "sine" });
  playTone(end, { freq: 3200, duration: 0.3, gain: 0.05, type: "triangle" }); // zil parıltısı
}

function playConquestCelebration(country) {
  if (country && country.key === "turkiye") playMehterFanfare();
  else playSfxConquer();
}

// ---------- Konfeti (fetih kutlaması) ----------
const CONFETTI_COLORS = ["#ef413a", "#f5d38a", "#6f4c9e", "#3fbd73", "#3b91b2", "#ffffff"];

function spawnConfetti(count = 26) {
  const appEl = document.getElementById("app");
  for (let i = 0; i < count; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = Math.random() * 100 + "%";
    piece.style.background = CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)];
    piece.style.width = (6 + Math.random() * 5) + "px";
    piece.style.height = (10 + Math.random() * 8) + "px";
    piece.style.animationDuration = (1.6 + Math.random() * 1.2) + "s";
    piece.style.animationDelay = (Math.random() * 0.3) + "s";
    piece.addEventListener("animationend", () => piece.remove());
    appEl.appendChild(piece);
  }
}

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ---------- Sayaç animasyonu (altın/fetih sayısı akıp değişsin diye) ----------
function animateNumber(target, to) {
  const from = parseInt(target.textContent, 10) || 0;
  if (from === to) return;
  const duration = 500;
  const start = performance.now();
  function step(now) {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    target.textContent = Math.round(from + (to - from) * eased);
    if (progress < 1) requestAnimationFrame(step);
    else target.textContent = to;
  }
  requestAnimationFrame(step);
}

// ---------- Sunucu iletişimi ----------
// Tüm HTTP istekleri buradan geçer: zaman aşımı, hata durumunda anlaşılır
// "Sunucuya bağlanılamadı" ekranı. Hata yine fırlatılır ki çağıran akış dursun.
const API_TIMEOUT_MS = 8000;

async function api(path, { method = "GET", body } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    showServerError();
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function showServerError(text) {
  el.serverErrorText.textContent = text || "Oyun sunucusu çalışmıyor ya da bu cihaz ona ulaşamıyor.";
  el.serverError.classList.remove("hidden");
}

async function checkServer() {
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    if (!res.ok) throw new Error();
    el.serverError.classList.add("hidden");
    return true;
  } catch (err) {
    showServerError("Sunucu başlatılamadı ya da bu cihaz ona ulaşamıyor.");
    return false;
  }
}

el.serverRetryBtn.addEventListener("click", async () => {
  el.serverRetryBtn.disabled = true;
  el.serverRetryBtn.textContent = "Bağlanıyor…";
  await checkServer();
  el.serverRetryBtn.disabled = false;
  el.serverRetryBtn.textContent = "Tekrar Dene";
});
checkServer();

// ---------- Başlangıç ----------
el.startBtn.addEventListener("click", handleStart);
el.usernameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") handleStart();
});
el.eventSelectClose.addEventListener("click", () => {
  playSfxClick();
  el.eventSelectModal.classList.add("hidden");
});
el.emptyCloseBtn.addEventListener("click", () => {
  playSfxClick();
  el.emptyModal.classList.add("hidden");
});
el.resultCloseBtn.addEventListener("click", () => {
  playSfxClick();
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
  startMusic();
  playSfxClick();
  state.username = username;
  safeStorageSet("bilgi_akini_user", username);

  try {
    const player = await api(`/player/${encodeURIComponent(username)}`);
    state.gold = player.gold;
    state.conqueredCount = player.conquered_count;
    state.character = player.character_key || null;
    updateStatsUI();
    updateCharacterBadgeUI();

    state.eras = await api("/eras");
    state.currentEra = (state.eras.find((e) => e.key === "yukselis") || state.eras[0]).key;

    el.loginScreen.classList.add("hidden");
    el.characterScreen.classList.remove("hidden");
    renderCharacterGrid();
  } catch (err) {
    /* api() bağlantı hatası ekranını zaten gösterdi */
  }
}

// ---------- Kumandan seçimi ----------
function renderCharacterGrid() {
  el.characterGrid.innerHTML = "";
  CHARACTERS.forEach((char) => {
    const btn = document.createElement("button");
    btn.className = "character-card" + (state.character === char.key ? " selected" : "");
    btn.setAttribute("aria-label", char.name + " — " + char.title);

    const icon = document.createElement("div");
    icon.className = "character-icon " + char.theme;
    applyPortrait(icon, char);

    const name = document.createElement("div");
    name.className = "character-name";
    name.textContent = char.name;

    const title = document.createElement("div");
    title.className = "character-title";
    title.textContent = char.title;

    btn.appendChild(icon);
    btn.appendChild(name);
    btn.appendChild(title);
    btn.addEventListener("click", () => selectCharacter(char));
    el.characterGrid.appendChild(btn);
  });
}

async function selectCharacter(char) {
  playSfxClick();
  state.character = char.key;
  updateCharacterBadgeUI();

  try {
    await fetch(`${API_BASE}/player/${encodeURIComponent(state.username)}/character`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ character_key: char.key }),
    });
  } catch (err) {
    /* kozmetik bir tercih — kaydedilemese bile sefere devam et */
  }

  el.characterScreen.classList.add("hidden");
  el.modeScreen.classList.remove("hidden");
}

function updateCharacterBadgeUI() {
  const char = findCharacter(state.character);
  if (!char) {
    el.characterStat.classList.add("hidden");
    return;
  }
  applyPortrait(el.characterBadgeIcon, char);
  el.characterStat.title = char.name;
  el.characterStat.classList.remove("hidden");
}

// ---------- Geri butonları ----------
el.characterBackBtn.addEventListener("click", () => {
  playSfxClick();
  el.characterScreen.classList.add("hidden");
  el.loginScreen.classList.remove("hidden");
});
el.modeBackBtn.addEventListener("click", () => {
  playSfxClick();
  el.modeScreen.classList.add("hidden");
  el.characterScreen.classList.remove("hidden");
  renderCharacterGrid();
});
el.roomBackBtn.addEventListener("click", () => {
  playSfxClick();
  leaveRoom();
  el.roomScreen.classList.add("hidden");
  el.modeScreen.classList.remove("hidden");
});

// Bekleyen odadan çık: soketi kapatmak sunucuda odayı da siler.
function leaveRoom() {
  if (state.socket) {
    const socket = state.socket;
    state.socket = null;
    socket.disconnect();
  }
  state.roomCode = null;
  el.connBanner.classList.add("hidden");
}

// ---------- Mod seçimi ----------
el.soloModeBtn.addEventListener("click", async () => {
  playSfxClick();
  state.mode = "solo";
  el.modeScreen.classList.add("hidden");
  el.mapScreen.classList.remove("hidden");
  el.mapHint.textContent = "Bir ülkeye dokun, tarihi olayı fethet.";
  el.enemyStat.classList.add("hidden");
  renderEraTabs();
  await loadCountries();
});

el.duoModeBtn.addEventListener("click", () => {
  playSfxClick();
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
  playSfxClick();
  el.roomError.classList.add("hidden");
  state.socket.emit("create_room", { username: state.username });
});

el.joinRoomBtn.addEventListener("click", () => {
  playSfxClick();
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
  const socket = io(SOCKET_BASE, { reconnectionDelayMax: 3000 });
  state.socket = socket;

  socket.on("connect", () => el.connBanner.classList.add("hidden"));
  socket.on("disconnect", () => {
    if (state.socket === socket) el.connBanner.classList.remove("hidden");
  });
  socket.on("connect_error", () => {
    if (!state.roomCode) {
      el.roomError.textContent = "Sunucuya bağlanılamadı. start.bat açık mı, aynı Wi-Fi'da mısınız?";
      el.roomError.classList.remove("hidden");
    } else {
      el.connBanner.classList.remove("hidden");
    }
  });

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
    const opponentCharKey = (data.characters || {})[state.opponentUsername] || null;
    state.opponentCharacter = opponentCharKey;

    if (!state.countriesRaw) {
      state.countriesRaw = await api("/countries/all");
    }
    state.duoEvents = new Map(data.events.map((e) => [e.id, e]));

    el.roomScreen.classList.add("hidden");
    el.mapScreen.classList.remove("hidden");
    el.enemyStat.classList.remove("hidden");
    const opponentChar = findCharacter(opponentCharKey);
    el.enemyName.textContent = (opponentChar ? opponentChar.icon + " " : "") + (state.opponentUsername || "");
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
      playSfxCorrect();
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
      playSfxClick();
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
  state.countries = await api(
    `/countries?era=${encodeURIComponent(state.currentEra)}&username=${encodeURIComponent(state.username)}`
  );
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
      btn.addEventListener("click", () => {
        playSfxClick();
        openCountry(country);
      });
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
    events = await api(
      `/countries/${country.id}/events?era=${encodeURIComponent(state.currentEra)}&username=${encodeURIComponent(state.username)}`
    );
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
  const event = await api(`/events/${eventSummary.id}?username=${encodeURIComponent(state.username)}`);

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

  // Gösterim sırası karıştırılır; cevap harf anahtarıyla (a-d) kontrol
  // edildiği için doğru cevap değişmez.
  shuffle(Object.entries(question.options)).forEach(([key, label]) => {
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
    check = await api(`/questions/${question.id}/check`, { method: "POST", body: { chosen: chosenKey } });
  } catch (err) {
    check = { correct: false, correct_option: null };
  }

  buttons.forEach((b) => {
    if (b.dataset.key === check.correct_option) b.classList.add("correct");
    else if (b.dataset.key === chosenKey) b.classList.add("wrong");
  });
  if (check.correct) playSfxCorrect();
  else playSfxWrong();

  const isLast = state.qIndex === event.questions.length - 1;

  setTimeout(() => {
    if (!check.correct || isLast) {
      finishSoloEvent();
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
    result = await api(`/events/${event.id}/answer`, {
      method: "POST",
      body: { username: state.username, answers: state.answers },
    });
  } catch (err) {
    result = null;
  }

  el.quizModal.classList.add("hidden");

  const resultCard = el.resultModal.querySelector(".quiz-card");
  resultCard.classList.remove("celebrate");

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
      if (!result.already_conquered) {
        resultCard.classList.add("celebrate");
        playConquestCelebration(state.activeCountry);
        spawnConfetti();
      }
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
    playConquestCelebration(state.activeCountry);
    spawnConfetti();
  } else {
    el.quizFeedback.textContent = state.lastChosenKey
      ? "Yanlış cevap. Bu olay tekrar herkese açıldı."
      : "Süre doldu. Bu olay tekrar herkese açıldı.";
    el.quizFeedback.classList.add("lose");
    playSfxWrong();
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
  animateNumber(el.goldCount, state.gold);
  animateNumber(el.conquerCount, state.conqueredCount);
}

function updateDuoStatsUI() {
  const mine = [...state.duoEvents.values()].filter((e) => e.state === "conquered" && e.owner === state.username).length;
  const enemy = [...state.duoEvents.values()].filter((e) => e.state === "conquered" && e.owner === state.opponentUsername).length;
  animateNumber(el.goldCount, state.gold);
  animateNumber(el.conquerCount, mine);
  animateNumber(el.enemyConquerCount, enemy);
}
