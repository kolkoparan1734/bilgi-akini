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
const WARN_SECONDS = 5; // süre çubuğu bu kadar saniye kala kırmızıya döner
// Bonus kuralları backend'deki speed_bonus/streak_bonus ile aynı (burada
// sadece anlık "+7 hız" baloncuğunu göstermek için kullanılır).
const SPEED_BONUS_MAX = 10;
const STREAK_MIN = 3;

// ---------- Kumandanlar (karakter seçimi — sadece kozmetik) ----------
// key değerleri backend'deki ALLOWED_CHARACTERS ile birebir eşleşmeli.
// portrait: assets/characters/ altındaki dosya adı. Dosya yoksa (404)
// otomatik olarak icon (emoji) rozetine düşer — bkz. applyPortrait().
// cry: seçilince ekranda beliren oyun içi savaş sözü.
const CHARACTERS = [
  { key: "mete_han", name: "Mete Han", title: "Büyük Hun Hakanı", icon: "🏹", theme: "theme-gold", portrait: "mete_han.webp",
    cry: "Atlarımız durmaz, oklarımız şaşmaz!" },
  { key: "attila", name: "Attila", title: "Hunların Batı Hükümdarı", icon: "🐎", theme: "theme-red", portrait: "attila.webp",
    cry: "Bozkırın fırtınası geliyor!" },
  { key: "cengiz_han", name: "Cengiz Han", title: "Moğol İmparatorluğu Kurucusu", icon: "🐺", theme: "theme-purple", portrait: "cengiz_han.webp",
    cry: "Ufuk neredeyse, sınırımız orası!" },
  { key: "timur", name: "Timur", title: "Türk-Moğol Fatihi", icon: "⚔", theme: "theme-teal", portrait: "timur.webp",
    cry: "Kılıcım keskin, aklım daha keskin!" },
  { key: "iskender", name: "Büyük İskender", title: "Makedonya Kralı", icon: "🛡", theme: "theme-gold", portrait: "iskender.webp",
    cry: "Dünyanın sonuna kadar ileri!" },
  { key: "jul_sezar", name: "Jül Sezar", title: "Roma Cumhuriyeti Generali", icon: "🦅", theme: "theme-red", portrait: "jul_sezar.webp",
    cry: "Geldim, gördüm, yendim!" },
  { key: "fatih", name: "Fatih Sultan Mehmed", title: "Osmanlı Padişahı", icon: "🏰", theme: "theme-purple", portrait: "fatih.webp",
    cry: "Ya ben onu alırım, ya o beni!" },
  { key: "napolyon", name: "Napolyon Bonapart", title: "Fransız İmparatoru", icon: "🎖", theme: "theme-teal", portrait: "napolyon.webp",
    cry: "İmkânsız kelimesi benim sözlüğümde yok!" },
];
// style.css'teki --cmd-* renkleriyle aynı (haritada fetih rengi, konfeti)
const THEME_COLORS = {
  "theme-gold": "#d29a2e",
  "theme-red": "#d8352e",
  "theme-purple": "#7550b0",
  "theme-teal": "#2a8fb4",
};
function findCharacter(key) {
  return CHARACTERS.find((c) => c.key === key) || null;
}
function characterColor(key, fallback = THEME_COLORS["theme-red"]) {
  const char = findCharacter(key);
  return char ? THEME_COLORS[char.theme] : fallback;
}

// Haritada kısa etiket ve etiketin rozetin hangi yanında duracağı
// (Avrupa/Orta Doğu kalabalık olduğu için etiketler birbirine binmesin).
const COUNTRY_UI = {
  amerika: { short: "ABD", side: "bottom" },
  meksika: { short: "Meksika", side: "bottom" },
  brezilya: { short: "Brezilya", side: "bottom" },
  fransa: { short: "Fransa", side: "left" },
  almanya: { short: "Almanya", side: "top" },
  turkiye: { short: "Türkiye", side: "top" },
  rusya: { short: "Rusya", side: "bottom" },
  misir: { short: "Mısır", side: "bottom" },
  iran: { short: "İran", side: "right" },
  cin: { short: "Çin", side: "bottom" },
  hindistan: { short: "Hindistan", side: "bottom" },
  japonya: { short: "Japonya", side: "bottom" },
};

// Bir .character-icon kabına portre görselini koymaya çalışır; görsel dosyası
// henüz eklenmediyse (404) ya da yüklenemezse emoji rozete geri döner.
function applyPortrait(container, char) {
  container.textContent = "";
  if (!char) {
    container.textContent = "⚔";
    return;
  }
  if (!char.portrait) {
    container.textContent = char.icon;
    return;
  }
  const img = document.createElement("img");
  img.className = "character-portrait";
  img.alt = char.name;
  img.draggable = false;
  img.onerror = () => {
    container.textContent = char.icon;
  };
  img.src = "assets/characters/" + char.portrait;
  container.appendChild(img);
}

function setPortraitTheme(container, char) {
  container.classList.remove("theme-gold", "theme-red", "theme-purple", "theme-teal");
  if (char) container.classList.add(char.theme);
  applyPortrait(container, char);
}

const state = {
  username: null,
  character: null, // seçilen kumandanın key'i (kozmetik)
  opponentCharacter: null,
  mode: null, // "solo" | "duo"
  eras: [],
  currentEra: null,
  progress: {}, // solo: era_key -> {name, conquered, total}
  countries: [], // ekranda çizilen, hesaplanmış liste (her iki mod da bunu kullanır)
  gold: 0,
  conqueredCount: 0,

  activeCountry: null,
  activeEvent: null, // {id, title, leader, questions?} — solo'da tam liste, duo'da tek soru akışı
  qIndex: 0,
  qTotal: 0,
  currentQuestion: null,
  answers: {}, // solo: question_id -> chosen key
  times: {}, // solo: question_id -> cevap verildiğinde kalan saniye (hız bonusu)
  timerInterval: null,
  timeLeft: QUESTION_TIME,
  answered: false,

  streak: 0, // art arda doğru cevap sayısı (olaylar arasında da sürer)
  streakAtStart: 0,
  justConquered: null, // haritada fetih animasyonu oynatılacak ülke id'si
  pendingEraComplete: null, // "Dönem Fethedildi" ekranı gösterilecek dönem
  battleCryTimer: null,

  // 2 kişilik mod
  socket: null,
  roomCode: null,
  roomEra: null,
  opponentUsername: null,
  countriesRaw: null, // /api/countries/all — dönemden bağımsız ham liste
  duoEvents: new Map(), // event_id -> {id,country_id,era_key,title,leader,gold_reward,state,owner}
  matchEraKey: null,
  matchEndsAt: 0,
  matchTimerInterval: null,
  matchOver: false,
  myColor: THEME_COLORS["theme-red"],
  enemyColor: THEME_COLORS["theme-purple"],
};

