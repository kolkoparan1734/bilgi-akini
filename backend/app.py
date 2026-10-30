"""
BİLGİ AKINI - Backend API
--------------------------
Flask tabanlı REST API. Dünya haritası üzerindeki ülkeler, dönemler,
tarihi olaylar (ve her olayın soruları) burada yönetilir.

Veritabanı: Varsayılan olarak SQLite (hızlı test için) kullanır.
PostgreSQL için DATABASE_URL ortam değişkenini ayarla (Render otomatik sağlar).
"""

import eventlet
eventlet.monkey_patch()

import os
import random
import time
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy import inspect as sa_inspect, text as sa_text

# Frontend klasörü de bu sunucudan servis edilir: tek port (5000), tek
# güvenlik duvarı izni; telefon http://<bilgisayar-ip>:5000 adresine girer.
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)  # Mobil uygulama / farklı origin'lerden erişim için
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# --- Veritabanı Ayarı ---
DEFAULT_SQLITE = "sqlite:///" + os.path.join(os.path.dirname(__file__), "bilgi_akini.db")
_db_url = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)
# Render'ın PostgreSQL URL'i "postgres://" ile gelir; SQLAlchemy "postgresql://" ister.
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- Kumandan (karakter) seçim mekaniği ---
# Sadece kozmetik: oyunu etkilemez, sadece oyuncunun kimliğini süsler.
# Frontend'deki CHARACTERS dizisiyle (game.js) anahtarlar birebir eşleşmeli.
ALLOWED_CHARACTERS = {
    "mete_han", "attila", "cengiz_han", "timur",
    "iskender", "jul_sezar", "fatih", "napolyon",
}


# ---------------- MODELLER ----------------

class Era(db.Model):
    """Dönem sekmesi: Antik / Orta Çağ / Yükseliş / Modern."""
    __tablename__ = "eras"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)
    order = db.Column(db.Integer, default=0)


class Country(db.Model):
    """Dünya haritasında tıklanabilir bir ülke/bölge noktası."""
    __tablename__ = "countries"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)
    x = db.Column(db.Float, nullable=False)  # harita görseli üzerinde % konum
    y = db.Column(db.Float, nullable=False)


class HistoricalEvent(db.Model):
    """Bir ülkenin bir dönemdeki fethedilebilir tarihi olayı/seferi."""
    __tablename__ = "historical_events"
    id = db.Column(db.Integer, primary_key=True)
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False)
    era_id = db.Column(db.Integer, db.ForeignKey("eras.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    leader = db.Column(db.String(80))  # padişah / lider / dönem simgesi (opsiyonel)
    gold_reward = db.Column(db.Integer, default=80)

    country = db.relationship("Country")
    era = db.relationship("Era")


class EventQuestion(db.Model):
    __tablename__ = "event_questions"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("historical_events.id"), nullable=False)
    order = db.Column(db.Integer, default=0)
    text = db.Column(db.String(300), nullable=False)
    option_a = db.Column(db.String(150), nullable=False)
    option_b = db.Column(db.String(150), nullable=False)
    option_c = db.Column(db.String(150), nullable=False)
    option_d = db.Column(db.String(150), nullable=False)
    correct = db.Column(db.String(1), nullable=False)  # 'a' | 'b' | 'c' | 'd'


class Player(db.Model):
    __tablename__ = "players"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    gold = db.Column(db.Integer, default=200)
    conquered_count = db.Column(db.Integer, default=0)
    best_score = db.Column(db.Integer, default=0)
    character_key = db.Column(db.String(30), nullable=True)  # seçilen kumandan (kozmetik)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PlayerEventProgress(db.Model):
    """Bir oyuncunun fethettiği tarihi olaylar (kim neyi almış)."""
    __tablename__ = "player_event_progress"
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("historical_events.id"), nullable=False)
    conquered_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------- YARDIMCI ----------------

def get_or_create_player(username):
    player = Player.query.filter_by(username=username).first()
    if not player:
        player = Player(username=username)
        db.session.add(player)
        db.session.commit()
    return player


def conquered_event_ids(player):
    return {p.event_id for p in PlayerEventProgress.query.filter_by(player_id=player.id)}


# --- Hız ve seri bonusları ---
# Olayın taban ödülü (gold_reward) değişmez; bunlar fetih başarılı olunca
# üstüne eklenir. Hızlı cevap: kalan süreye göre soru başına 0-10 altın.
# Seri: art arda 3. doğru cevaptan itibaren her doğru cevap +5 altın.
QUESTION_TIME = 15
SPEED_BONUS_MAX = 10
STREAK_MIN = 3
STREAK_BONUS = 5
WRONG_PENALTY = 20


def speed_bonus(seconds_left):
    try:
        t = float(seconds_left)
    except (TypeError, ValueError):
        return 0
    t = max(0.0, min(float(QUESTION_TIME), t))
    return round(t / QUESTION_TIME * SPEED_BONUS_MAX)


def streak_bonus(streak_before, correct_count):
    """streak_before: olaya girerken süren seri; correct_count: bu olayda
    art arda bilinen soru sayısı. Seri eşiği geçen her doğru için bonus."""
    bonus = 0
    s = max(0, min(int(streak_before or 0), 1000))
    for _ in range(correct_count):
        s += 1
        if s >= STREAK_MIN:
            bonus += STREAK_BONUS
    return bonus


# ---------------- API ROUTES ----------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/player/<username>", methods=["GET"])
def player_info(username):
    player = get_or_create_player(username)
    return jsonify({
        "id": player.id,
        "username": player.username,
        "gold": player.gold,
        "conquered_count": player.conquered_count,
        "character_key": player.character_key,
    })


@app.route("/api/player/<username>/character", methods=["POST"])
def set_player_character(username):
    """Kumandan seçimini kaydeder. Sadece kozmetik — oyunu etkilemez."""
    data = request.get_json(silent=True) or {}
    character_key = (data.get("character_key") or "").strip()
    if character_key not in ALLOWED_CHARACTERS:
        return jsonify({"error": "Geçersiz kumandan"}), 400

    player = get_or_create_player(username)
    player.character_key = character_key
    db.session.commit()
    return jsonify({"character_key": player.character_key})


@app.route("/api/eras", methods=["GET"])
def list_eras():
    eras = Era.query.order_by(Era.order).all()
    return jsonify([{"key": e.key, "name": e.name} for e in eras])


@app.route("/api/countries", methods=["GET"])
def list_countries():
    """Belirtilen dönemde haritadaki tüm ülkeleri, oyuncunun o dönemdeki
    fetih durumuyla birlikte döner."""
    username = request.args.get("username", "")
    era_key = request.args.get("era", "")

    era = Era.query.filter_by(key=era_key).first()
    conquered_ids = set()
    if username:
        player = get_or_create_player(username)
        conquered_ids = conquered_event_ids(player)

    countries = Country.query.all()
    result = []
    for c in countries:
        events = []
        if era:
            events = HistoricalEvent.query.filter_by(country_id=c.id, era_id=era.id).all()
        event_count = len(events)
        conquered_count = sum(1 for e in events if e.id in conquered_ids)
        if event_count == 0:
            status = "empty"  # bu dönemde bu ülke için henüz olay yok
        elif conquered_count == event_count:
            status = "conquered"
        else:
            status = "available"
        result.append({
            "id": c.id,
            "key": c.key,
            "name": c.name,
            "x": c.x,
            "y": c.y,
            "event_count": event_count,
            "status": status,
        })
    return jsonify(result)


@app.route("/api/countries/<int:country_id>/events", methods=["GET"])
def country_events(country_id):
    username = request.args.get("username", "")
    era_key = request.args.get("era", "")
    era = Era.query.filter_by(key=era_key).first()
    if not era:
        return jsonify({"error": "Geçersiz dönem"}), 400

    conquered_ids = set()
    if username:
        player = get_or_create_player(username)
        conquered_ids = conquered_event_ids(player)

    events = HistoricalEvent.query.filter_by(country_id=country_id, era_id=era.id).all()
    return jsonify([{
        "id": e.id,
        "title": e.title,
        "leader": e.leader,
        "gold_reward": e.gold_reward,
        "conquered": e.id in conquered_ids,
        "question_count": EventQuestion.query.filter_by(event_id=e.id).count(),
    } for e in events])


@app.route("/api/events/<int:event_id>", methods=["GET"])
def get_event(event_id):
    event = HistoricalEvent.query.get_or_404(event_id)
    questions = EventQuestion.query.filter_by(event_id=event.id).order_by(EventQuestion.order).all()
    return jsonify({
        "id": event.id,
        "title": event.title,
        "leader": event.leader,
        "country_name": event.country.name,
        "gold_reward": event.gold_reward,
        "questions": [{
            "id": q.id,
            "text": q.text,
            "options": {"a": q.option_a, "b": q.option_b, "c": q.option_c, "d": q.option_d},
        } for q in questions],
    })


@app.route("/api/questions/<int:question_id>/check", methods=["POST"])
def check_question(question_id):
    """Tek bir sorunun cevabını hafifçe kontrol eder (anlık geri bildirim
    için) — oyuncu durumunu değiştirmez, fetih kararı /answer'da kesinleşir."""
    data = request.get_json(force=True)
    chosen = data.get("chosen")
    question = EventQuestion.query.get_or_404(question_id)
    return jsonify({"correct": chosen == question.correct, "correct_option": question.correct})


@app.route("/api/events/<int:event_id>/answer", methods=["POST"])
def answer_event(event_id):
    """Bir olayın TÜM sorularının cevaplarını tek seferde alır; hepsi
    doğruysa olay fethedilir.
    Body: {username, answers: {question_id: chosen},
           times: {question_id: kalan_saniye}, streak: olaya girerken süren seri}"""
    data = request.get_json(force=True)
    username = data.get("username")
    answers = data.get("answers", {})  # {"12": "a", "13": "c", ...}
    times = data.get("times", {}) or {}

    event = HistoricalEvent.query.get_or_404(event_id)
    player = get_or_create_player(username)
    questions = EventQuestion.query.filter_by(event_id=event.id).all()

    results = {}
    all_correct = True
    for q in questions:
        chosen = answers.get(str(q.id))
        correct = chosen == q.correct
        if not correct:
            all_correct = False
        results[q.id] = {"correct": correct, "correct_option": q.correct}

    already = PlayerEventProgress.query.filter_by(player_id=player.id, event_id=event.id).first()
    fast = 0
    combo = 0
    penalty = 0
    if all_correct and not already:
        fast = sum(speed_bonus(times.get(str(q.id))) for q in questions)
        combo = streak_bonus(data.get("streak", 0), len(questions))
        db.session.add(PlayerEventProgress(player_id=player.id, event_id=event.id))
        player.conquered_count += 1
        player.gold += event.gold_reward + fast + combo
        player.best_score = max(player.best_score, player.conquered_count)
    elif not all_correct:
        penalty = min(WRONG_PENALTY, player.gold)  # başarısız fetih küçük gold cezası
        player.gold -= penalty

    db.session.commit()

    return jsonify({
        "all_correct": all_correct,
        "already_conquered": bool(already),
        "results": results,
        "gold": player.gold,
        "conquered_count": player.conquered_count,
        "gold_reward": event.gold_reward,
        "speed_bonus": fast,
        "streak_bonus": combo,
        "penalty": penalty,
    })


