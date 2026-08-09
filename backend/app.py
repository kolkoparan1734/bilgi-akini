"""
BİLGİ AKINI - Backend API
--------------------------
Flask tabanlı REST API. Dünya haritası üzerindeki ülkeler, dönemler,
tarihi olaylar (ve her olayın soruları) burada yönetilir.

Veritabanı: Varsayılan olarak SQLite (hızlı test için) kullanır.
MySQL'e geçmek için DATABASE_URL ortam değişkenini ayarla, örn:
    DATABASE_URL=mysql+mysqlconnector://kullanici:sifre@localhost/bilgi_akini
"""

import os
import random
from datetime import datetime

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
CORS(app)  # Mobil uygulama / farklı origin'lerden erişim için
socketio = SocketIO(app, cors_allowed_origins="*")  # 2 kişilik gerçek zamanlı mod

# --- Veritabanı Ayarı ---
DEFAULT_SQLITE = "sqlite:///" + os.path.join(os.path.dirname(__file__), "bilgi_akini.db")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


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


# ---------------- API ROUTES ----------------

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
    })


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
    doğruysa olay fethedilir. Body: {username, answers: {question_id: chosen}}"""
    data = request.get_json(force=True)
    username = data.get("username")
    answers = data.get("answers", {})  # {"12": "a", "13": "c", ...}

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
    if all_correct and not already:
        db.session.add(PlayerEventProgress(player_id=player.id, event_id=event.id))
        player.conquered_count += 1
        player.gold += event.gold_reward
        player.best_score = max(player.best_score, player.conquered_count)
    elif not all_correct:
        player.gold = max(0, player.gold - 20)  # başarısız fetih küçük gold cezası

    db.session.commit()

    return jsonify({
        "all_correct": all_correct,
        "already_conquered": bool(already),
        "results": results,
        "gold": player.gold,
        "conquered_count": player.conquered_count,
        "gold_reward": event.gold_reward,
    })


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    top = Player.query.order_by(Player.best_score.desc()).limit(10).all()
    return jsonify([
        {"username": p.username, "best_score": p.best_score, "gold": p.gold}
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


def make_room_code():
    while True:
        code = str(random.randint(1000, 9999))
        if code not in rooms:
            return code


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
        for e in HistoricalEvent.query.all()
    ]


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

    code = make_room_code()
    rooms[code] = {
        "code": code,
        "players": [username],
        "sids": {username: request.sid},
        "events": {e.id: {"state": "available", "owner": None, "excluded_qids": set()} for e in HistoricalEvent.query.all()},
    }
    join_room(code)
    emit("room_created", {"code": code, "username": username})


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

    emit("match_start", {
        "code": code,
        "players": room["players"],
        "events": all_events_state(room),
    }, room=code)


@socketio.on("attack_event")
def handle_attack_event(data):
    data = data or {}
    code = (data.get("code") or "").strip()
    username = data.get("username")
    event_id = data.get("event_id")

    room = rooms.get(code)
    rs = room["events"].get(event_id) if room else None
    if not room or not rs or rs["state"] != "available":
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
    if not room or not rs or not question or not event or rs["owner"] != username:
        return

    correct = (chosen == question.correct)

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
    player = Player.query.filter_by(username=username).first()
    if player:
        player.gold += event.gold_reward
        db.session.commit()
    emit("event_result", {
        "event_id": event_id,
        "correct": True,
        "owner": username,
        "by": username,
        "gold_reward": event.gold_reward,
        "correct_option": question.correct,
    }, room=code)

    if all(r["state"] == "conquered" for r in room["events"].values()):
        scores = {p: 0 for p in room["players"]}
        for r in room["events"].values():
            if r["owner"] in scores:
                scores[r["owner"]] += 1
        emit("match_over", {"scores": scores}, room=code)


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
    if Era.query.first():
        return  # zaten dolu

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
    ]

    for ev in events:
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


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)