// ---------- DOM referansları ----------
const el = {
  app: document.getElementById("app"),
  loginScreen: document.getElementById("login-screen"),
  characterScreen: document.getElementById("character-screen"),
  characterGrid: document.getElementById("character-grid"),
  characterStat: document.getElementById("character-stat"),
  characterBadgeIcon: document.getElementById("character-badge-icon"),
  battleCry: document.getElementById("battle-cry"),
  battleCryPortrait: document.getElementById("battle-cry-portrait"),
  battleCryName: document.getElementById("battle-cry-name"),
  battleCryQuote: document.getElementById("battle-cry-quote"),
  modeScreen: document.getElementById("mode-screen"),
  roomScreen: document.getElementById("room-screen"),
  mapScreen: document.getElementById("map-screen"),
  usernameInput: document.getElementById("username-input"),
  startBtn: document.getElementById("start-btn"),
  soloModeBtn: document.getElementById("solo-mode-btn"),
  duoModeBtn: document.getElementById("duo-mode-btn"),
  modeLeaderboardBtn: document.getElementById("mode-leaderboard-btn"),
  roomIdle: document.getElementById("room-idle"),
  roomWaiting: document.getElementById("room-waiting"),
  eraPicker: document.getElementById("era-picker"),
  createRoomBtn: document.getElementById("create-room-btn"),
  joinCodeInput: document.getElementById("join-code-input"),
  joinRoomBtn: document.getElementById("join-room-btn"),
  roomError: document.getElementById("room-error"),
  roomCodeDisplay: document.getElementById("room-code-display"),
  roomWaitEra: document.getElementById("room-wait-era"),
  roomWaitHint: document.getElementById("room-wait-hint"),
  map: document.getElementById("map"),
  eraTabs: document.getElementById("era-tabs"),
  eraProgress: document.getElementById("era-progress"),
  eraProgressLabel: document.getElementById("era-progress-label"),
  eraProgressCount: document.getElementById("era-progress-count"),
  eraProgressFill: document.getElementById("era-progress-fill"),
  mapHint: document.getElementById("map-hint"),
  mapMenuBtn: document.getElementById("map-menu-btn"),
  goldStat: document.getElementById("gold-stat"),
  goldCount: document.getElementById("gold-count"),
  conquerStat: document.getElementById("conquer-stat"),
  conquerCount: document.getElementById("conquer-count"),
  enemyStat: document.querySelector(".enemy-stat"),
  enemyPortrait: document.getElementById("enemy-portrait"),
  enemyConquerCount: document.getElementById("enemy-conquer-count"),
  enemyName: document.getElementById("enemy-name"),
  matchTimerStat: document.getElementById("match-timer-stat"),
  matchTimer: document.getElementById("match-timer"),
  leaderboardBtn: document.getElementById("leaderboard-btn"),

  eventSelectModal: document.getElementById("event-select-modal"),
  eventSelectCountry: document.getElementById("event-select-country"),
  eventList: document.getElementById("event-list"),
  eventSelectClose: document.getElementById("event-select-close"),

  emptyModal: document.getElementById("empty-modal"),
  emptyCountryName: document.getElementById("empty-country-name"),
  emptyCloseBtn: document.getElementById("empty-close-btn"),

  quizModal: document.getElementById("quiz-modal"),
  quizCard: document.getElementById("quiz-card"),
  quizEventTitle: document.getElementById("quiz-event-title"),
  quizProgress: document.getElementById("quiz-progress"),
  quizText: document.getElementById("quiz-text"),
  quizOptions: document.getElementById("quiz-options"),
  quizFeedback: document.getElementById("quiz-feedback"),
  timerRow: document.querySelector(".timer-row"),
  timerFill: document.getElementById("timer-fill"),
  timerNum: document.getElementById("timer-num"),
  streakBadge: document.getElementById("streak-badge"),
  streakFlash: document.getElementById("streak-flash"),

  resultModal: document.getElementById("result-modal"),
  resultCard: document.getElementById("result-card"),
  resultEyebrow: document.getElementById("result-eyebrow"),
  resultTitle: document.getElementById("result-title"),
  resultDetail: document.getElementById("result-detail"),
  rewardRows: document.getElementById("reward-rows"),
  resultCloseBtn: document.getElementById("result-close-btn"),

  eraModal: document.getElementById("era-modal"),
  eraPortrait: document.getElementById("era-portrait"),
  eraTitle: document.getElementById("era-title"),
  eraDetail: document.getElementById("era-detail"),
  eraCloseBtn: document.getElementById("era-close-btn"),

  leaderboardModal: document.getElementById("leaderboard-modal"),
  leaderboardList: document.getElementById("leaderboard-list"),
  leaderboardCloseBtn: document.getElementById("leaderboard-close-btn"),

  matchOverModal: document.getElementById("match-over-modal"),
  matchOverCard: document.getElementById("match-over-card"),
  matchOverReason: document.getElementById("match-over-reason"),
  matchOverTitle: document.getElementById("match-over-title"),
  matchOverVersus: document.getElementById("match-over-versus"),
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
  noise: null,
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

// Zil/ziller için kısa beyaz gürültü patlaması (yüksek geçiren filtreli).
function playNoise(time, { duration, gain, highpass = 6000 }) {
  if (music.muted) return;
  const ctx = music.ctx;
  if (!music.noise) {
    const buffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    music.noise = buffer;
  }
  const src = ctx.createBufferSource();
  src.buffer = music.noise;
  const filter = ctx.createBiquadFilter();
  filter.type = "highpass";
  filter.frequency.value = highpass;
  const gainNode = ctx.createGain();
  gainNode.gain.setValueAtTime(gain, time);
  gainNode.gain.exponentialRampToValueAtTime(0.0001, time + duration);
  src.connect(filter).connect(gainNode).connect(ctx.destination);
  src.start(time);
  src.stop(time + duration + 0.05);
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

function playSfxTick() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  playTone(t, { freq: 1320, duration: 0.04, gain: 0.12, type: "square" });
  playTone(t + 0.05, { freq: 880, duration: 0.04, gain: 0.06, type: "square" });
}

function playSfxCoin() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  playTone(t, { freq: 1568, duration: 0.06, gain: 0.07, type: "triangle" });
  playTone(t + 0.04, { freq: 2093, duration: 0.09, gain: 0.06, type: "triangle" });
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

function playSfxStreak(level) {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  const base = 523.25 * Math.pow(1.06, Math.min(level - STREAK_MIN, 8));
  [1, 1.25, 1.5, 2].forEach((m, i) => {
    playTone(t + i * 0.06, { freq: base * m, duration: 0.14, gain: 0.12, type: "square" });
  });
}

// Kumandan seçilince: alçaktan yükselen savaş borusu
function playSfxHorn() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  playTone(t, { freq: 146.8, endFreq: 196, duration: 0.5, gain: 0.16, type: "sawtooth" });
  playTone(t + 0.45, { freq: 196, duration: 0.6, gain: 0.16, type: "sawtooth" });
  playTone(t, { freq: 60, endFreq: 30, duration: 0.5, gain: 0.3, type: "sine" });
}

// Haritaya bayrak dikilirken: tok bir vuruş + zil
function playSfxFlag() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  playTone(t, { freq: 110, endFreq: 40, duration: 0.35, gain: 0.32, type: "sine" });
  playNoise(t, { duration: 0.25, gain: 0.08 });
  playTone(t + 0.05, { freq: 1046.5, duration: 0.3, gain: 0.08, type: "triangle" });
}

// Fetih fanfarı: yükselen borular, akor, davul ve zil
function playSfxConquer() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  [523.25, 659.25, 783.99, 1046.5].forEach((freq, i) => {
    playTone(t + i * 0.11, { freq, duration: 0.28, gain: 0.18, type: "triangle" });
    playTone(t + i * 0.11, { freq: freq / 2, duration: 0.2, gain: 0.08, type: "sawtooth" });
  });
  const end = t + 0.46;
  [523.25, 659.25, 783.99].forEach((freq) => {
    playTone(end, { freq, duration: 0.9, gain: 0.12, type: "triangle" });
  });
  playTone(end, { freq: 70, endFreq: 32, duration: 0.6, gain: 0.32, type: "sine" });
  playNoise(end, { duration: 0.9, gain: 0.09 });
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
  playNoise(end, { duration: 0.7, gain: 0.07 });
}