@app.route("/api/progress", methods=["GET"])
def era_progress():
    """Her dönem için: olayı olan ülke sayısı ve oyuncunun tamamen fethettiği
    ülke sayısı — dönem sekmelerindeki "7/11" göstergesi için."""
    username = request.args.get("username", "")
    conquered_ids = conquered_event_ids(get_or_create_player(username)) if username else set()
    result = {}
    for era in Era.query.order_by(Era.order).all():
        by_country = {}
        for e in HistoricalEvent.query.filter_by(era_id=era.id).all():
            by_country.setdefault(e.country_id, []).append(e.id)
        done = sum(1 for ids in by_country.values() if all(i in conquered_ids for i in ids))
        result[era.key] = {"name": era.name, "conquered": done, "total": len(by_country)}
    return jsonify(result)


@app.route("/api/server-info", methods=["GET"])
def server_info():
    """Oda ekranında ikinci oyuncuya hangi adrese girmesi gerektiğini göstermek için."""
    from netinfo import get_lan_ips
    port = request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"
    return jsonify({"lan_urls": [f"http://{ip}:{port}" for ip in get_lan_ips()]})


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    top = (Player.query.order_by(Player.best_score.desc(), Player.gold.desc())
           .limit(10).all())
    return jsonify([
        {"username": p.username, "best_score": p.best_score, "gold": p.gold,
         "conquered_count": p.conquered_count, "character_key": p.character_key}
        for p in top
    ])


@app.route("/api/countries/all", methods=["GET"])
def list_countries_raw():
    """Dönem/oyuncudan bağımsız, ham ülke listesi — 2 kişilik mod haritayı
    kendi oda durumuna göre çizmek için bunu kullanır."""
    countries = Country.query.all()
    return jsonify([{"id": c.id, "key": c.key, "name": c.name, "x": c.x, "y": c.y} for c in countries])


# ---------------- 2 KİŞİLİK MOD (Socket.IO) ----------------
# Maç durumu kalıcı DB'ye değil, sadece bu sözlüğe yazılır (oda bitince silinir).
# Kural: bir olaya dokunan oyuncu onu kilitler ("rakip deniyor"); tüm sorularını
# doğru bilirse olay onun olur, yanlış/süre biterse olay tekrar herkese açılır.

rooms = {}
MATCH_SECONDS = int(os.environ.get("BILGI_MATCH_SECONDS", 5 * 60))  # iki kişilik maçın süre sınırı


def make_room_code():
    while True:
        code = str(random.randint(1000, 9999))
        if code not in rooms:
            return code


def room_event_query(room):
    q = HistoricalEvent.query
    if room.get("era_id"):
        q = q.filter_by(era_id=room["era_id"])
    return q


def all_events_state(room):
    return [
        {
            "id": e.id,
            "country_id": e.country_id,
            "era_key": e.era.key,
            "title": e.title,
            "leader": e.leader,
            "gold_reward": e.gold_reward,
            "state": room["events"][e.id]["state"],
            "owner": room["events"][e.id]["owner"],
        }
        for e in room_event_query(room).all()
    ]


def finish_match(code, reason):
    """Maçı bitirir (tüm olaylar alındı ya da süre doldu) ve skorları yollar."""
    room = rooms.get(code)
    if not room or room.get("over"):
        return
    room["over"] = True
    scores = {p: 0 for p in room["players"]}
    gold = {p: 0 for p in room["players"]}
    for r in room["events"].values():
        if r["state"] == "conquered" and r["owner"] in scores:
            scores[r["owner"]] += 1
            gold[r["owner"]] += r.get("earned", 0)
    socketio.emit("match_over", {"scores": scores, "gold": gold, "reason": reason}, room=code)


def match_timer(code, started_at):
    socketio.sleep(MATCH_SECONDS)
    room = rooms.get(code)
    if room and room.get("started_at") == started_at:
        finish_match(code, "time")


def find_room_by_sid(sid):
    for code, room in rooms.items():
        if sid in room["sids"].values():
            return code, room
    return None, None


@socketio.on("create_room")
def handle_create_room(data):
    username = (data or {}).get("username", "").strip()
    if not username:
        emit("room_error", {"message": "Kullanıcı adı gerekli"})
        return

    era = Era.query.filter_by(key=(data or {}).get("era", "")).first()
    code = make_room_code()
    room = {
        "code": code,
        "players": [username],
        "sids": {username: request.sid},
        "era_id": era.id if era else None,
        "era_key": era.key if era else None,
        "era_name": era.name if era else "Tüm Dönemler",
        "over": False,
    }
    room["events"] = {
        e.id: {"state": "available", "owner": None, "excluded_qids": set()}
        for e in room_event_query(room).all()
    }
    rooms[code] = room
    join_room(code)
    emit("room_created", {"code": code, "username": username, "era_name": room["era_name"]})


@socketio.on("join_room_request")
def handle_join_room_request(data):
    data = data or {}
    username = data.get("username", "").strip()
    code = (data.get("code") or "").strip()
    room = rooms.get(code)

    if not username:
        emit("room_error", {"message": "Kullanıcı adı gerekli"})
        return
    if not room:
        emit("room_error", {"message": "Oda bulunamadı"})
        return
    if len(room["players"]) >= 2:
        emit("room_error", {"message": "Oda dolu"})
        return
    if username in room["players"]:
        emit("room_error", {"message": "Bu isim odada zaten var, başka isimle katıl"})
        return

    room["players"].append(username)
    room["sids"][username] = request.sid
    join_room(code)

    characters = {}
    for p_username in room["players"]:
        p = Player.query.filter_by(username=p_username).first()
        characters[p_username] = p.character_key if p else None

    started_at = time.time()
    room["started_at"] = started_at
    socketio.start_background_task(match_timer, code, started_at)

    emit("match_start", {
        "code": code,
        "players": room["players"],
        "characters": characters,
        "events": all_events_state(room),
        "era_key": room["era_key"],
        "era_name": room["era_name"],
        "seconds_left": MATCH_SECONDS,
    }, room=code)


@socketio.on("attack_event")
def handle_attack_event(data):
    data = data or {}
    code = (data.get("code") or "").strip()
    username = data.get("username")
    event_id = data.get("event_id")

    room = rooms.get(code)
    rs = room["events"].get(event_id) if room else None
    if not room or room.get("over") or not rs or rs["state"] != "available":
        emit("attack_denied", {"event_id": event_id})
        return

    event = HistoricalEvent.query.get(event_id)
    questions = EventQuestion.query.filter_by(event_id=event_id).order_by(EventQuestion.order).all()
    if not event or not questions:
        emit("attack_denied", {"event_id": event_id})
        return

    rs["state"] = "locked"
    rs["owner"] = username
    rs["qIndex"] = 0
    rs["bonus"] = 0
    rs["asked_at"] = time.time()
    emit("event_locked", {"event_id": event_id, "by": username}, room=code)

    q = questions[0]
    emit("question_ready", {
        "event_id": event_id,
        "question_id": q.id,
        "text": q.text,
        "options": {"a": q.option_a, "b": q.option_b, "c": q.option_c, "d": q.option_d},
        "index": 0,
        "total": len(questions),
        "title": event.title,
        "leader": event.leader,
    }, room=room["sids"][username])


@socketio.on("submit_answer")
def handle_submit_answer(data):
    data = data or {}
    code = (data.get("code") or "").strip()
    username = data.get("username")
    event_id = data.get("event_id")
    question_id = data.get("question_id")
    chosen = data.get("chosen")

    room = rooms.get(code)
    rs = room["events"].get(event_id) if room else None
    question = EventQuestion.query.get(question_id)
    event = HistoricalEvent.query.get(event_id)
    if not room or room.get("over") or not rs or not question or not event or rs["owner"] != username:
        return

    correct = (chosen == question.correct)
    if correct:
        # hız bonusunu sunucu kendi saatine göre hesaplar (istemciye güvenmeden)
        rs["bonus"] = rs.get("bonus", 0) + speed_bonus(QUESTION_TIME - (time.time() - rs.get("asked_at", time.time())))

    if not correct:
        rs["state"] = "available"
        rs["owner"] = None
        emit("event_result", {
            "event_id": event_id, "correct": False, "by": username, "correct_option": question.correct,
        }, room=code)
        return

    questions = EventQuestion.query.filter_by(event_id=event_id).order_by(EventQuestion.order).all()
    next_index = rs["qIndex"] + 1

    if next_index < len(questions):
        rs["qIndex"] = next_index
        rs["asked_at"] = time.time()
        # doğru: sıradaki soruyu sadece saldırana gönder (rakibe bilgi sızdırmadan).
        # İstemci, "question_ready" alması bir önceki cevabın doğru olduğu anlamına
        # geldiğini bilir (yanlışta her zaman event_result gelir).
        q = questions[next_index]
        emit("question_ready", {
            "event_id": event_id,
            "question_id": q.id,
            "text": q.text,
            "options": {"a": q.option_a, "b": q.option_b, "c": q.option_c, "d": q.option_d},
            "index": next_index,
            "total": len(questions),
            "title": event.title,
            "leader": event.leader,
        }, room=room["sids"][username])
        return

    # son soru da doğru: olay fethedildi
    rs["state"] = "conquered"
    rs["owner"] = username
    earned = event.gold_reward + rs.get("bonus", 0)
    rs["earned"] = earned
    player = Player.query.filter_by(username=username).first()
    if player:
        player.gold += earned
        db.session.commit()
    emit("event_result", {
        "event_id": event_id,
        "correct": True,
        "owner": username,
        "by": username,
        "gold_reward": earned,
        "base_reward": event.gold_reward,
        "speed_bonus": rs.get("bonus", 0),
        "correct_option": question.correct,
    }, room=code)

    if all(r["state"] == "conquered" for r in room["events"].values()):
        finish_match(code, "all")


