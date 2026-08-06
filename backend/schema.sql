-- BİLGİ AKINI - MySQL Şeması
-- Kullanım: mysql -u kullanici -p < schema.sql

CREATE DATABASE IF NOT EXISTS bilgi_akini CHARACTER SET utf8mb4;
USE bilgi_akini;

CREATE TABLE regions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    x FLOAT NOT NULL,
    y FLOAT NOT NULL,
    category VARCHAR(50) NOT NULL,
    difficulty VARCHAR(20) DEFAULT 'kolay',
    gold_reward INT DEFAULT 50
);

CREATE TABLE questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    difficulty VARCHAR(20) DEFAULT 'kolay',
    text VARCHAR(300) NOT NULL,
    option_a VARCHAR(150) NOT NULL,
    option_b VARCHAR(150) NOT NULL,
    option_c VARCHAR(150) NOT NULL,
    option_d VARCHAR(150) NOT NULL,
    correct CHAR(1) NOT NULL
);

CREATE TABLE players (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    gold INT DEFAULT 200,
    conquered_count INT DEFAULT 0,
    best_score INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE player_regions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    player_id INT NOT NULL,
    region_id INT NOT NULL,
    conquered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES regions(id) ON DELETE CASCADE
);

-- Not: Flask uygulaması SQLAlchemy ile açılınca tabloları ve örnek
-- verileri kendisi oluşturur (bkz. app.py -> seed_data()).
-- Bu dosya, MySQL'e manuel geçiş yapmak isteyenler için referans amaçlıdır.