// Dönem fethedildi: daha uzun, törensel bir fanfar
function playSfxEra() {
  if (!music.ctx) return;
  const t = music.ctx.currentTime;
  const notes = [392, 523.25, 659.25, 783.99, 659.25, 783.99, 1046.5];
  notes.forEach((freq, i) => {
    playTone(t + i * 0.14, { freq, duration: 0.3, gain: 0.16, type: "triangle" });
    playTone(t + i * 0.14, { freq: freq / 2, duration: 0.25, gain: 0.07, type: "sawtooth" });
    playTone(t + i * 0.14, { freq: 80, endFreq: 38, duration: 0.2, gain: 0.18, type: "sine" });
  });
  const end = t + notes.length * 0.14;
  [523.25, 659.25, 783.99, 1046.5].forEach((freq) => {
    playTone(end, { freq, duration: 1.6, gain: 0.1, type: "triangle" });
  });
  playTone(end, { freq: 55, endFreq: 28, duration: 1, gain: 0.34, type: "sine" });
  playNoise(end, { duration: 1.4, gain: 0.1 });
}

function playConquestCelebration(country) {
  if (country && country.key === "turkiye") playMehterFanfare();
  else playSfxConquer();
}

// ---------- Titreşim (destekleyen telefonlarda; diğerlerinde sessizce atlanır) ----------
function haptic(pattern) {
  try {
    if (navigator.vibrate) navigator.vibrate(pattern);
  } catch (err) {
    /* desteklenmiyor */
  }
}
const HAPTIC = { tap: 12, correct: 30, wrong: [60, 40, 60], conquer: [40, 30, 40, 30, 120] };

// ---------- Konfeti (fetih kutlaması) ----------
const CONFETTI_COLORS = ["#ef413a", "#f5d38a", "#e0b563", "#6f4c9e", "#3fbd73", "#3b91b2", "#ffffff"];

// Yukarıdan yağan konfeti + ortadan patlayan ikinci dalga. Parça sayısı
// orta seviye telefonlarda akıcı kalacak şekilde sınırlı tutuldu.
function spawnConfetti({ rain = 36, burst = 24, colors = [] } = {}) {
  const appEl = el.app;
  const palette = colors.concat(CONFETTI_COLORS);
  const pick = () => palette[Math.floor(Math.random() * palette.length)];
  for (let i = 0; i < rain; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = Math.random() * 100 + "%";
    piece.style.background = pick();
    piece.style.width = (6 + Math.random() * 6) + "px";
    piece.style.height = (10 + Math.random() * 8) + "px";
    piece.style.setProperty("--dx", (Math.random() * 120 - 60) + "px");
    piece.style.setProperty("--rot", (360 + Math.random() * 540) * (Math.random() < 0.5 ? -1 : 1) + "deg");
    piece.style.animationDuration = (1.8 + Math.random() * 1.4) + "s";
    piece.style.animationDelay = (Math.random() * 0.5) + "s";
    piece.addEventListener("animationend", () => piece.remove());
    appEl.appendChild(piece);
  }
  setTimeout(() => {
    for (let i = 0; i < burst; i++) {
      const piece = document.createElement("div");
      piece.className = "confetti-piece burst";
      piece.style.left = "50%";
      piece.style.top = "45%";
      piece.style.background = pick();
      const angle = Math.random() * Math.PI * 2;
      const dist = 120 + Math.random() * 220;
      piece.style.setProperty("--dx", Math.cos(angle) * dist + "px");
      piece.style.setProperty("--dy", Math.sin(angle) * dist + "px");
      piece.style.setProperty("--rot", (Math.random() * 720 - 360) + "deg");
      piece.style.animationDuration = (0.9 + Math.random() * 0.6) + "s";
      piece.addEventListener("animationend", () => piece.remove());
      appEl.appendChild(piece);
    }
  }, 250);
}

// ---------- Sayaç animasyonu (altın/fetih sayısı akıp değişsin diye) ----------
// onStep: değer her değiştiğinde (en fazla ~12 kez/sn) çağrılır — altın sesi için.
function animateNumber(target, to, { duration = 500, onStep } = {}) {
  const from = parseInt(target.textContent, 10) || 0;
  if (from === to) return;
  const start = performance.now();
  let lastStep = 0;
  function step(now) {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = Math.round(from + (to - from) * eased);
    if (String(value) !== target.textContent) {
      target.textContent = value;
      if (onStep && now - lastStep > 80) {
        lastStep = now;
        onStep();
      }
    }
    if (progress < 1) requestAnimationFrame(step);
    else target.textContent = to;
  }
  requestAnimationFrame(step);
}

function bump(node) {
  node.classList.remove("bump");
  void node.offsetWidth;
  node.classList.add("bump");
}

// Topbar'daki altını sesli şekilde akıtarak güncelle
function flowGold(to) {
  el.goldStat.classList.add("flowing");
  animateNumber(el.goldCount, to, { duration: 1300, onStep: playSfxCoin });
  setTimeout(() => {
    el.goldStat.classList.remove("flowing");
    bump(el.goldStat);
  }, 1300);
}

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function speedBonusFor(secondsLeft) {
  const t = Math.max(0, Math.min(QUESTION_TIME, secondsLeft));
  return Math.round((t / QUESTION_TIME) * SPEED_BONUS_MAX);
}

// ---------- Ekran ve modal geçişleri ----------
let currentScreen = el.loginScreen;

function showScreen(next) {
  if (next === currentScreen) return;
  const prev = currentScreen;
  currentScreen = next;
  el.app.dataset.view = next === el.mapScreen ? "map" : "hero";
  // giriş ekranı kendi arka planını, diğer menü ekranları seçim arka planını
  // kullanır; değişim CSS'te 0.6 sn'lik crossfade
  if (next !== el.mapScreen) el.app.dataset.bg = next === el.loginScreen ? "giris" : "secim";
  if (prev) {
    prev.classList.remove("entering");
    prev.classList.add("leaving");
    setTimeout(() => {
      prev.classList.remove("leaving");
      if (currentScreen !== prev) prev.classList.add("hidden");
    }, 200);
  }
  next.classList.remove("hidden", "leaving", "entering");
  void next.offsetWidth;
  next.classList.add("entering");
  setTimeout(() => next.classList.remove("entering"), 420);
}