@socketio.on("disconnect")
def handle_disconnect():
    code, room = find_room_by_sid(request.sid)
    if not room:
        return
    leaving = next((u for u, s in room["sids"].items() if s == request.sid), None)
    rooms.pop(code, None)
    if leaving:
        emit("opponent_left", {"username": leaving}, room=code)


# ---------------- SEED DATA ----------------

def seed_data():
    """Dönem/ülke/olay verisini doldurur. Idempotent: daha önce eklenmiş
    dönem/ülke/olaylar atlanır, sadece eksik olanlar eklenir — böylece
    içerik zamanla büyütülebilir, mevcut oyuncu ilerlemesi (gold, fetih
    durumu) korunur, db'yi silmeye gerek kalmaz."""
    if not Era.query.first():
        eras = [
            {"key": "antik", "name": "Antik", "order": 1},
            {"key": "ortacag", "name": "Orta Çağ", "order": 2},
            {"key": "yukselis", "name": "Yükseliş", "order": 3},
            {"key": "modern", "name": "Modern", "order": 4},
        ]
        for e in eras:
            db.session.add(Era(**e))
        db.session.commit()

    era_by_key = {e.key: e for e in Era.query.all()}

    # Haritadaki ülke noktaları (x, y: dünya haritası görseli üzerinde %).
    # Kürate edilmiş 12 bölge — mobil ekranda sıkışmasın diye sayı sınırlı
    # tutuldu. Bazılarının bu ilk sürümde henüz olayı yok; tıklanınca
    # "yakında" mesajı alır, içerik zamanla eklenir.
    if not Country.query.first():
        countries = [
            # Kuzey & Güney Amerika
            {"key": "amerika", "name": "Amerika Birleşik Devletleri", "x": 14, "y": 32},
            {"key": "meksika", "name": "Meksika", "x": 13, "y": 50},
            {"key": "brezilya", "name": "Brezilya", "x": 28, "y": 66},
            # Avrupa
            {"key": "turkiye", "name": "Türkiye / Osmanlı", "x": 58, "y": 42},
            {"key": "fransa", "name": "Fransa", "x": 46, "y": 30},
            {"key": "almanya", "name": "Almanya", "x": 53, "y": 23},
            {"key": "rusya", "name": "Rusya", "x": 68, "y": 15},
            # Orta Doğu & Afrika
            {"key": "misir", "name": "Mısır / Arap Yarımadası", "x": 57, "y": 52},
            {"key": "iran", "name": "İran / Persler", "x": 67, "y": 44},
            # Asya & Okyanusya
            {"key": "cin", "name": "Çin", "x": 80, "y": 34},
            {"key": "hindistan", "name": "Hindistan", "x": 71, "y": 50},
            {"key": "japonya", "name": "Japonya", "x": 90, "y": 30},
        ]
        for c in countries:
            db.session.add(Country(**c))
        db.session.commit()

    country_by_key = {c.key: c for c in Country.query.all()}

    events = [
        {
            "country": "fransa", "era": "yukselis",
            "title": "Fransız İhtilali", "leader": "XVI. Louis Dönemi", "gold_reward": 90,
            "questions": [
                {"text": "Fransız İhtilali hangi yılda başladı?",
                 "a": "1789", "b": "1799", "c": "1804", "d": "1776", "correct": "a"},
                {"text": "İhtilal sırasında halkın hapishane simgesi olarak bastığı kale hangisidir?",
                 "a": "Louvre", "b": "Bastille", "c": "Versay Sarayı", "d": "Notre-Dame", "correct": "b"},
                {"text": "İhtilalin sloganı olan üçlü ilke aşağıdakilerden hangisidir?",
                 "a": "Özgürlük, Eşitlik, Kardeşlik", "b": "Barış, Ekmek, Toprak",
                 "c": "Tanrı, Kral, Vatan", "d": "Birlik, Adalet, Güç", "correct": "a"},
                {"text": "İhtilal sonrası giyotinle idam edilen Fransa kralı kimdir?",
                 "a": "XIV. Louis", "b": "XV. Louis", "c": "XVI. Louis", "d": "Napolyon", "correct": "c"},
            ],
        },
        {
            "country": "turkiye", "era": "yukselis",
            "title": "Çaldıran Seferi", "leader": "Yavuz Sultan Selim", "gold_reward": 100,
            "questions": [
                {"text": "Çaldıran Savaşı hangi yıl gerçekleşti?",
                 "a": "1514", "b": "1453", "c": "1571", "d": "1526", "correct": "a"},
                {"text": "Çaldıran Savaşı Osmanlı ile hangi devlet arasında oldu?",
                 "a": "Memlük Devleti", "b": "Safevi Devleti", "c": "Bizans", "d": "Venedik", "correct": "b"},
                {"text": "Çaldıran Savaşı'ndaki Safevi hükümdarı kimdir?",
                 "a": "Şah İsmail", "b": "Şah Abbas", "c": "Nadir Şah", "d": "Şah Tahmasp", "correct": "a"},
                {"text": "Yavuz Sultan Selim'in Çaldıran sonrası yöneldiği coğrafya neresidir?",
                 "a": "Balkanlar", "b": "Kuzey Afrika", "c": "Doğu Anadolu ve Mısır yönü", "d": "Kırım", "correct": "c"},
            ],
        },
        {
            "country": "turkiye", "era": "ortacag",
            "title": "Belgrad Kuşatması", "leader": "Fatih Sultan Mehmed", "gold_reward": 85,
            "questions": [
                {"text": "Fatih Sultan Mehmed'in Belgrad Kuşatması hangi yıl yapıldı?",
                 "a": "1456", "b": "1444", "c": "1461", "d": "1480", "correct": "a"},
                {"text": "Belgrad Kuşatması hangi savunmacı komutana karşı başarısız oldu?",
                 "a": "Yanoş Hunyadi", "b": "Vlad Tepeş", "c": "II. Ulászló", "d": "Skenderbeg", "correct": "a"},
                {"text": "Fatih Sultan Mehmed İstanbul'u hangi yıl fethetmiştir?",
                 "a": "1453", "b": "1461", "c": "1456", "d": "1481", "correct": "a"},
                {"text": "Belgrad, Osmanlılar tarafından nihayet hangi padişah döneminde alınmıştır?",
                 "a": "Yavuz Sultan Selim", "b": "Kanuni Sultan Süleyman", "c": "II. Bayezid", "d": "III. Selim", "correct": "b"},
            ],
        },
        {
            "country": "turkiye", "era": "modern",
            "title": "I. Dünya Savaşı ve Kurtuluş", "leader": "Mustafa Kemal Atatürk", "gold_reward": 110,
            "questions": [
                {"text": "Osmanlı Devleti I. Dünya Savaşı'na hangi tarafta katıldı?",
                 "a": "İtilaf Devletleri", "b": "İttifak Devletleri", "c": "Tarafsız kaldı", "d": "Önce İtilaf sonra İttifak", "correct": "b"},
                {"text": "Çanakkale Savaşları hangi yıllarda gerçekleşti?",
                 "a": "1915", "b": "1918", "c": "1912", "d": "1922", "correct": "a"},
                {"text": "Mustafa Kemal, Kurtuluş Savaşı'nı başlatmak üzere Samsun'a hangi yıl çıktı?",
                 "a": "1918", "b": "1919", "c": "1920", "d": "1923", "correct": "b"},
                {"text": "Türkiye Cumhuriyeti hangi yıl ilan edildi?",
                 "a": "1922", "b": "1920", "c": "1923", "d": "1924", "correct": "c"},
            ],
        },
        {
            "country": "amerika", "era": "modern",
            "title": "Soğuk Savaş", "leader": "ABD - SSCB Rekabeti", "gold_reward": 100,
            "questions": [
                {"text": "Soğuk Savaş esas olarak hangi iki güç arasında yaşandı?",
                 "a": "ABD - SSCB", "b": "ABD - Çin", "c": "İngiltere - Almanya", "d": "Fransa - SSCB", "correct": "a"},
                {"text": "Berlin Duvarı hangi yıl yıkıldı?",
                 "a": "1985", "b": "1989", "c": "1991", "d": "1975", "correct": "b"},
                {"text": "Küba Füze Krizi hangi yıl yaşandı?",
                 "a": "1962", "b": "1958", "c": "1970", "d": "1965", "correct": "a"},
                {"text": "Soğuk Savaş döneminde Doğu Bloku'nu askeri olarak bir araya getiren pakt hangisidir?",
                 "a": "NATO", "b": "Varşova Paktı", "c": "SEATO", "d": "AGİT", "correct": "b"},
            ],
        },
        {
            "country": "misir", "era": "antik",
            "title": "Antik Mısır ve Piramitler", "leader": "Firavunlar", "gold_reward": 70,
            "questions": [
                {"text": "Mısır piramitlerinin en büyüğü hangisidir?",
                 "a": "Keops (Büyük Piramit)", "b": "Kefren", "c": "Mikerinos", "d": "Sakkara", "correct": "a"},
                {"text": "Antik Mısır'ı yöneten krallara ne ad verilirdi?",
                 "a": "Şah", "b": "Firavun", "c": "İmparator", "d": "Sultan", "correct": "b"},
                {"text": "Mısır uygarlığı hangi nehir kıyısında gelişmiştir?",
                 "a": "Fırat", "b": "Dicle", "c": "Nil", "d": "Ganj", "correct": "c"},
                {"text": "Antik Mısır'da kullanılan resim yazısına ne ad verilir?",
                 "a": "Çivi yazısı", "b": "Hiyeroglif", "c": "Kiril", "d": "Rün", "correct": "b"},
            ],
        },
        {
            "country": "iran", "era": "antik",
            "title": "Pers İmparatorluğu", "leader": "Büyük Kiros", "gold_reward": 70,
            "questions": [
                {"text": "Pers İmparatorluğu'nun kurucusu kimdir?",
                 "a": "Büyük Kiros", "b": "Dara I", "c": "Büyük İskender", "d": "Kserkses", "correct": "a"},
                {"text": "Pers İmparatorluğu'nu yıkan Makedon kral kimdir?",
                 "a": "II. Filip", "b": "Büyük İskender", "c": "Pyrrhus", "d": "I. Ptolemaios", "correct": "b"},
                {"text": "Persler ile Antik Yunanlılar arasındaki ünlü savaşlardan biri hangisidir?",
                 "a": "Truva Savaşı", "b": "Maraton Savaşı", "c": "Pön Savaşları", "d": "Peloponez Savaşı", "correct": "b"},
                {"text": "Pers İmparatorluğu'nun başkentlerinden biri hangisidir?",
                 "a": "Persepolis", "b": "Atina", "c": "Roma", "d": "Babil", "correct": "a"},
            ],
        },
        {
            "country": "cin", "era": "antik",
            "title": "İlk Çin Hanedanlıkları", "leader": "Qin Shi Huang", "gold_reward": 70,
            "questions": [
                {"text": "Çin'i ilk kez birleştiren imparator kimdir?",
                 "a": "Qin Shi Huang", "b": "Konfüçyüs", "c": "Kubilay Han", "d": "Mao Zedong", "correct": "a"},
                {"text": "Çin Seddi temel olarak hangi amaçla inşa edilmiştir?",
                 "a": "Ticaret", "b": "Kuzeyden gelen istilalara karşı savunma", "c": "Sulama", "d": "Dini tören", "correct": "b"},
                {"text": "Ahlak ve devlet düzeni üzerine öğretileriyle tanınan Çinli filozof kimdir?",
                 "a": "Laozi", "b": "Konfüçyüs", "c": "Sun Tzu", "d": "Mengzi", "correct": "b"},
                {"text": "Ünlü Terakota Ordusu hangi imparatorun mezarında bulunmuştur?",
                 "a": "Han Wudi", "b": "Qin Shi Huang", "c": "Kangxi", "d": "Kubilay Han", "correct": "b"},
            ],
        },
        {
            "country": "meksika", "era": "yukselis",
            "title": "Aztek İmparatorluğu ve İspanyol Fethi", "leader": "Hernán Cortés", "gold_reward": 90,
            "questions": [
                {"text": "Aztek İmparatorluğu'nun başkenti hangi şehirdi?",
                 "a": "Tenochtitlan", "b": "Cusco", "c": "Teotihuacan", "d": "Chichen Itza", "correct": "a"},
                {"text": "Aztek İmparatorluğu'nu fetheden İspanyol conquistador kimdir?",
                 "a": "Francisco Pizarro", "b": "Hernán Cortés", "c": "Kristof Kolomb", "d": "Vasco da Gama", "correct": "b"},
                {"text": "Aztek İmparatorluğu İspanyollar tarafından hangi yıl yıkıldı?",
                 "a": "1492", "b": "1521", "c": "1533", "d": "1600", "correct": "b"},
                {"text": "İspanyollar geldiğinde tahtta olan Aztek imparatoru kimdir?",
                 "a": "Montezuma II", "b": "Atahualpa", "c": "Pachacuti", "d": "Cuauhtémoc", "correct": "a"},
            ],
        },
        {
            "country": "hindistan", "era": "ortacag",
            "title": "Baharat Yolu ve Keşifler", "leader": "Ticaret Çağı", "gold_reward": 85,
            "questions": [
                {"text": "Avrupalıların Hindistan'a deniz yoluyla ulaşmasını sağlayan kaşif kimdir?",
                 "a": "Vasco da Gama", "b": "Kristof Kolomb", "c": "Ferdinand Magellan", "d": "Marco Polo", "correct": "a"},
                {"text": "Baharat Yolu'nda en çok aranan ürünlerden biri hangisidir?",
                 "a": "Karabiber", "b": "Şeker", "c": "Pamuk", "d": "İpek", "correct": "a"},
                {"text": "Hindistan'a kara yoluyla ulaşan, seyahatnamesiyle ünlenen Venedikli gezgin kimdir?",
                 "a": "Marco Polo", "b": "Vasco da Gama", "c": "İbn-i Battuta", "d": "Kristof Kolomb", "correct": "a"},
                {"text": "Osmanlıların Baharat Yolu'nu kontrol etmesi Avrupalıları hangi sonuca yöneltmiştir?",
                 "a": "Yeni deniz yolları aramaya", "b": "Ticareti bırakmaya",
                 "c": "Hindistan'ı işgalden vazgeçmeye", "d": "Baharat kullanmayı bırakmaya", "correct": "a"},
            ],
        },
        {
            "country": "japonya", "era": "ortacag",
            "title": "Samuray Dönemi", "leader": "Şogunlar", "gold_reward": 85,
            "questions": [
                {"text": "Japonya'da feodal dönemde savaşçı sınıfına ne ad verilir?",
                 "a": "Samuray", "b": "Ronin", "c": "Şogun", "d": "Daimyo", "correct": "a"},
                {"text": "Samurayların bağlı olduğu ahlaki kod nedir?",
                 "a": "Bushido", "b": "Zen", "c": "Şinto", "d": "Kabuki", "correct": "a"},
                {"text": "Japonya'yı fiilen yöneten askeri lider unvanı nedir?",
                 "a": "Şogun", "b": "İmparator", "c": "Daimyo", "d": "Kral", "correct": "a"},
                {"text": "Japonya'da Edo döneminde ülkeyi dış dünyaya kapatan politikaya ne ad verilir?",
                 "a": "Sakoku", "b": "Meiji", "c": "Bushido", "d": "Kamikaze", "correct": "a"},
            ],
        },
        {
            "country": "almanya", "era": "modern",
            "title": "II. Dünya Savaşı", "leader": "Dönem Liderleri", "gold_reward": 110,
            "questions": [
                {"text": "II. Dünya Savaşı hangi yıl başladı?",
                 "a": "1939", "b": "1914", "c": "1945", "d": "1929", "correct": "a"},
                {"text": "II. Dünya Savaşı, Almanya'nın hangi ülkeyi işgaliyle başladı?",
                 "a": "Fransa", "b": "Polonya", "c": "Belçika", "d": "Danimarka", "correct": "b"},
                {"text": "II. Dünya Savaşı hangi yıl sona erdi?",
                 "a": "1943", "b": "1944", "c": "1945", "d": "1946", "correct": "c"},
                {"text": "Berlin'in düşmesiyle sonuçlanan kuşatmayı hangi ülkenin orduları gerçekleştirdi?",
                 "a": "ABD", "b": "İngiltere", "c": "SSCB", "d": "Fransa", "correct": "c"},
            ],
        },
        {
            "country": "rusya", "era": "modern",
            "title": "Rus Devrimi ve SSCB", "leader": "Lenin", "gold_reward": 100,
            "questions": [
                {"text": "Rus Devrimi hangi yıl gerçekleşti?",
                 "a": "1905", "b": "1917", "c": "1922", "d": "1929", "correct": "b"},
                {"text": "Rus Devrimi'nin lideri kimdir?",
                 "a": "Stalin", "b": "Lenin", "c": "Troçki", "d": "Kerenski", "correct": "b"},
                {"text": "Devrim sonrası kurulan devletin adı nedir?",
                 "a": "Rusya İmparatorluğu", "b": "Sovyet Sosyalist Cumhuriyetler Birliği",
                 "c": "Rusya Federasyonu", "d": "Slav Birliği", "correct": "b"},
                {"text": "Rus Devrimi'nde tahttan indirilen son Çar kimdir?",
                 "a": "II. Nikolay", "b": "III. Aleksandr", "c": "I. Petro", "d": "Büyük Katerina", "correct": "a"},
            ],
        },
        {
            "country": "brezilya", "era": "modern",
            "title": "Brezilya'nın Bağımsızlığı", "leader": "I. Pedro", "gold_reward": 85,
            "questions": [
                {"text": "Brezilya hangi ülkenin sömürgesiydi?",
                 "a": "İspanya", "b": "Portekiz", "c": "Fransa", "d": "Hollanda", "correct": "b"},
                {"text": "Brezilya bağımsızlığını hangi yıl ilan etti?",
                 "a": "1822", "b": "1889", "c": "1776", "d": "1810", "correct": "a"},
                {"text": "Brezilya'nın bağımsızlığını ilan eden kişi kimdir?",
                 "a": "Simón Bolívar", "b": "Dom Pedro I", "c": "José de San Martín", "d": "Getúlio Vargas", "correct": "b"},
                {"text": "Brezilya, Latin Amerika'da hangi dille öne çıkan tek büyük ülkedir?",
                 "a": "İspanyolca", "b": "Portekizce", "c": "Fransızca", "d": "İtalyanca", "correct": "b"},
            ],
        },
        # ---- Boş ülke×dönem hücrelerini dolduran yeni olaylar ----
        {
            "country": "amerika", "era": "antik",
            "title": "Yerli Amerikan Medeniyetleri", "leader": "Kızılderili Kabileleri", "gold_reward": 70,
            "questions": [
                {"text": "Kuzey Amerika'nın en büyük yerli şehir-merkezlerinden Cahokia hangi nehir kıyısındaydı?",
                 "a": "Mississippi", "b": "Missouri", "c": "Colorado", "d": "Rio Grande", "correct": "a"},
                {"text": "Kuzey Amerika yerlilerine Avrupalılar tarafından hangi isim yaygın olarak verilmiştir?",
                 "a": "Kızılderili", "b": "Aborjin", "c": "İnka", "d": "Maya", "correct": "a"},
                {"text": "İroki Konfederasyonu klasik dönemde kaç kabileden oluşuyordu?",
                 "a": "3", "b": "5", "c": "7", "d": "10", "correct": "b"},
                {"text": "Büyük Ovalar'da yaşayan yerli halkların temel geçim kaynağı hangi hayvandı?",
                 "a": "At", "b": "Bizon", "c": "Geyik", "d": "Koyun", "correct": "b"},
            ],
        },
        {
            "country": "amerika", "era": "ortacag",
            "title": "Viking Keşifleri (Vinland)", "leader": "Leif Erikson", "gold_reward": 80,
            "questions": [
                {"text": "Kolomb'dan yaklaşık 500 yıl önce Kuzey Amerika kıyılarına ulaştığı düşünülen halk hangisidir?",
                 "a": "Vikingler", "b": "Fenikeliler", "c": "Romalılar", "d": "Araplar", "correct": "a"},
                {"text": "Vikinglerin Kuzey Amerika'da ulaştığı bölgeye verdikleri isim nedir?",
                 "a": "Vinland", "b": "Groenland", "c": "Nova Scotia", "d": "Newfoundland", "correct": "a"},
                {"text": "Vinland'a ulaştığı kabul edilen Viking kaşif kimdir?",
                 "a": "Leif Erikson", "b": "Erik the Red", "c": "Ragnar Lodbrok", "d": "Rollo", "correct": "a"},
                {"text": "Vikingler esas olarak hangi bölgeden yayılmışlardır?",
                 "a": "İskandinavya", "b": "İber Yarımadası", "c": "Britanya Adaları", "d": "Kuzey Afrika", "correct": "a"},
            ],
        },
        {
            "country": "amerika", "era": "yukselis",
            "title": "Amerika'nın Keşfi", "leader": "Kristof Kolomb", "gold_reward": 90,
            "questions": [
                {"text": "Kristof Kolomb Amerika kıtasına hangi yıl ayak bastı?",
                 "a": "1492", "b": "1498", "c": "1500", "d": "1512", "correct": "a"},
                {"text": "Kolomb hangi ülke adına sefere çıkmıştır?",
                 "a": "Portekiz", "b": "İspanya", "c": "İngiltere", "d": "Fransa", "correct": "b"},
                {"text": "Kolomb'un ilk ulaştığı toprakları hangi kıta zannettiği bilinir?",
                 "a": "Afrika", "b": "Asya (Hindistan)", "c": "Avustralya", "d": "Antarktika", "correct": "b"},
                {"text": "Amerika kıtasına adını veren kaşif kimdir?",
                 "a": "Amerigo Vespucci", "b": "Vasco da Gama", "c": "Ferdinand Magellan", "d": "Juan Ponce de León", "correct": "a"},
            ],
        },
        {
            "country": "meksika", "era": "antik",
            "title": "Maya Uygarlığı", "leader": "Maya Şehir Devletleri", "gold_reward": 70,
            "questions": [
                {"text": "Maya Uygarlığı esas olarak hangi bölgede gelişmiştir?",
                 "a": "And Dağları", "b": "Orta Amerika (Yukatan)", "c": "Amazon Havzası", "d": "Kuzey Amerika Ovaları", "correct": "b"},
                {"text": "Mayaların geliştirdiği ve sıfır kavramını içeren şey nedir?",
                 "a": "Takvim ve sayı sistemi", "b": "Metal para", "c": "Tekerlek", "d": "Yazı çarkı", "correct": "a"},
                {"text": "Ünlü Maya piramidi Chichen Itza hangi günümüz ülkesindedir?",
                 "a": "Guatemala", "b": "Meksika", "c": "Honduras", "d": "Belize", "correct": "b"},
                {"text": "Maya uygarlığı en çok hangi alanda ileri gitmiştir?",
                 "a": "Astronomi ve takvim", "b": "Denizcilik", "c": "Demir işleme", "d": "Atçılık", "correct": "a"},
            ],
        },
        {
            "country": "meksika", "era": "ortacag",
            "title": "Aztek İmparatorluğu'nun Doğuşu", "leader": "Tenoch", "gold_reward": 80,
            "questions": [
                {"text": "Aztekler başkentleri Tenochtitlan'ı hangi göl üzerinde kurmuşlardır?",
                 "a": "Texcoco Gölü", "b": "Titicaca Gölü", "c": "Maracaibo Gölü", "d": "Managua Gölü", "correct": "a"},
                {"text": "Aztek efsanesine göre şehrin kurulacağı yeri, kaktüs üzerinde ne yiyen bir kartal gösterir?",
                 "a": "Balık", "b": "Yılan", "c": "Fare", "d": "Tavşan", "correct": "b"},
                {"text": "Aztek toplumunda güneş tanrısına insan kurban etme geleneği hangi amaçla yapılırdı?",
                 "a": "Güneşin doğmaya devam etmesi için", "b": "Savaş kazanmak için", "c": "Bereket için", "d": "Yağmur için", "correct": "a"},
                {"text": "Aztek İmparatorluğu'nun kuruluşu yaklaşık hangi yüzyıla dayanır?",
                 "a": "11. yüzyıl", "b": "14. yüzyıl", "c": "16. yüzyıl", "d": "9. yüzyıl", "correct": "b"},
            ],
        },
        {
            "country": "meksika", "era": "modern",
            "title": "Meksika Devrimi", "leader": "Pancho Villa & Zapata", "gold_reward": 100,
            "questions": [
                {"text": "Meksika Devrimi hangi yıl başladı?",
                 "a": "1910", "b": "1920", "c": "1900", "d": "1930", "correct": "a"},
                {"text": "\"Toprak ve Özgürlük\" sloganıyla köylü hareketini yöneten devrimci kimdir?",
                 "a": "Pancho Villa", "b": "Emiliano Zapata", "c": "Porfirio Díaz", "d": "Venustiano Carranza", "correct": "b"},
                {"text": "Devrim öncesi Meksika'yı uzun süre diktatörlükle yöneten lider kimdir?",
                 "a": "Porfirio Díaz", "b": "Santa Anna", "c": "Benito Juárez", "d": "Maximilian", "correct": "a"},
                {"text": "Meksika Devrimi sonucunda kabul edilen ve sosyal hakları güvence altına alan belge nedir?",
                 "a": "1917 Anayasası", "b": "Bağımsızlık Bildirgesi", "c": "Guadalupe Hidalgo Antlaşması", "d": "Plan de Ayala", "correct": "a"},
            ],
        },
        {
            "country": "brezilya", "era": "antik",
            "title": "Amazon'un Yerli Halkları", "leader": "Tupi-Guarani Kabileleri", "gold_reward": 70,
            "questions": [
                {"text": "Portekizliler gelmeden önce Brezilya topraklarında en yaygın yerli halk grubu hangisidir?",
                 "a": "Tupi-Guarani", "b": "Maya", "c": "İnka", "d": "Aztek", "correct": "a"},
                {"text": "Amazon yağmur ormanlarında yaşayan yerli halkların temel geçim şekli nedir?",
                 "a": "Avcılık-toplayıcılık ve tarım", "b": "Göçebe hayvancılık", "c": "Balıkçılık ve maden işletmeciliği", "d": "Ticaret kervanları", "correct": "a"},
                {"text": "Brezilya'nın adı hangi ağaçtan gelmektedir?",
                 "a": "Pau-brasil (Brezilya ağacı)", "b": "Kauçuk ağacı", "c": "Maun ağacı", "d": "Palmiye", "correct": "a"},
                {"text": "Portekizliler Brezilya'ya ayak bastığında (1500) yerli nüfusun büyük kısmı hangi dil ailesine mensuptu?",
                 "a": "Tupi", "b": "Nahuatl", "c": "Keçuva", "d": "Maya dilleri", "correct": "a"},
            ],
        },
        {
            "country": "brezilya", "era": "yukselis",
            "title": "Portekiz Sömürgeciliği ve Şeker Çağı", "leader": "Vali-Genel", "gold_reward": 85,
            "questions": [
                {"text": "Brezilya'yı ilk kez keşfeden Portekizli denizci kimdir?",
                 "a": "Pedro Álvares Cabral", "b": "Vasco da Gama", "c": "Bartolomeu Dias", "d": "Fernão de Magalhães", "correct": "a"},
                {"text": "Sömürge döneminde Brezilya ekonomisinin temelini hangi ürün oluşturuyordu?",
                 "a": "Kahve", "b": "Şeker kamışı", "c": "Kauçuk", "d": "Pamuk", "correct": "b"},
                {"text": "Brezilya'ya Portekizliler tarafından hangi kıtadan köle emeği getirilmiştir?",
                 "a": "Asya", "b": "Afrika", "c": "Avustralya", "d": "Kuzey Amerika", "correct": "b"},
                {"text": "Brezilya, Portekiz'in hangi kıtadaki en büyük sömürgesiydi?",
                 "a": "Afrika", "b": "Güney Amerika", "c": "Asya", "d": "Okyanusya", "correct": "b"},
            ],
        },
        {
            "country": "turkiye", "era": "antik",
            "title": "Anadolu'nun Antik Uygarlıkları", "leader": "Hititler", "gold_reward": 75,
            "questions": [
                {"text": "Anadolu'da kurulan ve Mısır ile Kadeş Antlaşması'nı imzalayan antik uygarlık hangisidir?",
                 "a": "Hititler", "b": "Frigyalılar", "c": "Lidyalılar", "d": "İyonlar", "correct": "a"},
                {"text": "Tarihte bilinen ilk yazılı barış antlaşması olan Kadeş Antlaşması kimler arasında imzalanmıştır?",
                 "a": "Hititler-Mısırlılar", "b": "Persler-Yunanlılar", "c": "Asurlular-Babilliler", "d": "Hititler-Asurlular", "correct": "a"},
                {"text": "Parayı ilk kez icat ettiği kabul edilen Anadolu uygarlığı hangisidir?",
                 "a": "Lidyalılar", "b": "Frigyalılar", "c": "Urartular", "d": "İyonlar", "correct": "a"},
                {"text": "Efsanevi kral Midas'ın altına dokunuşuyla anılan Anadolu uygarlığı hangisidir?",
                 "a": "Frigyalılar", "b": "Hititler", "c": "Lidyalılar", "d": "Karyalılar", "correct": "a"},
            ],
        },
        {
            "country": "fransa", "era": "antik",
            "title": "Galya ve Roma Fransası", "leader": "Vercingetorix", "gold_reward": 70,
            "questions": [
                {"text": "Roma işgali öncesi bugünkü Fransa toprakları hangi isimle anılırdı?",
                 "a": "Galya", "b": "Germanya", "c": "Britanya", "d": "İberya", "correct": "a"},
                {"text": "Galyalıların Roma'ya karşı direnişini yöneten ünlü şef kimdir?",
                 "a": "Vercingetorix", "b": "Asterix", "c": "Karl Martel", "d": "Klovis", "correct": "a"},
                {"text": "Galya'yı fetheden Roma komutanı kimdir?",
                 "a": "Jül Sezar", "b": "Augustus", "c": "Hannibal", "d": "Pompeius", "correct": "a"},
                {"text": "Galya'nın Roma'ya kesin olarak boyun eğdiği kuşatma hangisidir?",
                 "a": "Alesia Kuşatması", "b": "Cannae Savaşı", "c": "Actium Savaşı", "d": "Zama Savaşı", "correct": "a"},
            ],
        },
        {
            "country": "fransa", "era": "ortacag",
            "title": "Yüzyıl Savaşları ve Jeanne d'Arc", "leader": "Jeanne d'Arc", "gold_reward": 85,
            "questions": [
                {"text": "İngiltere ile Fransa arasındaki Yüzyıl Savaşları toplamda yaklaşık kaç yıl sürmüştür?",
                 "a": "100", "b": "50", "c": "150", "d": "30", "correct": "a"},
                {"text": "Fransız ordularına önderlik ederek ülkesini kurtaran genç kız kahraman kimdir?",
                 "a": "Jeanne d'Arc", "b": "Marie Antoinette", "c": "Katerina de Medici", "d": "Eleanor of Aquitaine", "correct": "a"},
                {"text": "Jeanne d'Arc savaş sonunda hangi suçlamayla yakılarak idam edilmiştir?",
                 "a": "Cadılık/sapkınlık", "b": "Vatana ihanet", "c": "Hırsızlık", "d": "Casusluk", "correct": "a"},
                {"text": "Yüzyıl Savaşları hangi hanedanlar arasındaki taht iddiası yüzünden başlamıştır?",
                 "a": "Plantagenet-Valois", "b": "Tudor-Stuart", "c": "Habsburg-Bourbon", "d": "Capet-Habsburg", "correct": "a"},
            ],
        },
        {
            "country": "fransa", "era": "modern",
            "title": "Napolyon Dönemi", "leader": "Napolyon Bonapart", "gold_reward": 100,
            "questions": [
                {"text": "Napolyon Bonapart kendini hangi yıl Fransız İmparatoru ilan etmiştir?",
                 "a": "1804", "b": "1789", "c": "1815", "d": "1799", "correct": "a"},
                {"text": "Napolyon'un kesin yenilgiye uğradığı savaş hangisidir?",
                 "a": "Waterloo", "b": "Austerlitz", "c": "Trafalgar", "d": "Leipzig", "correct": "a"},
                {"text": "Napolyon son olarak hangi adaya sürgün edilmiştir?",
                 "a": "Elba", "b": "Korsika", "c": "Sen Helena", "d": "Sicilya", "correct": "c"},
                {"text": "Napolyon'un hazırlattığı ve modern hukukun temellerinden sayılan kanun hangisidir?",
                 "a": "Code Civil (Napolyon Kanunu)", "b": "Magna Carta", "c": "Hammurabi Kanunları", "d": "Justinianus Kanunları", "correct": "a"},
            ],
        },
        {
            "country": "almanya", "era": "antik",
            "title": "Germen Kabileleri ve Roma", "leader": "Arminius", "gold_reward": 70,
            "questions": [
                {"text": "Roma lejyonlarını Teutoburg Ormanı'nda yenen Germen lider kimdir?",
                 "a": "Arminius", "b": "Attila", "c": "Alarik", "d": "Odoaker", "correct": "a"},
                {"text": "Roma İmparatorluğu, Ren Nehri'nin doğusunu genel olarak neden kalıcı işgal edememiştir?",
                 "a": "Germen kabilelerinin güçlü direnişi", "b": "İklim çok soğuk olduğu için", "c": "Bölgede değerli kaynak olmadığı için", "d": "Barış anlaşması yüzünden", "correct": "a"},
                {"text": "Antik dönemde Germen kabilelerinin toplumsal yapısı genelde nasıldı?",
                 "a": "Kabile/boy temelli, merkezi olmayan", "b": "Güçlü merkezi imparatorluk", "c": "Şehir devletleri", "d": "Göçebe imparatorluk", "correct": "a"},
                {"text": "Roma kaynaklarında Germen kabileleri hakkında bilgi veren ünlü eser kime aittir?",
                 "a": "Tacitus (Germania)", "b": "Herodot", "c": "Julius Sezar", "d": "Plinius", "correct": "a"},
            ],
        },
        {
            "country": "almanya", "era": "ortacag",
            "title": "Kutsal Roma-Germen İmparatorluğu", "leader": "Şarlman / Otto", "gold_reward": 85,
            "questions": [
                {"text": "Kutsal Roma-Germen İmparatorluğu'nun kurucusu kabul edilen imparator kimdir?",
                 "a": "Büyük Otto", "b": "Şarlman", "c": "Barbaros Friedrich", "d": "V. Karl", "correct": "b"},
                {"text": "Şarlman hangi yılda Papa tarafından Roma İmparatoru olarak taçlandırılmıştır?",
                 "a": "800", "b": "962", "c": "1000", "d": "1215", "correct": "a"},
                {"text": "Kutsal Roma-Germen İmparatorluğu esas olarak hangi bölgeleri kapsıyordu?",
                 "a": "Orta Avrupa (Almanya, Avusturya ve çevresi)", "b": "İber Yarımadası", "c": "Britanya Adaları", "d": "Balkanlar", "correct": "a"},
                {"text": "Ortaçağ Almanya'sında imparatoru seçen soylulara ne ad verilirdi?",
                 "a": "Prens-Seçmenler (Kurfürst)", "b": "Baronlar", "c": "Şövalyeler", "d": "Dükler Konseyi", "correct": "a"},
            ],
        },
        {
            "country": "almanya", "era": "yukselis",
            "title": "Reform ve Otuz Yıl Savaşları", "leader": "Martin Luther", "gold_reward": 90,
            "questions": [
                {"text": "Reform hareketini başlatan ve 95 Tezi yayınlayan din adamı kimdir?",
                 "a": "Martin Luther", "b": "Jean Calvin", "c": "Papa X. Leo", "d": "Erasmus", "correct": "a"},
                {"text": "Otuz Yıl Savaşları hangi yüzyılda yaşanmıştır?",
                 "a": "17. yüzyıl", "b": "16. yüzyıl", "c": "18. yüzyıl", "d": "15. yüzyıl", "correct": "a"},
                {"text": "Otuz Yıl Savaşları'nı sona erdiren antlaşma hangisidir?",
                 "a": "Vestfalya Antlaşması", "b": "Utrecht Antlaşması", "c": "Tilsit Antlaşması", "d": "Versay Antlaşması", "correct": "a"},
                {"text": "Martin Luther'in Katolik Kilisesi'ne karşı en çok eleştirdiği uygulama neydi?",
                 "a": "Endüljans (günah affı) satışı", "b": "Latince ayin", "c": "Manastır sistemi", "d": "Haçlı Seferleri", "correct": "a"},
            ],
        },
        {
            "country": "rusya", "era": "antik",
            "title": "Bozkırın Antik Halkları: İskitler", "leader": "İskit Göçebeleri", "gold_reward": 70,
            "questions": [
                {"text": "Bugünkü Rusya bozkırlarında at ve okçulukla ünlenen antik göçebe halk hangisidir?",
                 "a": "İskitler", "b": "Vikingler", "c": "Moğollar", "d": "Hunlar", "correct": "a"},
                {"text": "İskitler hangi hayvanı evcilleştirerek savaş ve göçte ustaca kullanmışlardır?",
                 "a": "At", "b": "Fil", "c": "Deve", "d": "Öküz", "correct": "a"},
                {"text": "İskitlerin sanatında en çok görülen figür hangisidir?",
                 "a": "Hayvan üslubu (kartal, geyik vb.)", "b": "İnsan heykelleri", "c": "Geometrik mozaikler", "d": "Dini simgeler", "correct": "a"},
                {"text": "İskitler hakkında en çok bilgiyi veren antik Yunan tarihçi kimdir?",
                 "a": "Herodot", "b": "Tukidides", "c": "Ksenophon", "d": "Plutarkhos", "correct": "a"},
            ],
        },
        {
            "country": "rusya", "era": "ortacag",
            "title": "Kiev Rus Knezliği", "leader": "Vladimir", "gold_reward": 85,
            "questions": [
                {"text": "Rus devletinin ilk çekirdeği kabul edilen ortaçağ knezliği hangisidir?",
                 "a": "Kiev Rus Knezliği", "b": "Moskova Knezliği", "c": "Novgorod Cumhuriyeti", "d": "Altın Orda", "correct": "a"},
                {"text": "Rusya'yı Hristiyanlığı (Ortodoksluk) kabul etmeye yönelten Kiev knezi kimdir?",
                 "a": "Vladimir", "b": "Yaroslav", "c": "İvan IV", "d": "İgor", "correct": "a"},
                {"text": "Ortaçağda Rus knezliklerini uzun süre haraca bağlayan Moğol-Türk devleti hangisidir?",
                 "a": "Altın Orda", "b": "Timur İmparatorluğu", "c": "Göktürk Kağanlığı", "d": "Selçuklu Devleti", "correct": "a"},
                {"text": "\"Bütün Rusların Çarı\" unvanını ilk resmi kullanan hükümdar kimdir?",
                 "a": "IV. İvan (Korkunç İvan)", "b": "Büyük Petro", "c": "Vladimir", "d": "Yaroslav", "correct": "a"},
            ],
        },
        {
            "country": "rusya", "era": "yukselis",
            "title": "Büyük Petro ve Rusya'nın Modernleşmesi", "leader": "I. Petro", "gold_reward": 95,
            "questions": [
                {"text": "Rusya'yı Batılılaştırma politikalarıyla modernleştiren çar kimdir?",
                 "a": "Büyük Petro", "b": "Büyük Katerina", "c": "IV. İvan", "d": "I. Aleksandr", "correct": "a"},
                {"text": "Büyük Petro'nun Baltık kıyısında kurdurduğu ve başkent yaptığı şehir hangisidir?",
                 "a": "St. Petersburg", "b": "Moskova", "c": "Kiev", "d": "Novgorod", "correct": "a"},
                {"text": "Büyük Petro, İsveç'e karşı kazandığı hangi savaşla Rusya'yı büyük güç hâline getirmiştir?",
                 "a": "Büyük Kuzey Savaşı", "b": "Kırım Savaşı", "c": "Yedi Yıl Savaşları", "d": "Napolyon Savaşları", "correct": "a"},
                {"text": "Büyük Petro dönemi reformları özellikle hangi alanda yoğunlaşmıştır?",
                 "a": "Ordu, denizcilik ve yönetim", "b": "Sadece din", "c": "Sadece tarım", "d": "Sadece sanat", "correct": "a"},
            ],
        },
        {
            "country": "misir", "era": "ortacag",
            "title": "İslam Dönemi Mısır ve Memlükler", "leader": "Selahaddin Eyyubi / Memlükler", "gold_reward": 85,
            "questions": [
                {"text": "Haçlılara karşı Kudüs'ü geri alan ve Mısır'da Eyyubi Devleti'ni kuran komutan kimdir?",
                 "a": "Selahaddin Eyyubi", "b": "Baybars", "c": "Kalavun", "d": "Turan Şah", "correct": "a"},
                {"text": "Moğolları Ayn Calut Savaşı'nda durduran Mısır merkezli devlet hangisidir?",
                 "a": "Memlük Devleti", "b": "Fatımi Devleti", "c": "Eyyubi Devleti", "d": "Tolunoğulları", "correct": "a"},
                {"text": "Memlük Devleti hangi askerlerden oluşan bir yönetici sınıfa dayanıyordu?",
                 "a": "Köle asıllı askerler (Memlükler)", "b": "Toprak sahibi soylular", "c": "Din adamları", "d": "Tüccarlar", "correct": "a"},
                {"text": "Mısır'daki Memlük Devleti'ne son veren Osmanlı padişahı kimdir?",
                 "a": "Yavuz Sultan Selim", "b": "Fatih Sultan Mehmed", "c": "Kanuni Sultan Süleyman", "d": "II. Bayezid", "correct": "a"},
            ],
        },
        {
            "country": "misir", "era": "yukselis",
            "title": "Osmanlı Yönetiminde Mısır", "leader": "Kavalalı Mehmet Ali Paşa", "gold_reward": 90,
            "questions": [
                {"text": "Mısır, Osmanlı Devleti'ne hangi savaştan sonra katılmıştır?",
                 "a": "Ridaniye Savaşı", "b": "Mercidabık Savaşı", "c": "Çaldıran Savaşı", "d": "Mohaç Savaşı", "correct": "a"},
                {"text": "19. yüzyılda Mısır'da güçlü bir özerk yönetim kuran vali kimdir?",
                 "a": "Kavalalı Mehmet Ali Paşa", "b": "Kölemenler", "c": "İbrahim Paşa", "d": "Tosun Paşa", "correct": "a"},
                {"text": "Napolyon Bonapart Mısır'ı hangi yıl işgal etmiştir?",
                 "a": "1798", "b": "1805", "c": "1789", "d": "1815", "correct": "a"},
                {"text": "Süveyş Kanalı hangi yüzyılda açılmıştır?",
                 "a": "19. yüzyıl", "b": "18. yüzyıl", "c": "20. yüzyıl", "d": "17. yüzyıl", "correct": "a"},
            ],
        },
        {
            "country": "misir", "era": "modern",
            "title": "Modern Mısır ve Süveyş Krizi", "leader": "Cemal Abdünnasır", "gold_reward": 100,
            "questions": [
                {"text": "Süveyş Kanalı'nı millileştiren Mısır lideri kimdir?",
                 "a": "Cemal Abdünnasır", "b": "Enver Sedat", "c": "Kral Faruk", "d": "Hüsnü Mübarek", "correct": "a"},
                {"text": "Süveyş Krizi hangi yıl yaşanmıştır?",
                 "a": "1956", "b": "1948", "c": "1967", "d": "1973", "correct": "a"},
                {"text": "Mısır'da krallığı sona erdiren 1952 hareketi genel olarak ne olarak bilinir?",
                 "a": "Hür Subaylar Devrimi", "b": "Nil Devrimi", "c": "Kahire Ayaklanması", "d": "Ekim Devrimi", "correct": "a"},
                {"text": "İsrail ile Mısır arasında imzalanan ve barışı sağlayan antlaşma hangisidir?",
                 "a": "Camp David Antlaşması", "b": "Oslo Antlaşması", "c": "Vestfalya Antlaşması", "d": "Sykes-Picot Antlaşması", "correct": "a"},
            ],
        },
        {
            "country": "iran", "era": "ortacag",
            "title": "İslam Sonrası İran ve Selçuklular", "leader": "Büyük Selçuklu", "gold_reward": 85,
            "questions": [
                {"text": "İran coğrafyasında hüküm süren büyük Türk-İslam devleti hangisidir?",
                 "a": "Büyük Selçuklu Devleti", "b": "Gazneliler", "c": "Harzemşahlar", "d": "Timurlular", "correct": "a"},
                {"text": "Selçukluların İran'daki başkentlerinden biri hangi şehirdi?",
                 "a": "İsfahan", "b": "Bağdat", "c": "Semerkant", "d": "Kahire", "correct": "a"},
                {"text": "İranlı bilgin ve devlet adamı olarak ünlenen Selçuklu veziri kimdir?",
                 "a": "Nizamülmülk", "b": "El-Harezmi", "c": "İbn-i Sina", "d": "Farabi", "correct": "a"},
                {"text": "İran'ı istila eden ve büyük yıkıma yol açan Orta Asyalı fatih kimdir?",
                 "a": "Cengiz Han", "b": "Attila", "c": "Timur", "d": "Babür", "correct": "a"},
            ],
        },
        {
            "country": "iran", "era": "yukselis",
            "title": "Safevi Devleti", "leader": "Şah İsmail / Şah Abbas", "gold_reward": 90,
            "questions": [
                {"text": "İran'da Şiiliği devlet dini yapan hanedan hangisidir?",
                 "a": "Safeviler", "b": "Selçuklular", "c": "Gazneliler", "d": "Timurlular", "correct": "a"},
                {"text": "Safevi Devleti'nin kurucusu kimdir?",
                 "a": "Şah İsmail", "b": "Şah Abbas", "c": "Nadir Şah", "d": "Şah Tahmasp", "correct": "a"},
                {"text": "Safevi Devleti'ni en parlak dönemine ulaştıran hükümdar kimdir?",
                 "a": "Şah Abbas", "b": "Şah İsmail", "c": "Şah Tahmasp", "d": "Şah Sultan Hüseyin", "correct": "a"},
                {"text": "Safeviler'in başkenti İsfahan'ı hangi hükümdar imar etmiştir?",
                 "a": "Şah Abbas", "b": "Şah İsmail", "c": "Nadir Şah", "d": "Fetih Ali Şah", "correct": "a"},
            ],
        },
        {
            "country": "iran", "era": "modern",
            "title": "Modern İran ve Devrim", "leader": "Humeyni", "gold_reward": 100,
            "questions": [
                {"text": "1979 İran Devrimi'yle Şahlık rejimi yıkılıp yerine ne kurulmuştur?",
                 "a": "İslam Cumhuriyeti", "b": "Sosyalist Cumhuriyet", "c": "Anayasal Monarşi", "d": "Askeri Cunta", "correct": "a"},
                {"text": "1979 Devrimi'nin lideri kimdir?",
                 "a": "Ayetullah Humeyni", "b": "Musaddık", "c": "Rıza Şah Pehlevi", "d": "Ali Hamaney", "correct": "a"},
                {"text": "Devrim öncesi İran'ı yöneten son şah kimdir?",
                 "a": "Muhammed Rıza Pehlevi", "b": "Rıza Şah", "c": "Nasırüddin Şah", "d": "Fetih Ali Şah", "correct": "a"},
                {"text": "İran-Irak Savaşı hangi yıllar arasında yaşanmıştır?",
                 "a": "1980-1988", "b": "1990-1991", "c": "1970-1975", "d": "1960-1965", "correct": "a"},
            ],
        },
        {
            "country": "cin", "era": "ortacag",
            "title": "Tang ve Song Hanedanlıkları", "leader": "Tang İmparatorları", "gold_reward": 85,
            "questions": [
                {"text": "Çin tarihinde İpek Yolu ticaretinin ve kültürün doruk noktasına ulaştığı hanedan hangisidir?",
                 "a": "Tang Hanedanı", "b": "Qin Hanedanı", "c": "Yuan Hanedanı", "d": "Ming Hanedanı", "correct": "a"},
                {"text": "Matbaayı dünyada ilk kullanan uygarlıklardan biri Çin'de hangi dönemde gelişmiştir?",
                 "a": "Song Hanedanı", "b": "Qin Hanedanı", "c": "Han Hanedanı", "d": "Zhou Hanedanı", "correct": "a"},
                {"text": "Çin'i Moğol istilasından sonra yöneten ve Kubilay Han'ın kurduğu hanedan hangisidir?",
                 "a": "Yuan Hanedanı", "b": "Ming Hanedanı", "c": "Tang Hanedanı", "d": "Qing Hanedanı", "correct": "a"},
                {"text": "Barut, Çin'de ortaçağ döneminde ilk olarak hangi amaçla kullanılmıştır?",
                 "a": "Ateşli oyunlar/fişek", "b": "Doğrudan silah", "c": "Madencilik", "d": "Tıbbi tedavi", "correct": "a"},
            ],
        },
        {
            "country": "cin", "era": "yukselis",
            "title": "Ming Hanedanı ve Deniz Seferleri", "leader": "Zheng He", "gold_reward": 90,
            "questions": [
                {"text": "Ming Hanedanı döneminde büyük deniz seferleri düzenleyen ünlü Çinli amiral kimdir?",
                 "a": "Zheng He", "b": "Kubilay Han", "c": "Konfüçyüs", "d": "Sun Tzu", "correct": "a"},
                {"text": "Ming Hanedanı'nın başkentini taşıdığı ve Yasak Şehir'i inşa ettirdiği şehir hangisidir?",
                 "a": "Pekin", "b": "Şanghay", "c": "Nanjing", "d": "Xi'an", "correct": "a"},
                {"text": "Çin Seddi'nin bugünkü bilinen büyük kısmı hangi hanedan döneminde inşa/tahkim edilmiştir?",
                 "a": "Ming Hanedanı", "b": "Qin Hanedanı", "c": "Han Hanedanı", "d": "Tang Hanedanı", "correct": "a"},
                {"text": "Ming Hanedanı sonrasında Çin'i kim yönetmeye başlamıştır?",
                 "a": "Mançu Qing Hanedanı", "b": "Moğol Yuan Hanedanı", "c": "Song Hanedanı", "d": "Cumhuriyet", "correct": "a"},
            ],
        },
        {
            "country": "cin", "era": "modern",
            "title": "Modern Çin ve Halk Cumhuriyeti", "leader": "Mao Zedong", "gold_reward": 100,
            "questions": [
                {"text": "Çin Halk Cumhuriyeti hangi yıl kurulmuştur?",
                 "a": "1949", "b": "1911", "c": "1937", "d": "1966", "correct": "a"},
                {"text": "Çin Halk Cumhuriyeti'nin kurucu lideri kimdir?",
                 "a": "Mao Zedong", "b": "Deng Xiaoping", "c": "Sun Yat-sen", "d": "Çan Kay Şek", "correct": "a"},
                {"text": "Çin'de son imparatorluğu deviren 1911 hareketi ne olarak bilinir?",
                 "a": "Xinhai Devrimi", "b": "Kültür Devrimi", "c": "Boxer Ayaklanması", "d": "Uzun Yürüyüş", "correct": "a"},
                {"text": "Mao Zedong'un komünist güçlerinin kurtulduğu, tarihi 1934-35 geri çekilişine ne ad verilir?",
                 "a": "Uzun Yürüyüş", "b": "Büyük Sıçrayış", "c": "Kültür Devrimi", "d": "Xinhai Devrimi", "correct": "a"},
            ],
        },
        {
            "country": "hindistan", "era": "antik",
            "title": "İndus Vadisi ve Maurya İmparatorluğu", "leader": "İmparator Aşoka", "gold_reward": 75,
            "questions": [
                {"text": "Hindistan'daki en eski şehir uygarlıklarından biri hangi nehir vadisinde gelişmiştir?",
                 "a": "İndus Vadisi", "b": "Ganj Vadisi", "c": "Nil Vadisi", "d": "Fırat Vadisi", "correct": "a"},
                {"text": "Hindistan'ı büyük ölçüde birleştiren ve Budizmi yayan ünlü Maurya imparatoru kimdir?",
                 "a": "Aşoka", "b": "Chandragupta", "c": "Ekber Şah", "d": "Babür", "correct": "a"},
                {"text": "Hinduizm ve Budizm hangi kıtada doğmuş dinlerdendir?",
                 "a": "Asya (Hindistan)", "b": "Afrika", "c": "Avrupa", "d": "Amerika", "correct": "a"},
                {"text": "Antik Hindistan'da toplumu katı biçimde ayıran sosyal sistem nedir?",
                 "a": "Kast sistemi", "b": "Feodal sistem", "c": "Kölelik sistemi", "d": "Loncalar", "correct": "a"},
            ],
        },
        {
            "country": "hindistan", "era": "yukselis",
            "title": "Babür İmparatorluğu", "leader": "Babür / Ekber Şah", "gold_reward": 90,
            "questions": [
                {"text": "Hindistan'da güçlü Türk-Moğol kökenli imparatorluğu kuran hükümdar kimdir?",
                 "a": "Babür", "b": "Aşoka", "c": "Ekber Şah", "d": "Timur", "correct": "a"},
                {"text": "Babür İmparatorluğu'nun en parlak dönemini yaşatan hükümdar kimdir?",
                 "a": "Ekber Şah", "b": "Babür", "c": "Cihangir", "d": "Evrengzib", "correct": "a"},
                {"text": "Ünlü Tac Mahal, hangi Babür padişahı tarafından yaptırılmıştır?",
                 "a": "Şah Cihan", "b": "Ekber Şah", "c": "Babür", "d": "Evrengzib", "correct": "a"},
                {"text": "Babür İmparatorluğu'na son veren sömürgeci güç hangisidir?",
                 "a": "İngiltere", "b": "Portekiz", "c": "Fransa", "d": "Hollanda", "correct": "a"},
            ],
        },
        {
            "country": "hindistan", "era": "modern",
            "title": "Hindistan'ın Bağımsızlığı", "leader": "Mahatma Gandi", "gold_reward": 100,
            "questions": [
                {"text": "Hindistan'ı şiddet içermeyen direnişle bağımsızlığa taşıyan lider kimdir?",
                 "a": "Mahatma Gandi", "b": "Cevahirlal Nehru", "c": "Muhammed Ali Cinnah", "d": "Subhas Chandra Bose", "correct": "a"},
                {"text": "Hindistan İngiltere'den hangi yıl bağımsızlığını kazanmıştır?",
                 "a": "1947", "b": "1919", "c": "1930", "d": "1950", "correct": "a"},
                {"text": "Bağımsızlık sırasında Hindistan'dan ayrılarak kurulan Müslüman çoğunluklu ülke hangisidir?",
                 "a": "Pakistan", "b": "Bangladeş", "c": "Afganistan", "d": "Nepal", "correct": "a"},
                {"text": "Gandi'nin şiddetsiz direniş felsefesine verilen isim nedir?",
                 "a": "Satyagraha", "b": "Cihat", "c": "Jihad", "d": "Swaraj Savaşı", "correct": "a"},
            ],
        },
        {
            "country": "japonya", "era": "antik",
            "title": "Antik Japonya ve Yamato Dönemi", "leader": "Yamato Hanedanı", "gold_reward": 70,
            "questions": [
                {"text": "Japon imparatorluk hanedanının kökeni hangi antik döneme dayanır?",
                 "a": "Yamato Dönemi", "b": "Heian Dönemi", "c": "Edo Dönemi", "d": "Meiji Dönemi", "correct": "a"},
                {"text": "Japonya'nın geleneksel dini, doğa ve atalara tapınmayı içeren hangisidir?",
                 "a": "Şintoizm", "b": "Budizm", "c": "Taoizm", "d": "Konfüçyüsçülük", "correct": "a"},
                {"text": "Japon imparatorunun soyunun geldiğine inanılan tanrıça hangisidir?",
                 "a": "Amaterasu (Güneş Tanrıçası)", "b": "İsis", "c": "Athena", "d": "Freya", "correct": "a"},
                {"text": "Budizm Japonya'ya hangi komşu ülke/bölge üzerinden ulaşmıştır?",
                 "a": "Kore ve Çin", "b": "Hindistan doğrudan", "c": "Moğolistan", "d": "Filipinler", "correct": "a"},
            ],
        },
        {
            "country": "japonya", "era": "yukselis",
            "title": "Sengoku Dönemi ve Birleşme", "leader": "Oda Nobunaga / Tokugawa Ieyasu", "gold_reward": 90,
            "questions": [
                {"text": "Japonya'da derebeylerin sürekli savaştığı \"Savaşan Ülkeler\" dönemine ne ad verilir?",
                 "a": "Sengoku Dönemi", "b": "Heian Dönemi", "c": "Edo Dönemi", "d": "Meiji Dönemi", "correct": "a"},
                {"text": "Japonya'yı kesin olarak birleştirip Edo Şogunluğu'nu kuran lider kimdir?",
                 "a": "Tokugawa Ieyasu", "b": "Oda Nobunaga", "c": "Toyotomi Hideyoshi", "d": "Minamoto Yoritomo", "correct": "a"},
                {"text": "Japonya'yı ateşli silahlarla tanıştıran Avrupalı denizciler hangi ülkedendir?",
                 "a": "Portekiz", "b": "İspanya", "c": "Hollanda", "d": "İngiltere", "correct": "a"},
                {"text": "Edo Şogunluğu döneminde başkent işlevi gören şehir hangisidir?",
                 "a": "Edo (bugünkü Tokyo)", "b": "Kyoto", "c": "Osaka", "d": "Nagasaki", "correct": "a"},
            ],
        },
        {
            "country": "japonya", "era": "modern",
            "title": "Meiji Restorasyonu ve Modern Japonya", "leader": "Meiji İmparatoru", "gold_reward": 100,
            "questions": [
                {"text": "Japonya'yı hızla modernleştiren ve Batılılaşmayı başlatan siyasi hareket nedir?",
                 "a": "Meiji Restorasyonu", "b": "Sengoku Reformu", "c": "Edo Devrimi", "d": "Taisho Reformu", "correct": "a"},
                {"text": "Meiji Restorasyonu hangi yıl gerçekleşmiştir?",
                 "a": "1868", "b": "1900", "c": "1853", "d": "1912", "correct": "a"},
                {"text": "Japonya'yı dış dünyaya zorla açan Amerikalı komutan kimdir?",
                 "a": "Commodore Matthew Perry", "b": "Douglas MacArthur", "c": "Ulysses Grant", "d": "Theodore Roosevelt", "correct": "a"},
                {"text": "II. Dünya Savaşı'nda Japonya'yı teslim olmaya zorlayan olay nedir?",
                 "a": "Hiroşima ve Nagazaki'ye atom bombası atılması", "b": "Pearl Harbor saldırısı", "c": "Midway Deniz Savaşı", "d": "Okinawa Kuşatması", "correct": "a"},
            ],
        },
    ]

    existing = {
        (e.country_id, e.era_id, e.title) for e in HistoricalEvent.query.all()
    }

    for ev in events:
        key = (country_by_key[ev["country"]].id, era_by_key[ev["era"]].id, ev["title"])
        if key in existing:
            continue  # bu olay zaten eklenmiş, tekrar ekleme
        event = HistoricalEvent(
            country_id=country_by_key[ev["country"]].id,
            era_id=era_by_key[ev["era"]].id,
            title=ev["title"],
            leader=ev["leader"],
            gold_reward=ev["gold_reward"],
        )
        db.session.add(event)
        db.session.flush()  # event.id almak için
        for i, q in enumerate(ev["questions"]):
            db.session.add(EventQuestion(
                event_id=event.id, order=i, text=q["text"],
                option_a=q["a"], option_b=q["b"], option_c=q["c"], option_d=q["d"],
                correct=q["correct"],
            ))
    db.session.commit()


