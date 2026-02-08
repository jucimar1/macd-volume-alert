-- schema.sql - Estrutura do banco de dados para persistência de estado

CREATE TABLE IF NOT EXISTS alerts (
    symbol TEXT PRIMARY KEY,
    last_zero_cross INTEGER,      -- Timestamp do último zero line cross
    max_histogram REAL,           -- Pico do histograma desde o zero cross
    alert_sent INTEGER DEFAULT 0, -- 1 = alerta enviado nas últimas 15min
    last_check INTEGER,           -- Última verificação (timestamp)
    volume_score INTEGER DEFAULT 0 -- Score de validação de volume (0-10)
);

-- Tabela para histórico de alertas (opcional, para análise)
CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp INTEGER,
    macd_distance REAL,
    max_histogram REAL,
    volume_ratio REAL,
    taker_buy_ratio REAL,
    volume_score INTEGER,
    decision TEXT
);