// Giriş/menü arka planındaki altın kıvılcımlar: birkaç düzine küçük nokta,
// sadece CSS transform/opacity animasyonu (telefonda daha az parça).
(function spawnSparks() {
  const host = document.getElementById("hero-particles");
  if (!host || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const count = window.matchMedia("(pointer: coarse)").matches ? 12 : 22;
  for (let i = 0; i < count; i++) {
    const s = document.createElement("span");
    s.className = "spark";
    s.style.left = (Math.random() * 100).toFixed(1) + "%";
    s.style.setProperty("--s", (2 + Math.random() * 4).toFixed(1) + "px");
    s.style.setProperty("--d", (10 + Math.random() * 10).toFixed(1) + "s");
    s.style.setProperty("--delay", (-Math.random() * 20).toFixed(1) + "s");
    s.style.setProperty("--dx", (Math.random() * 80 - 40).toFixed(0) + "px");
    s.style.setProperty("--o", (0.45 + Math.random() * 0.5).toFixed(2));
    host.appendChild(s);
  }
})();

function openModal(modal) {
  clearTimeout(modal._closeTimer);
  modal.classList.remove("hidden", "closing");
}

function closeModal(modal) {
  if (modal.classList.contains("hidden")) return Promise.resolve();
  modal.classList.add("closing");
  return new Promise((resolve) => {
    modal._closeTimer = setTimeout(() => {
      modal.classList.add("hidden");
      modal.classList.remove("closing");
      resolve();
    }, 180);
  });
}

function isOpen(modal) {
  return !modal.classList.contains("hidden") && !modal.classList.contains("closing");
}

// ---------- Sunucu iletişimi ----------
// Tüm HTTP istekleri buradan geçer: zaman aşımı, hata durumunda anlaşılır
// "Sunucuya bağlanılamadı" ekranı. Hata yine fırlatılır ki çağıran akış dursun.
const API_TIMEOUT_MS = 8000;

async function api(path, { method = "GET", body, quiet = false } = {}) {
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
    if (!quiet) showServerError();
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
  closeModal(el.eventSelectModal);
});
el.emptyCloseBtn.addEventListener("click", () => {
  playSfxClick();
  closeModal(el.emptyModal);
});
el.resultCloseBtn.addEventListener("click", handleResultClose);
el.eraCloseBtn.addEventListener("click", () => {
  playSfxClick();
  closeModal(el.eraModal);
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

const isTouchDevice = window.matchMedia("(pointer: coarse)").matches;

async function tryLockLandscape() {
  // Sadece telefonda: Chrome/Android gibi tam ekran + Screen Orientation API
  // destekleyen ortamlarda çalışır (iOS Safari desteklemez) — bu yüzden
  // sessizce yutulur, asıl güvence CSS'teki "yatay çevir" uyarısıdır.
  if (!isTouchDevice) return;
  try {
    if (document.documentElement.requestFullscreen && !document.fullscreenElement) {
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
    bump(el.usernameInput);
    return;
  }
  el.usernameInput.blur();
  tryLockLandscape();
  startMusic();
  playSfxClick();
  haptic(HAPTIC.tap);
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

    renderCharacterGrid();
    showScreen(el.characterScreen);
  } catch (err) {
    /* api() bağlantı hatası ekranını zaten gösterdi */
  }
}

// ---------- Kumandan seçimi ----------
function renderCharacterGrid() {
  el.characterGrid.innerHTML = "";
  CHARACTERS.forEach((char) => {
    const btn = document.createElement("button");
    btn.type = "button";
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
    btn.addEventListener("click", () => selectCharacter(char, btn));
    el.characterGrid.appendChild(btn);
  });
}

function selectCharacter(char, btn) {
  if (state.battleCryTimer) return; // savaş sözü zaten oynuyor
  playSfxHorn();
  haptic(HAPTIC.tap);
  state.character = char.key;
  updateCharacterBadgeUI();
  el.characterGrid.querySelectorAll(".character-card").forEach((b) => b.classList.toggle("selected", b === btn));

  // kozmetik bir tercih — kaydedilemese bile sefere devam et
  fetch(`${API_BASE}/player/${encodeURIComponent(state.username)}/character`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character_key: char.key }),
  }).catch(() => {});

  setPortraitTheme(el.battleCryPortrait, char);
  el.battleCryName.textContent = char.name;
  el.battleCryQuote.textContent = `“${char.cry}”`;
  setTimeout(() => {
    el.battleCry.classList.remove("hidden");
    state.battleCryTimer = setTimeout(finishBattleCry, 2100);
  }, 180);
}

function finishBattleCry() {
  if (!state.battleCryTimer) return;
  clearTimeout(state.battleCryTimer);
  state.battleCryTimer = null;
  showScreen(el.modeScreen);
  setTimeout(() => el.battleCry.classList.add("hidden"), 220);
}
el.battleCry.addEventListener("click", finishBattleCry);

function updateCharacterBadgeUI() {
  const char = findCharacter(state.character);
  state.myColor = characterColor(state.character);
  document.documentElement.style.setProperty("--cmd", state.myColor);
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
  showScreen(el.loginScreen);
});
el.modeBackBtn.addEventListener("click", () => {
  playSfxClick();
  renderCharacterGrid();
  showScreen(el.characterScreen);
});
el.roomBackBtn.addEventListener("click", () => {
  playSfxClick();
  leaveRoom();
  showScreen(el.modeScreen);
});
el.mapMenuBtn.addEventListener("click", () => {
  playSfxClick();
  showScreen(el.modeScreen);
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
  haptic(HAPTIC.tap);
  state.mode = "solo";
  el.mapHint.textContent = "Bir ülkeye dokun, tarihi olayı fethet.";
  el.enemyStat.classList.add("hidden");
  el.mapMenuBtn.classList.remove("hidden");
  try {
    await Promise.all([loadProgress(), loadCountries()]);
    renderEraTabs();
    showScreen(el.mapScreen);
  } catch (err) {
    /* bağlantı hatası ekranı gösterildi */
  }
});

el.duoModeBtn.addEventListener("click", () => {
  playSfxClick();
  haptic(HAPTIC.tap);
  state.mode = "duo";
  state.roomEra = state.roomEra || state.currentEra;
  ensureSocket();
  renderEraPicker();
  el.roomIdle.classList.remove("hidden");
  el.roomWaiting.classList.add("hidden");
  el.roomError.classList.add("hidden");
  showScreen(el.roomScreen);
});

// ---------- Oda kur / katıl ----------
function renderEraPicker() {
  el.eraPicker.innerHTML = "";
  state.eras.forEach((era) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "era-chip" + (era.key === state.roomEra ? " selected" : "");
    chip.textContent = era.name;
    chip.addEventListener("click", () => {
      playSfxClick();
      state.roomEra = era.key;
      renderEraPicker();
    });
    el.eraPicker.appendChild(chip);
  });
}

el.createRoomBtn.addEventListener("click", () => {
  playSfxClick();
  haptic(HAPTIC.tap);
  el.roomError.classList.add("hidden");
  ensureSocket().emit("create_room", { username: state.username, era: state.roomEra });
});

el.joinRoomBtn.addEventListener("click", joinRoom);
el.joinCodeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") joinRoom();
});

function joinRoom() {
  playSfxClick();
  haptic(HAPTIC.tap);
  const code = el.joinCodeInput.value.trim();
  el.roomError.classList.add("hidden");
  if (!/^\d{4}$/.test(code)) {
    el.roomError.textContent = "4 haneli oda kodunu gir.";
    el.roomError.classList.remove("hidden");
    return;
  }
  el.joinCodeInput.blur();
  ensureSocket().emit("join_room_request", { username: state.username, code });
}

// İkinci oyuncunun hangi adrese girmesi gerektiğini oda ekranında göster.
async function showJoinAddress() {
  let url = null;
  const host = window.location.hostname;
  if (host && host !== "localhost" && host !== "127.0.0.1") {
    url = window.location.origin;
  } else {
    try {
      const info = await api("/server-info", { quiet: true });
      url = (info.lan_urls || [])[0] || null;
    } catch (err) {
      url = null;
    }
  }
  el.roomWaitHint.textContent = "";
  if (url) {
    el.roomWaitHint.append("Rakibin aynı Wi-Fi'dan ");
    const strong = document.createElement("strong");
    strong.textContent = url;
    el.roomWaitHint.append(strong, " adresine girip bu kodu yazsın.");
  } else {
    el.roomWaitHint.textContent = "Rakibin bu kodu girip katılmasını bekliyoruz…";
  }
}

