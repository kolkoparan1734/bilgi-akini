"""
BİLGİ AKINI - Backend API
--------------------------
Flask tabanlı REST API. Bölgeler, sorular, oyuncu skorları burada yönetilir.

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

class Region(db.Model):
    __tablename__ = "regions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    x = db.Column(db.Float, nullable=False)          # harita üzerinde % konum
    y = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    difficulty = db.Column(db.String(20), default="kolay")  # kolay / normal / zor
    gold_reward = db.Column(db.Integer, default=50)


class Question(db.Model):
    __tablename__ = "questions"
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    difficulty = db.Column(db.String(20), default="kolay")
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


class PlayerRegion(db.Model):
    """Bir oyuncunun fethettiği bölgeler (kim neyi almış)."""
    __tablename__ = "player_regions"
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    conquered_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------- YARDIMCI ----------------

def region_to_dict(region, conquered_ids):
    return {
        "id": region.id,
        "name": region.name,
        "x": region.x,
        "y": region.y,
        "category": region.category,
        "difficulty": region.difficulty,
        "gold_reward": region.gold_reward,
        "conquered": region.id in conquered_ids,
    }


def pick_question(region, exclude_ids=None):
    """Bölgeye uygun rastgele bir soru seçer; mümkünse exclude_ids içindeki
    (son sorulmuş / bu maçta yanlış bilinmiş) soruları hariç tutar."""
    exclude_ids = exclude_ids or set()
    candidates = Question.query.filter_by(category=region.category, difficulty=region.difficulty).all()
    if not candidates:
        candidates = Question.query.filter_by(category=region.category).all()
    if not candidates:
        return None
    fresh = [q for q in candidates if q.id not in exclude_ids]
    pool = fresh if fresh else candidates  # tüm adaylar hariç tutulduysa (tek soru vb.) yine de bir şey döndür
    return random.choice(pool)


# Tek kişilik modda, bir oyuncunun bir bölgede en son gördüğü soruyu tutar
# (username, region_id) -> question_id — yanlış/süre sonrası aynı soru tekrar gelmesin diye.
last_shown_question = {}

# 2 kişilik maç odaları (bellekte, kalıcı değil): code -> oda durumu
rooms = {}


# ---------------- API ROUTES ----------------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/player/<username>", methods=["GET"])
def get_or_create_player(username):
    player = Player.query.filter_by(username=username).first()
    if not player:
        player = Player(username=username)
        db.session.add(player)
        db.session.commit()
    conquered_ids = {pr.region_id for pr in PlayerRegion.query.filter_by(player_id=player.id)}
    return jsonify({
        "id": player.id,
        "username": player.username,
        "gold": player.gold,
        "conquered_count": player.conquered_count,
        "conquered_region_ids": list(conquered_ids),
    })


@app.route("/api/regions", methods=["GET"])
def list_regions():
    username = request.args.get("username", "")
    conquered_ids = set()
    if username:
        player = Player.query.filter_by(username=username).first()
        if player:
            conquered_ids = {pr.region_id for pr in PlayerRegion.query.filter_by(player_id=player.id)}
    regions = Region.query.all()
    return jsonify([region_to_dict(r, conquered_ids) for r in regions])


@app.route("/api/regions/<int:region_id>/question", methods=["GET"])
def get_question_for_region(region_id):
    region = Region.query.get_or_404(region_id)
    username = request.args.get("username", "")

    exclude_ids = set()
    last_id = last_shown_question.get((username, region_id))
    if last_id is not None:
        exclude_ids.add(last_id)

    q = pick_question(region, exclude_ids=exclude_ids)
    if not q:
        return jsonify({"error": "Bu bölge için soru bulunamadı"}), 404

    last_shown_question[(username, region_id)] = q.id

    return jsonify({
        "id": q.id,
        "region_id": region.id,
        "region_name": region.name,
        "text": q.text,
        "options": {"a": q.option_a, "b": q.option_b, "c": q.option_c, "d": q.option_d},
    })


@app.route("/api/answer", methods=["POST"])
def submit_answer():
    data = request.get_json(force=True)
    username = data.get("username")
    question_id = data.get("question_id")
    region_id = data.get("region_id")
    chosen = data.get("chosen")  # 'a' | 'b' | 'c' | 'd'

    player = Player.query.filter_by(username=username).first()
    question = Question.query.get(question_id)
    region = Region.query.get(region_id)

    if not (player and question and region):
        return jsonify({"error": "Geçersiz istek"}), 400

    correct = (chosen == question.correct)

    if correct:
        already = PlayerRegion.query.filter_by(player_id=player.id, region_id=region.id).first()
        if not already:
            db.session.add(PlayerRegion(player_id=player.id, region_id=region.id))
            player.conquered_count += 1
            player.gold += region.gold_reward
            player.best_score = max(player.best_score, player.conquered_count)
    else:
        player.gold = max(0, player.gold - 20)  # yanlış cevap küçük gold cezası

    db.session.commit()

    return jsonify({
        "correct": correct,
        "correct_option": question.correct,
        "gold": player.gold,
        "conquered_count": player.conquered_count,
    })


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    top = Player.query.order_by(Player.best_score.desc()).limit(10).all()
    return jsonify([
        {"username": p.username, "best_score": p.best_score, "gold": p.gold}
        for p in top
    ])


# ---------------- 2 KİŞİLİK MOD (Socket.IO) ----------------
# Maç durumu kalıcı DB'ye değil, sadece bu sözlüğe yazılır (oda bitince silinir).
# Kural: bir bölgeye dokunan oyuncu bölgeyi kilitler ("rakip deniyor"); doğru
# bilirse bölge onun olur, yanlış/süre biterse bölge tekrar herkese açılır.

def make_room_code():
    while True:
        code = str(random.randint(1000, 9999))
        if code not in rooms:
            return code


def region_to_dict_mp(region, room):
    rs = room["regions"][region.id]
    return {
        "id": region.id,
        "name": region.name,
        "x": region.x,
        "y": region.y,
        "category": region.category,
        "difficulty": region.difficulty,
        "gold_reward": region.gold_reward,
        "state": rs["state"],  # available | locked | conquered
        "owner": rs["owner"],
    }


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
    regions = Region.query.all()
    rooms[code] = {
        "code": code,
        "players": [username],
        "sids": {username: request.sid},
        "regions": {
            r.id: {"state": "available", "owner": None, "excluded_qids": set()}
            for r in regions
        },
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

    regions = Region.query.order_by(Region.id).all()
    emit("match_start", {
        "code": code,
        "players": room["players"],
        "regions": [region_to_dict_mp(r, room) for r in regions],
    }, room=code)


@socketio.on("attack_region")
def handle_attack_region(data):
    data = data or {}
    code = (data.get("code") or "").strip()
    username = data.get("username")
    region_id = data.get("region_id")

    room = rooms.get(code)
    rs = room["regions"].get(region_id) if room else None
    if not room or not rs or rs["state"] != "available":
        emit("attack_denied", {"region_id": region_id})
        return

    region = Region.query.get(region_id)
    question = pick_question(region, exclude_ids=rs["excluded_qids"]) if region else None
    if not question:
        emit("attack_denied", {"region_id": region_id})
        return

    rs["state"] = "locked"
    rs["owner"] = username
    emit("region_locked", {"region_id": region_id, "by": username}, room=code)

    emit("question_ready", {
        "region_id": region_id,
        "region_name": region.name,
        "question_id": question.id,
        "text": question.text,
        "options": {"a": question.option_a, "b": question.option_b, "c": question.option_c, "d": question.option_d},
    }, room=room["sids"][username])


@socketio.on("submit_answer")
def handle_submit_answer(data):
    data = data or {}
    code = (data.get("code") or "").strip()
    username = data.get("username")
    region_id = data.get("region_id")
    question_id = data.get("question_id")
    chosen = data.get("chosen")

    room = rooms.get(code)
    rs = room["regions"].get(region_id) if room else None
    question = Question.query.get(question_id)
    region = Region.query.get(region_id)
    if not room or not rs or not question or not region:
        return

    correct = (chosen == question.correct)

    if correct:
        rs["state"] = "conquered"
        rs["owner"] = username
        player = Player.query.filter_by(username=username).first()
        if player:
            player.gold += region.gold_reward
            db.session.commit()
        emit("region_result", {
            "region_id": region_id,
            "correct": True,
            "owner": username,
            "by": username,
            "gold_reward": region.gold_reward,
            "correct_option": question.correct,
        }, room=code)
    else:
        rs["excluded_qids"].add(question_id)
        rs["state"] = "available"
        rs["owner"] = None
        emit("region_result", {
            "region_id": region_id,
            "correct": False,
            "by": username,
            "correct_option": question.correct,
        }, room=code)

    if all(r["state"] == "conquered" for r in room["regions"].values()):
        scores = {p: 0 for p in room["players"]}
        for r in room["regions"].values():
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
    if Region.query.first():
        return  # zaten dolu

    regions = [
        {"name": "Edirne", "x": 20, "y": 15, "category": "tarih", "difficulty": "kolay", "gold_reward": 40},
        {"name": "Bursa", "x": 30, "y": 35, "category": "tarih", "difficulty": "kolay", "gold_reward": 40},
        {"name": "İstanbul", "x": 45, "y": 20, "category": "genel_kultur", "difficulty": "normal", "gold_reward": 80},
        {"name": "Konya", "x": 55, "y": 55, "category": "bilim", "difficulty": "normal", "gold_reward": 60},
        {"name": "Diyarbakır", "x": 75, "y": 45, "category": "cografya", "difficulty": "zor", "gold_reward": 100},
        {"name": "Kahire", "x": 60, "y": 85, "category": "tarih", "difficulty": "zor", "gold_reward": 100},
        {"name": "Belgrad", "x": 15, "y": 45, "category": "genel_kultur", "difficulty": "normal", "gold_reward": 60},
        {"name": "Bağdat", "x": 85, "y": 65, "category": "bilim", "difficulty": "zor", "gold_reward": 100},
    ]
    for r in regions:
        db.session.add(Region(**r))

    questions = [
        # tarih - kolay
        {"category": "tarih", "difficulty": "kolay", "text": "İstanbul hangi yılda fethedildi?",
         "option_a": "1453", "option_b": "1071", "option_c": "1299", "option_d": "1512", "correct": "a"},
        {"category": "tarih", "difficulty": "kolay", "text": "Osmanlı Devleti'nin kurucusu kimdir?",
         "option_a": "II. Mehmed", "option_b": "Osman Bey", "option_c": "Orhan Bey", "option_d": "Yıldırım Bayezid", "correct": "b"},
        # tarih - zor
        {"category": "tarih", "difficulty": "zor", "text": "Mısır, Yavuz Sultan Selim tarafından hangi savaştan sonra Osmanlı topraklarına katıldı?",
         "option_a": "Ridaniye", "option_b": "Mohaç", "option_c": "Çaldıran", "option_d": "Otlukbeli", "correct": "a"},
        # genel kültür - normal
        {"category": "genel_kultur", "difficulty": "normal", "text": "Ayasofya hangi imparator tarafından kilise olarak inşa ettirilmiştir?",
         "option_a": "I. Justinianus", "option_b": "Konstantin", "option_c": "II. Mehmed", "option_d": "I. Theodosius", "correct": "a"},
        {"category": "genel_kultur", "difficulty": "normal", "text": "Topkapı Sarayı hangi şehirdedir?",
         "option_a": "Bursa", "option_b": "İstanbul", "option_c": "Edirne", "option_d": "Ankara", "correct": "b"},
        # bilim - normal
        {"category": "bilim", "difficulty": "normal", "text": "İlk rasathanelerden birini kuran Osmanlı bilgini kimdir?",
         "option_a": "Takiyüddin", "option_b": "Uluğ Bey", "option_c": "El-Harezmi", "option_d": "İbn-i Sina", "correct": "a"},
        # bilim - zor
        {"category": "bilim", "difficulty": "zor", "text": "Cebir biliminin kurucusu kabul edilen İslam bilgini kimdir?",
         "option_a": "İbn-i Sina", "option_b": "El-Harezmi", "option_c": "Farabi", "option_d": "Biruni", "correct": "b"},
        # coğrafya - zor
        {"category": "cografya", "difficulty": "zor", "text": "Diyarbakır hangi nehir kıyısındadır?",
         "option_a": "Fırat", "option_b": "Dicle", "option_c": "Kızılırmak", "option_d": "Sakarya", "correct": "b"},
    ]
    for q in questions:
        db.session.add(Question(**q))

    db.session.commit()


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)