# Ülke noktalarının harita görseli (frontend/assets/world-map.webp — kırpılmış
# hâli) üzerindeki % konumları. Görsel değişirse sadece burası güncellenir;
# her açılışta veritabanındaki x/y bu değerlere eşitlenir.
COUNTRY_LAYOUT = {
    "amerika": (16.0, 27.4),
    "meksika": (13.9, 43.8),
    "brezilya": (30.4, 65.8),
    "fransa": (45.0, 28.5),
    "almanya": (51.0, 19.5),
    "turkiye": (59.3, 33.6),
    "rusya": (66.5, 12.3),
    "misir": (56.2, 45.9),
    "iran": (66.0, 38.4),
    "cin": (77.8, 31.5),
    "hindistan": (71.1, 46.6),
    "japonya": (88.1, 27.4),
}


def sync_country_layout():
    changed = False
    for c in Country.query.all():
        pos = COUNTRY_LAYOUT.get(c.key)
        if pos and (c.x, c.y) != pos:
            c.x, c.y = pos
            changed = True
    if changed:
        db.session.commit()


def ensure_schema_migrations():
    """db.create_all() zaten var olan tabloları değiştirmez; bu yüzden
    daha önceden oluşmuş bir bilgi_akini.db dosyasına sonradan eklenen
    kolonları (örn. character_key) burada elle ekliyoruz. Kolon zaten
    varsa hiçbir şey yapmaz — güvenle tekrar tekrar çalıştırılabilir."""
    inspector = sa_inspect(db.engine)
    if "players" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("players")}
    if "character_key" not in existing_cols:
        with db.engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE players ADD COLUMN character_key VARCHAR(30)"))
            conn.commit()


with app.app_context():
    db.create_all()
    ensure_schema_migrations()
    seed_data()
    sync_country_layout()


if __name__ == "__main__":
    from netinfo import get_lan_ips

    port = int(os.environ.get("PORT", 5000))
    ips = get_lan_ips()
    print("=" * 56)
    print("  BILGI AKINI SUNUCUSU CALISIYOR")
    print(f"  Bilgisayar : http://localhost:{port}")
    for ip in ips[:2]:
        print(f"  Telefon    : http://{ip}:{port}   (ayni Wi-Fi)")
    print("  Kapatmak icin bu pencereyi kapat.")
    print("=" * 56, flush=True)
    # debug/reloader kapalı: sunumda tek süreç, beklenmedik yeniden başlama yok.
    socketio.run(app, host="0.0.0.0", port=port, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