function ensureSocket() {
  if (state.socket) return state.socket;
  const socket = io(SOCKET_BASE, { reconnectionDelayMax: 3000 });
  state.socket = socket;

  socket.on("connect", () => el.connBanner.classList.add("hidden"));
  socket.on("disconnect", () => {
    if (state.socket === socket && !state.matchOver) el.connBanner.classList.remove("hidden");
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
    playSfxWrong();
  });

  socket.on("room_created", ({ code, era_name }) => {
    state.roomCode = code;
    el.roomIdle.classList.add("hidden");
    el.roomWaiting.classList.remove("hidden");
    el.roomCodeDisplay.textContent = code;
    el.roomWaitEra.textContent = `${era_name} · 5 dakika`;
    showJoinAddress();
  });

  socket.on("match_start", async (data) => {
    state.roomCode = data.code;
    state.matchOver = false;
    state.opponentUsername = data.players.find((p) => p !== state.username) || null;
    const opponentCharKey = (data.characters || {})[state.opponentUsername] || null;
    state.opponentCharacter = opponentCharKey;
    state.myColor = characterColor(state.character);
    state.enemyColor = characterColor(opponentCharKey, THEME_COLORS["theme-purple"]);
    if (state.enemyColor === state.myColor) {
      state.enemyColor = state.myColor === THEME_COLORS["theme-purple"] ? THEME_COLORS["theme-teal"] : THEME_COLORS["theme-purple"];
    }
    state.matchEraKey = data.era_key || null;
    if (state.matchEraKey) state.currentEra = state.matchEraKey;
    state.streak = 0;

    try {
      if (!state.countriesRaw) {
        state.countriesRaw = await api("/countries/all");
      }
    } catch (err) {
      return;
    }
    state.duoEvents = new Map(data.events.map((e) => [e.id, e]));

    el.enemyStat.classList.remove("hidden");
    el.mapMenuBtn.classList.add("hidden");
    const opponentChar = findCharacter(opponentCharKey);
    applyPortrait(el.enemyPortrait, opponentChar);
    el.enemyName.textContent = state.opponentUsername || "";
    el.mapHint.textContent = "Ülkelere saldır, rakibinden önce fethet!";

    startMatchTimer(data.seconds_left || 300);
    renderEraTabs();
    refreshMap();
    updateDuoStatsUI();
    showScreen(el.mapScreen);
    playSfxHorn();
    haptic(HAPTIC.conquer);
  });

  socket.on("event_locked", ({ event_id, by }) => {
    const ev = state.duoEvents.get(event_id);
    if (ev) { ev.state = "locked"; ev.owner = by; }
    if (by !== state.username) refreshMap();
  });

  socket.on("attack_denied", ({ event_id }) => {
    if (state.activeEvent && state.activeEvent.id === event_id) {
      stopTimer();
      closeModal(el.quizModal);
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
      buttons.forEach((b) => b.classList.add("disabled"));
      const chosenBtn = buttons.find((b) => b.dataset.key === lastChosen);
      celebrateCorrect(chosenBtn, state.lastTimeLeft);
      setTimeout(() => renderQuizQuestion(), 1100);
    } else {
      openModal(el.quizModal);
      renderQuizQuestion();
    }
  });

  socket.on("event_result", (data) => {
    const { event_id, correct, owner, correct_option, by } = data;
    const ev = state.duoEvents.get(event_id);
    if (ev) {
      ev.state = correct ? "conquered" : "available";
      ev.owner = correct ? owner : null;
    }

    const iAmAttacker = by === state.username;
    if (iAmAttacker && state.activeEvent && state.activeEvent.id === event_id) {
      finishDuoEvent(correct, correct_option, data);
    } else {
      // rakibin fethi de haritada animasyonla görünsün
      if (correct && ev) state.justConquered = ev.country_id;
      refreshMap();
      updateDuoStatsUI();
    }
  });

  socket.on("match_over", (data) => showMatchOver(data));

  socket.on("opponent_left", () => {
    if (state.matchOver) return;
    stopTimer();
    stopMatchTimer();
    el.quizModal.classList.add("hidden");
    openModal(el.opponentLeftModal);
  });

  return socket;
}

// ---------- 2 kişilik maç süresi ----------
function startMatchTimer(seconds) {
  stopMatchTimer();
  state.matchEndsAt = Date.now() + seconds * 1000;
  el.matchTimerStat.classList.remove("hidden");
  const tick = () => {
    const left = Math.max(0, Math.round((state.matchEndsAt - Date.now()) / 1000));
    el.matchTimer.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    el.matchTimerStat.classList.toggle("urgent", left <= 30);
    if (left <= 0) stopMatchTimer(false);
  };
  tick();
  state.matchTimerInterval = setInterval(tick, 250);
}

function stopMatchTimer(hide = false) {
  clearInterval(state.matchTimerInterval);
  state.matchTimerInterval = null;
  if (hide) el.matchTimerStat.classList.add("hidden");
}

function showMatchOver({ scores, gold = {}, reason }) {
  state.matchOver = true;
  stopTimer();
  stopMatchTimer();
  el.quizModal.classList.add("hidden");
  const mine = scores[state.username] || 0;
  const enemy = scores[state.opponentUsername] || 0;
  let title;
  if (mine > enemy) title = "Zafer Senin!";
  else if (mine < enemy) title = "Rakip Kazandı";
  else title = "Berabere!";
  el.matchOverTitle.textContent = title;
  el.matchOverReason.textContent = reason === "time" ? "Süre Doldu" : "Tüm Olaylar Fethedildi";

  el.matchOverVersus.innerHTML = "";
  const side = (name, charKey, score, g, winner) => {
    const wrap = document.createElement("div");
    wrap.className = "versus-side" + (winner ? " winner" : "");
    const icon = document.createElement("div");
    icon.className = "character-icon";
    setPortraitTheme(icon, findCharacter(charKey));
    const n = document.createElement("div");
    n.className = "versus-name";
    n.textContent = name;
    const s = document.createElement("div");
    s.className = "versus-score";
    s.textContent = score;
    const gl = document.createElement("div");
    gl.className = "versus-gold";
    gl.textContent = `${score} olay · ◈ ${g}`;
    wrap.append(icon, n, s, gl);
    return wrap;
  };
  const vs = document.createElement("div");
  vs.className = "versus-vs";
  vs.textContent = "VS";
  el.matchOverVersus.append(
    side(state.username + " (sen)", state.character, mine, gold[state.username] || 0, mine > enemy),
    vs,
    side(state.opponentUsername || "Rakip", state.opponentCharacter, enemy, gold[state.opponentUsername] || 0, enemy > mine)
  );
  el.matchOverCard.classList.toggle("celebrate", mine >= enemy);
  openModal(el.matchOverModal);
  if (mine > enemy) {
    playSfxEra();
    spawnConfetti({ rain: 40, burst: 30, colors: [state.myColor] });
    haptic(HAPTIC.conquer);
  } else {
    playSfxWrong();
    haptic(HAPTIC.wrong);
  }
}

// ---------- Dönem sekmeleri + ilerleme ----------
function eraStats(eraKey) {
  if (state.mode === "duo") {
    const byCountry = new Map();
    state.duoEvents.forEach((e) => {
      if (e.era_key !== eraKey) return;
      if (!byCountry.has(e.country_id)) byCountry.set(e.country_id, []);
      byCountry.get(e.country_id).push(e);
    });
    let conquered = 0;
    byCountry.forEach((evs) => {
      if (evs.every((e) => e.state === "conquered" && e.owner === state.username)) conquered++;
    });
    const era = state.eras.find((e) => e.key === eraKey);
    return { name: era ? era.name : eraKey, conquered, total: byCountry.size };
  }
  return state.progress[eraKey] || { name: eraKey, conquered: 0, total: 0 };
}

function renderEraTabs() {
  el.eraTabs.innerHTML = "";
  const eras = state.mode === "duo" && state.matchEraKey
    ? state.eras.filter((e) => e.key === state.matchEraKey)
    : state.eras;
  eras.forEach((era) => {
    const stats = eraStats(era.key);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "era-tab" + (era.key === state.currentEra ? " active" : "");
    if (stats.total > 0 && stats.conquered === stats.total) btn.classList.add("done");
    const name = document.createElement("span");
    name.textContent = era.name;
    const count = document.createElement("span");
    count.className = "era-tab-count";
    count.textContent = `${stats.conquered}/${stats.total}`;
    btn.append(name, count);
    btn.addEventListener("click", async () => {
      if (state.currentEra === era.key) return;
      playSfxClick();
      haptic(HAPTIC.tap);
      state.currentEra = era.key;
      renderEraTabs();
      await refreshMap();
    });
    el.eraTabs.appendChild(btn);
  });
  updateProgressUI();
}

function updateProgressUI() {
  const stats = eraStats(state.currentEra);
  el.eraProgressLabel.textContent = stats.name;
  el.eraProgressCount.textContent = `${stats.conquered}/${stats.total}`;
  const ratio = stats.total ? stats.conquered / stats.total : 0;
  el.eraProgressFill.style.transform = `scaleX(${ratio})`;
  el.eraProgress.classList.toggle("complete", stats.total > 0 && stats.conquered === stats.total);
  el.eraProgress.setAttribute("aria-label", `${stats.name}: ${stats.conquered}/${stats.total} fethedildi`);
}

async function loadProgress() {
  state.progress = await api(`/progress?username=${encodeURIComponent(state.username)}`);
}

// ---------- Harita (mod-agnostik render) ----------
async function refreshMap() {
  if (state.mode === "duo") {
    state.countries = computeDuoCountries();
    renderMap();
    renderEraTabs();
    updateDuoStatsUI();
  } else {
    try {
      await Promise.all([loadCountries(), loadProgress()]);
      renderEraTabs();
    } catch (err) {
      /* bağlantı hatası ekranı gösterildi */
    }
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
  let conqueredNow = null;
  state.countries.forEach((country) => {
    const ui = COUNTRY_UI[country.key] || { short: country.name, side: "bottom" };
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `country-marker ${country.status} lbl-${ui.side}`;
    if (country.status === "conquered" && state.mode === "duo" && !country.mine) btn.classList.add("enemy");
    btn.style.left = country.x + "%";
    btn.style.top = country.y + "%";
    const owner = state.mode === "duo" && country.status === "conquered" && !country.mine ? state.enemyColor : state.myColor;
    btn.style.setProperty("--owner", owner);

    const badge = document.createElement("div");
    badge.className = "country-badge";
    if (country.status === "conquered") {
      const flag = document.createElement("span");
      flag.className = "flag-glyph";
      flag.textContent = "⚑";
      badge.appendChild(flag);
    } else {
      badge.textContent = country.status === "locked" ? "⏳" : country.status === "empty" ? "?" : "⚔";
    }

    const label = document.createElement("div");
    label.className = "country-label";
    label.textContent = ui.short;

    let ariaExtra = "";
    if (country.status === "conquered") ariaExtra = country.mine === false ? " (rakipte)" : " (fethedildi)";
    else if (country.status === "empty") ariaExtra = " (yakında)";
    else if (country.status === "locked") ariaExtra = " (rakip deniyor)";
    btn.setAttribute("aria-label", country.name + ariaExtra);

    btn.appendChild(badge);
    btn.appendChild(label);

    if (state.justConquered === country.id && country.status === "conquered") {
      btn.classList.add("just-conquered");
      conqueredNow = country;
    }

    const clickable = country.status === "empty" || country.status === "available";
    if (clickable) {
      btn.addEventListener("click", () => {
        playSfxClick();
        haptic(HAPTIC.tap);
        openCountry(country);
      });
    } else {
      btn.tabIndex = -1;
    }
    el.map.appendChild(btn);
  });
  if (conqueredNow) {
    state.justConquered = null;
    setTimeout(playSfxFlag, 250);
  }
}

// ---------- Ülkeye tıklama → olay(lar) ----------
async function openCountry(country) {
  state.activeCountry = country;

  if (country.status === "empty") {
    el.emptyCountryName.textContent = country.name;
    openModal(el.emptyModal);
    return;
  }

  let events;
  if (state.mode === "duo") {
    events = country.events.filter((e) => e.state === "available");
  } else {
    try {
      events = await api(
        `/countries/${country.id}/events?era=${encodeURIComponent(state.currentEra)}&username=${encodeURIComponent(state.username)}`
      );
    } catch (err) {
      return;
    }
  }

  if (events.length === 0) {
    el.emptyCountryName.textContent = country.name;
    openModal(el.emptyModal);
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
    item.type = "button";
    item.className = "event-item" + (ev.conquered ? " conquered" : "");
    const title = document.createElement("span");
    title.className = "event-item-title";
    title.textContent = ev.title + (ev.conquered ? " ✓" : "");
    const leader = document.createElement("span");
    leader.className = "event-item-leader";
    leader.textContent = ev.leader || "";
    item.appendChild(title);
    item.appendChild(leader);
    item.addEventListener("click", async () => {
      playSfxClick();
      await closeModal(el.eventSelectModal);
      if (state.mode === "duo") attackEvent(ev);
      else openEvent(ev);
    });
    el.eventList.appendChild(item);
  });
  openModal(el.eventSelectModal);
}

// ---------- Olay / çok soruluk quiz akışı — TEK KİŞİLİK ----------
async function openEvent(eventSummary) {
  let event;
  try {
    event = await api(`/events/${eventSummary.id}?username=${encodeURIComponent(state.username)}`);
  } catch (err) {
    return;
  }

  state.activeEvent = event;
  state.qIndex = 0;
  state.qTotal = event.questions.length;
  state.currentQuestion = event.questions[0];
  state.answers = {};
  state.times = {};
  state.streakAtStart = state.streak;

  openModal(el.quizModal);
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
  el.quizCard.classList.remove("shake");
  el.quizFeedback.classList.add("hidden");
  el.quizEventTitle.textContent = event.title + (event.leader ? " · " + event.leader : "");
  el.quizProgress.textContent = `Soru ${state.qIndex + 1}/${state.qTotal}`;
  el.quizText.textContent = question.text;
  el.quizText.classList.remove("enter");
  void el.quizText.offsetWidth;
  el.quizText.classList.add("enter");
  el.quizOptions.innerHTML = "";
  updateStreakBadge();

  // Gösterim sırası karıştırılır; cevap harf anahtarıyla (a-d) kontrol
  // edildiği için doğru cevap değişmez.
  shuffle(Object.entries(question.options)).forEach(([key, label], i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "option-btn";
    btn.textContent = label;
    btn.dataset.key = key;
    btn.dataset.num = String(i + 1);
    btn.addEventListener("click", () => handleAnswer(key));
    el.quizOptions.appendChild(btn);
  });

  startTimer();
}

function startTimer() {
  stopTimer();
  state.timeLeft = QUESTION_TIME;
  const startedAt = performance.now();
  let lastWhole = QUESTION_TIME;
  el.timerFill.style.transform = "scaleX(1)";
  el.timerNum.textContent = QUESTION_TIME;
  el.timerRow.classList.remove("warn");

  state.timerInterval = setInterval(() => {
    state.timeLeft = QUESTION_TIME - (performance.now() - startedAt) / 1000;
    const left = Math.max(0, state.timeLeft);
    el.timerFill.style.transform = `scaleX(${left / QUESTION_TIME})`;
    const whole = Math.ceil(left);
    if (whole !== lastWhole) {
      lastWhole = whole;
      el.timerNum.textContent = whole;
      if (whole <= WARN_SECONDS && whole > 0) {
        el.timerRow.classList.add("warn");
        // nabız animasyonunu her saniyenin başına hizala
        el.timerRow.classList.remove("warn");
        void el.timerRow.offsetWidth;
        el.timerRow.classList.add("warn");
        playSfxTick();
      }
    }
    if (state.timeLeft <= 0) {
      stopTimer();
      if (!state.answered) handleAnswer(null);
    }
  }, 100);
}

function stopTimer() {
  clearInterval(state.timerInterval);
  state.timerInterval = null;
}

function handleAnswer(chosenKey) {
  if (state.answered) return;
  if (state.mode === "duo") handleAnswerDuo(chosenKey);
  else handleAnswerSolo(chosenKey);
}

// ---------- Doğru / yanlış efektleri (iki mod ortak) ----------
function updateStreakBadge() {
  if (state.streak >= STREAK_MIN) {
    el.streakBadge.textContent = `🔥 ${state.streak}x SERİ`;
    if (el.streakBadge.classList.contains("hidden")) el.streakBadge.classList.remove("hidden");
  } else {
    el.streakBadge.classList.add("hidden");
  }
}

function floatText(anchor, text) {
  if (!anchor) return;
  const cardRect = el.quizCard.getBoundingClientRect();
  const r = anchor.getBoundingClientRect();
  const bubble = document.createElement("div");
  bubble.className = "float-bonus";
  bubble.textContent = text;
  bubble.style.left = (r.left - cardRect.left + r.width - 70) + "px";
  bubble.style.top = (r.top - cardRect.top - 6 + el.quizCard.scrollTop) + "px";
  bubble.addEventListener("animationend", () => bubble.remove());
  el.quizCard.appendChild(bubble);
}

function celebrateCorrect(btn, secondsLeft) {
  if (btn) btn.classList.add("correct");
  playSfxCorrect();
  haptic(HAPTIC.correct);
  state.streak += 1;
  const bonus = speedBonusFor(secondsLeft);
  if (bonus > 0) floatText(btn, `+${bonus} hız`);
  updateStreakBadge();
  if (state.streak >= STREAK_MIN) {
    el.streakFlash.textContent = `${state.streak}x SERİ!`;
    el.streakFlash.classList.remove("hidden");
    el.streakFlash.style.animation = "none";
    void el.streakFlash.offsetWidth;
    el.streakFlash.style.animation = "";
    setTimeout(() => playSfxStreak(state.streak), 120);
    clearTimeout(el.streakFlash._t);
    el.streakFlash._t = setTimeout(() => el.streakFlash.classList.add("hidden"), 1000);
  }
}

function showWrong(buttons, chosenKey, correctKey) {
  buttons.forEach((b) => {
    if (b.dataset.key === correctKey) b.classList.add("reveal");
    else if (b.dataset.key === chosenKey) b.classList.add("wrong");
  });
  el.quizCard.classList.remove("shake");
  void el.quizCard.offsetWidth;
  el.quizCard.classList.add("shake");
  playSfxWrong();
  haptic(HAPTIC.wrong);
  state.streak = 0;
  updateStreakBadge();
}

// ---------- Cevap işleme — TEK KİŞİLİK ----------
async function handleAnswerSolo(chosenKey) {
  state.answered = true;
  stopTimer();
  const secondsLeft = Math.max(0, state.timeLeft);

  const event = state.activeEvent;
  const question = event.questions[state.qIndex];
  state.answers[question.id] = chosenKey;
  state.times[question.id] = secondsLeft;

  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => b.classList.add("disabled"));
  const chosenBtn = buttons.find((b) => b.dataset.key === chosenKey);
  if (chosenBtn) chosenBtn.classList.add("pressed");

  let check;
  try {
    check = await api(`/questions/${question.id}/check`, { method: "POST", body: { chosen: chosenKey } });
  } catch (err) {
    check = { correct: false, correct_option: null };
  }
  if (chosenBtn) chosenBtn.classList.remove("pressed");

  if (check.correct) {
    celebrateCorrect(chosenBtn, secondsLeft);
  } else {
    showWrong(buttons, chosenKey, check.correct_option);
    if (!chosenKey) showFeedback("Süre doldu!", "lose");
  }

  const isLast = state.qIndex === event.questions.length - 1;

  setTimeout(() => {
    if (!check.correct || isLast) {
      finishSoloEvent();
    } else {
      state.qIndex += 1;
      renderQuizQuestion();
    }
  }, check.correct ? 1100 : 1900);
}

function showFeedback(text, kind) {
  el.quizFeedback.textContent = text;
  el.quizFeedback.classList.remove("hidden", "win", "lose");
  el.quizFeedback.classList.add(kind);
}

function rewardRow(label, value, extraClass = "", delay = 0) {
  const row = document.createElement("div");
  row.className = "reward-row " + extraClass;
  row.style.animationDelay = delay + "s";
  const l = document.createElement("span");
  l.textContent = label;
  const v = document.createElement("span");
  v.className = "reward-val";
  v.textContent = value;
  row.append(l, v);
  el.rewardRows.appendChild(row);
  return v;
}

async function finishSoloEvent() {
  const event = state.activeEvent;
  const country = state.activeCountry;
  const eraBefore = { ...eraStats(state.currentEra) };

  let result;
  try {
    result = await api(`/events/${event.id}/answer`, {
      method: "POST",
      body: { username: state.username, answers: state.answers, times: state.times, streak: state.streakAtStart },
    });
  } catch (err) {
    result = null;
  }

  await closeModal(el.quizModal);

  el.resultCard.classList.remove("celebrate");
  el.rewardRows.innerHTML = "";

  if (result) {
    state.conqueredCount = result.conquered_count;
    animateNumber(el.conquerCount, state.conqueredCount);

    if (result.all_correct && !result.already_conquered) {
      el.resultEyebrow.textContent = "Fetih Tamam";
      el.resultTitle.textContent = event.title + " Fethedildi!";
      el.resultDetail.textContent = (country ? country.name + " · " : "") + "Sancağın dalgalanıyor, Kumandan!";
      const total = result.gold_reward + result.speed_bonus + result.streak_bonus;
      rewardRow("Fetih ödülü", `+${result.gold_reward}`, "", 0.15);
      if (result.speed_bonus) rewardRow("Hız bonusu", `+${result.speed_bonus}`, "", 0.3);
      if (result.streak_bonus) rewardRow("Seri bonusu", `+${result.streak_bonus}`, "", 0.45);
      const totalEl = rewardRow("Toplam altın", "+0", "total", 0.6);
      setTimeout(() => {
        totalEl.textContent = "0";
        animateNumber(totalEl, total, { duration: 900 });
        setTimeout(() => (totalEl.textContent = "+" + total), 950);
      }, 650);

      el.resultCard.classList.add("celebrate");
      playConquestCelebration(country);
      spawnConfetti({ colors: [state.myColor, state.myColor] });
      haptic(HAPTIC.conquer);
      state.gold = result.gold;
      setTimeout(() => flowGold(state.gold), 700);
      bump(el.conquerStat);

      if (country) state.justConquered = country.id;
      // dönemin son ülkesi de alındıysa tören ekranını sıraya koy
      try {
        await loadProgress();
        const after = eraStats(state.currentEra);
        if (after.total > 0 && after.conquered === after.total && eraBefore.conquered < eraBefore.total) {
          state.pendingEraComplete = state.currentEra;
        }
      } catch (err) {
        /* yok say */
      }
    } else if (result.all_correct) {
      el.resultEyebrow.textContent = "Zaten Senin";
      el.resultTitle.textContent = event.title;
      el.resultDetail.textContent = "Bu olayı daha önce fethetmiştin. Bilgin hâlâ keskin!";
      state.gold = result.gold;
      updateStatsUI();
    } else {
      el.resultEyebrow.textContent = "Sefer Başarısız";
      el.resultTitle.textContent = "Bu Sefer Olmadı";
      el.resultDetail.textContent = "Yanlış cevap ya da süre doldu. Ordunu topla, tekrar dene!";
      if (result.penalty) rewardRow("Sefer bedeli", `−${result.penalty}`, "penalty", 0.15);
      state.gold = result.gold;
      animateNumber(el.goldCount, state.gold, { duration: 700 });
    }
  } else {
    el.resultEyebrow.textContent = "Bağlantı Hatası";
    el.resultTitle.textContent = "Sunucuya Ulaşılamadı";
    el.resultDetail.textContent = "Lütfen tekrar dene.";
  }

  openModal(el.resultModal);
}

async function handleResultClose() {
  playSfxClick();
  await closeModal(el.resultModal);
  await refreshMap();
  if (state.pendingEraComplete) {
    const eraKey = state.pendingEraComplete;
    state.pendingEraComplete = null;
    setTimeout(() => showEraComplete(eraKey), 1300);
  }
}

// ---------- "Dönem Fethedildi" töreni (tek kişilik) ----------
function showEraComplete(eraKey) {
  const stats = eraStats(eraKey);
  setPortraitTheme(el.eraPortrait, findCharacter(state.character));
  el.eraTitle.textContent = stats.name;
  el.eraDetail.textContent = `${stats.total} ülkenin hepsi artık senin, ${state.username}! Hazinende ◈ ${state.gold} altın var.`;
  openModal(el.eraModal);
  playSfxEra();
  haptic([60, 40, 60, 40, 200]);
  spawnConfetti({ rain: 40, burst: 32, colors: [state.myColor, "#f5d38a"] });
  setTimeout(() => spawnConfetti({ rain: 30, burst: 0, colors: [state.myColor] }), 1300);
}

// ---------- Cevap işleme — 2 KİŞİLİK ----------
function handleAnswerDuo(chosenKey) {
  state.answered = true;
  state.lastChosenKey = chosenKey;
  state.lastTimeLeft = Math.max(0, state.timeLeft);
  stopTimer();

  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => b.classList.add("disabled"));
  const chosenBtn = buttons.find((b) => b.dataset.key === chosenKey);
  if (chosenBtn) chosenBtn.classList.add("pressed");

  state.socket.emit("submit_answer", {
    code: state.roomCode,
    username: state.username,
    event_id: state.activeEvent.id,
    question_id: state.currentQuestion.id,
    chosen: chosenKey,
  });
}

function finishDuoEvent(correct, correctOption, data) {
  const buttons = [...el.quizOptions.querySelectorAll(".option-btn")];
  buttons.forEach((b) => {
    b.classList.add("disabled");
    b.classList.remove("pressed");
  });

  if (correct) {
    const chosenBtn = buttons.find((b) => b.dataset.key === state.lastChosenKey);
    celebrateCorrect(chosenBtn, state.lastTimeLeft);
    const reward = data.gold_reward || 0;
    state.gold += reward;
    showFeedback(
      `Fetih tamam! +${reward} altın` + (data.speed_bonus ? ` (hız bonusu +${data.speed_bonus})` : ""),
      "win"
    );
    playConquestCelebration(state.activeCountry);
    spawnConfetti({ colors: [state.myColor, state.myColor] });
    haptic(HAPTIC.conquer);
    flowGold(state.gold);
    if (state.activeCountry) state.justConquered = state.activeCountry.id;
  } else {
    showWrong(buttons, state.lastChosenKey, correctOption);
    showFeedback(
      state.lastChosenKey ? "Yanlış cevap. Bu olay tekrar herkese açıldı." : "Süre doldu. Bu olay tekrar herkese açıldı.",
      "lose"
    );
  }

  updateDuoStatsUI();
  state.currentQuestion = null;

  setTimeout(async () => {
    await closeModal(el.quizModal);
    refreshMap();
  }, correct ? 1700 : 2000);
}

// ---------- Kumandanlar Sıralaması ----------
async function openLeaderboard() {
  playSfxClick();
  let rows;
  try {
    rows = await api("/leaderboard");
  } catch (err) {
    return;
  }
  rows = rows.filter((r) => r.best_score > 0 || r.username === state.username);
  el.leaderboardList.innerHTML = "";
  if (rows.length === 0) {
    const li = document.createElement("li");
    li.className = "lb-empty";
    li.textContent = "Henüz kimse fetih yapmadı — ilk sancağı sen dik!";
    el.leaderboardList.appendChild(li);
  }
  const medals = ["🥇", "🥈", "🥉"];
  rows.forEach((r, i) => {
    const li = document.createElement("li");
    li.className = "lb-row" + (r.username === state.username ? " me" : "");
    li.style.animationDelay = i * 0.04 + "s";
    const rank = document.createElement("span");
    rank.className = "lb-rank";
    rank.textContent = medals[i] || String(i + 1);
    const portrait = document.createElement("div");
    portrait.className = "character-icon lb-portrait";
    setPortraitTheme(portrait, findCharacter(r.character_key));
    const name = document.createElement("span");
    name.className = "lb-name";
    name.textContent = r.username + (r.username === state.username ? " (sen)" : "");
    const conq = document.createElement("span");
    conq.className = "lb-stat";
    conq.textContent = `⚑ ${r.best_score}`;
    const gold = document.createElement("span");
    gold.className = "lb-stat";
    gold.textContent = `◈ ${r.gold}`;
    li.append(rank, portrait, name, conq, gold);
    el.leaderboardList.appendChild(li);
  });
  openModal(el.leaderboardModal);
}
el.leaderboardBtn.addEventListener("click", openLeaderboard);
el.modeLeaderboardBtn.addEventListener("click", openLeaderboard);
el.leaderboardCloseBtn.addEventListener("click", () => {
  playSfxClick();
  closeModal(el.leaderboardModal);
});

// ---------- İstatistikler ----------
function updateStatsUI() {
  animateNumber(el.goldCount, state.gold);
  animateNumber(el.conquerCount, state.conqueredCount);
}

function updateDuoStatsUI() {
  const mine = [...state.duoEvents.values()].filter((e) => e.state === "conquered" && e.owner === state.username).length;
  const enemy = [...state.duoEvents.values()].filter((e) => e.state === "conquered" && e.owner === state.opponentUsername).length;
  animateNumber(el.conquerCount, mine);
  animateNumber(el.enemyConquerCount, enemy);
}

// ---------- Tam ekran (sunum modu) ----------
// iPhone Safari Fullscreen API'yi desteklemez; orada buton gizli kalır.
const fullscreenBtn = document.getElementById("fullscreen-btn");
if (document.fullscreenEnabled) fullscreenBtn.classList.remove("hidden");

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch (err) {
    /* tarayıcı izin vermedi — sessizce yok say */
  }
}
fullscreenBtn.addEventListener("click", () => {
  playSfxClick();
  toggleFullscreen();
});
document.addEventListener("fullscreenchange", () => {
  fullscreenBtn.classList.toggle("active", !!document.fullscreenElement);
  fullscreenBtn.setAttribute("aria-label", document.fullscreenElement ? "Tam ekrandan çık" : "Tam ekran");
});

// ---------- Klavye kısayolları (masaüstü / projeksiyon) ----------
// 1-4: şık seç · Enter: devam · Esc (tam ekranda Esc tarayıcıya gittiği
// için Backspace de olur): açık pencereyi kapat · F: tam ekran
const ESC_SAFE_MODALS = ["event-select-modal", "empty-modal", "result-modal", "era-modal", "leaderboard-modal"];

function topOpenModal(ids) {
  const open = [...document.querySelectorAll(".modal[data-dismiss]")].filter(
    (m) => isOpen(m) && (!ids || ids.includes(m.id))
  );
  return open[open.length - 1] || null;
}

function pressModalButton(modal) {
  const btn = document.getElementById(modal.dataset.dismiss);
  if (!btn) return;
  btn.classList.add("pressed");
  setTimeout(() => {
    btn.classList.remove("pressed");
    btn.click();
  }, 90);
}

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.altKey || e.metaKey || e.repeat) return;
  const typing = e.target instanceof HTMLInputElement;
  if (typing) return; // isim/oda kodu yazarken kısayollar devre dışı

  if (isOpen(el.quizModal) && !state.answered && /^[1-4]$/.test(e.key)) {
    const btn = el.quizOptions.querySelector(`.option-btn[data-num="${e.key}"]`);
    if (btn) {
      e.preventDefault();
      btn.classList.add("pressed");
      setTimeout(() => btn.click(), 80);
    }
    return;
  }

  if (e.key === "Enter") {
    if (!el.battleCry.classList.contains("hidden")) {
      e.preventDefault();
      finishBattleCry();
      return;
    }
    const modal = topOpenModal();
    if (modal) {
      e.preventDefault();
      pressModalButton(modal);
    }
    return;
  }

  if (e.key === "Escape" || e.key === "Backspace") {
    const modal = topOpenModal(ESC_SAFE_MODALS);
    if (modal) {
      e.preventDefault();
      pressModalButton(modal);
    }
    return;
  }

  if (e.key === "f" || e.key === "F") {
    if (document.fullscreenEnabled) toggleFullscreen();
  }
});
