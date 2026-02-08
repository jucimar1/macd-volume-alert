#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALERTA MACD 5m com Validação Institucional via Volume
======================================================
Critério: Distância entre linhas MACD ≥ 2x pico do histograma 
          DESDE o último zero line cross + confirmação de volume
"""

import os
import sys
import sqlite3
import time
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# Configuração de logging colorido (conforme sua preferência por console limpo)
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',    # Ciano
        'INFO': '\033[32m',     # Verde
        'WARNING': '\033[33m',  # Amarelo
        'ERROR': '\033[31m',    # Vermelho
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'
    }
    
    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        return super().format(record)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger()
for handler in logger.handlers[:]:
    logger.removeHandler(handler)
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(handler)

# Importações condicionais (permite execução mesmo sem config.py)
try:
    from config import (
        TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
        BINANCE_API_KEY, BINANCE_API_SECRET,
        SYMBOLS, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
        TRADING_HOURS, VOLUME_THRESHOLD_STRONG,
        VOLUME_THRESHOLD_MODERATE, TAKER_BUY_THRESHOLD
    )
    from binance.client import Client
    from telegram import Bot
    HAS_TELEGRAM = True
except ImportError as e:
    logger.warning(f"⚠️ Módulos opcionais não disponíveis: {e}")
    HAS_TELEGRAM = False
    BINANCE_API_KEY = BINANCE_API_SECRET = ""
    SYMBOLS = ["BTCUSDT"]
    TRADING_HOURS = [(7, 10), (12, 16)]
    VOLUME_THRESHOLD_STRONG = 1.8
    VOLUME_THRESHOLD_MODERATE = 1.3
    TAKER_BUY_THRESHOLD = 65

# Inicialização do cliente Binance (com fallback para modo offline)
try:
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET) if BINANCE_API_KEY else None
except Exception as e:
    logger.error(f"❌ Erro ao inicializar Binance Client: {e}")
    client = None

# Inicialização do bot Telegram (com fallback)
bot = Bot(token=TELEGRAM_TOKEN) if HAS_TELEGRAM and TELEGRAM_TOKEN else None

DB_PATH = "alerts.db"

def init_database():
    """Inicializa o banco SQLite com estrutura persistente"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Criar tabelas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            symbol TEXT PRIMARY KEY,
            last_zero_cross INTEGER,
            max_histogram REAL,
            alert_sent INTEGER DEFAULT 0,
            last_check INTEGER,
            volume_score INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
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
        )
    ''')
    
    # Inserir símbolos iniciais se não existirem
    for symbol in SYMBOLS:
        cursor.execute(
            "INSERT OR IGNORE INTO alerts (symbol, last_zero_cross, max_histogram, alert_sent, last_check, volume_score) VALUES (?, ?, ?, ?, ?, ?)",
            (symbol, 0, 0.0, 0, 0, 0)
        )
    
    conn.commit()
    conn.close()
    logger.info("✅ Banco de dados inicializado")

def get_klines(symbol, interval='5m', limit=100):
    """
    Obtém candles da Binance com fallback para dados simulados (offline)
    """
    if not client:
        logger.warning("⚠️ Modo offline: usando dados simulados")
        return generate_mock_data(symbol, limit)
    
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        # Conversão de tipos
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['taker_buy_volume'] = df['taker_buy_quote_asset_volume'].astype(float)
        
        return df[['open_time', 'close', 'volume', 'taker_buy_volume']]
    
    except Exception as e:
        logger.error(f"❌ Erro ao buscar candles {symbol}: {e}")
        return pd.DataFrame()

def generate_mock_data(symbol, limit=100):
    """Gera dados simulados para teste offline"""
    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(minutes=5*i) for i in range(limit)][::-1]
    
    # Simular movimento com reversão e expansão
    base_price = 100.0
    prices = []
    for i in range(limit):
        if i < 30:
            prices.append(base_price - i * 0.1)  # Queda
        elif i < 50:
            prices.append(base_price - 3.0 + (i-30) * 0.3)  # Reversão forte
        else:
            prices.append(base_price + 3.0 + (i-50) * 0.05)  # Consolidação
    
    df = pd.DataFrame({
        'open_time': timestamps,
        'close': prices,
        'volume': [1000 + np.random.rand()*500 for _ in range(limit)],
        'taker_buy_volume': [600 + np.random.rand()*300 for _ in range(limit)]
    })
    return df

def calculate_macd(df):
    """Calcula MACD, Signal Line e Histograma"""
    exp1 = df['close'].ewm(span=MACD_FAST, adjust=False).mean()
    exp2 = df['close'].ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

def find_last_zero_cross(macd_series):
    """
    Encontra o índice do último cruzamento da linha MACD na linha 0
    Retorna: (índice, direção) onde direção = 'bullish' (cruzou para cima) ou 'bearish'
    """
    for i in range(len(macd_series)-1, 10, -1):
        prev = macd_series.iloc[i-1]
        curr = macd_series.iloc[i]
        
        # Cruzamento de baixo para cima (bullish reversal)
        if prev < 0 and curr >= 0:
            return i, 'bullish'
        # Cruzamento de cima para baixo (bearish reversal)
        elif prev > 0 and curr <= 0:
            return i, 'bearish'
    
    return None, None

def validate_volume(symbol, df, zero_cross_idx):
    """
    Validação tripla do volume para confirmar participação institucional
    Retorna: (score, mensagem, volume_ratio, taker_ratio)
    """
    if len(df) < 25:
        return 0, "❌ Dados insuficientes para análise de volume", 0, 0
    
    # 1. Volume relativo vs média móvel 20 períodos
    volume_ma20 = df['volume'].rolling(20).mean().iloc[-1]
    volume_atual = df['volume'].iloc[-1]
    volume_ratio = volume_atual / volume_ma20 if volume_ma20 > 0 else 0
    
    # 2. Taker Buy/Sell Ratio (fluxo institucional)
    taker_buy = df['taker_buy_volume'].iloc[-1]
    total_volume = df['volume'].iloc[-1] * df['close'].iloc[-1]  # Aproximação em quote asset
    taker_ratio = (taker_buy / total_volume) * 100 if total_volume > 0 else 50
    
    # 3. Volume acumulado desde zero line cross (confirmação de sustentação)
    if zero_cross_idx and zero_cross_idx < len(df):
        volume_since_cross = df['volume'].iloc[zero_cross_idx:].sum()
        avg_volume_since_cross = volume_since_cross / (len(df) - zero_cross_idx)
        volume_sustained = avg_volume_since_cross > volume_ma20 * 0.9
    else:
        volume_sustained = False
    
    # 🔑 Lógica de decisão com pesos institucionais
    score = 0
    reasons = []
    
    # Critério 1: Volume relativo forte (>1.8x média)
    if volume_ratio >= VOLUME_THRESHOLD_STRONG:
        score += 4
        reasons.append(f"Volume {volume_ratio:.1f}x média (forte)")
    elif volume_ratio >= VOLUME_THRESHOLD_MODERATE:
        score += 2
        reasons.append(f"Volume {volume_ratio:.1f}x média (moderado)")
    else:
        reasons.append(f"Volume {volume_ratio:.1f}x média (fraco)")
    
    # Critério 2: Taker Buy dominante (>65%)
    if taker_ratio >= TAKER_BUY_THRESHOLD:
        score += 4
        reasons.append(f"Taker Buy {taker_ratio:.0f}% (institucional)")
    elif taker_ratio >= 55:
        score += 2
        reasons.append(f"Taker Buy {taker_ratio:.0f}% (neutro)")
    else:
        reasons.append(f"Taker Buy {taker_ratio:.0f}% (retail)")
    
    # Critério 3: Volume sustentado desde reversão
    if volume_sustained:
        score += 2
        reasons.append("Volume sustentado desde reversão")
    
    # Montar mensagem de diagnóstico
    if score >= 8:
        msg = f"✅ Volume FORTE ({volume_ratio:.1f}x) + Taker Buy {taker_ratio:.0f}%"
    elif score >= 5:
        msg = f"🟡 Volume MODERADO ({volume_ratio:.1f}x) + Taker Buy {taker_ratio:.0f}%"
    else:
        msg = f"❌ Volume FRACO ({volume_ratio:.1f}x) + Taker Buy {taker_ratio:.0f}%"
    
    return score, msg, volume_ratio, taker_ratio

def is_trading_hour():
    """Verifica se está dentro do horário de alta liquidez (UTC)"""
    utc_now = datetime.now(timezone.utc)
    current_hour = utc_now.hour
    
    for start, end in TRADING_HOURS:
        if start <= current_hour < end:
            return True, f"🕗 Horário de alta liquidez: {start:02d}:00-{end:02d}:00 UTC"
    
    return False, f"⚠️ Fora do horário ideal (agora: {current_hour:02d}:00 UTC)"

def detect_macd_pattern(symbol):
    """
    Detecta o padrão completo:
    1. Zero line cross (reversão)
    2. Pico do histograma desde a reversão
    3. Distância atual ≥ 2x pico do histograma
    4. Validação de volume institucional
    """
    df = get_klines(symbol)
    if df.empty or len(df) < 50:
        return False, None, 0, 0, 0, 0, "Dados insuficientes", False
    
    # Calcular MACD
    macd, signal, hist = calculate_macd(df)
    df['macd'] = macd
    df['signal'] = signal
    df['hist'] = hist
    
    # 1. Encontrar último zero line cross
    zero_cross_idx, direction = find_last_zero_cross(df['macd'])
    if zero_cross_idx is None:
        return False, None, 0, 0, 0, 0, "Sem zero line cross recente", False
    
    zero_cross_time = df['open_time'].iloc[zero_cross_idx]
    
    # 2. Encontrar pico MÁXIMO do histograma desde o zero cross
    hist_since_cross = df['hist'].iloc[zero_cross_idx:].abs()
    if hist_since_cross.empty:
        return False, None, 0, 0, 0, 0, "Sem dados pós-reversão", False
    
    max_hist_value = hist_since_cross.max()
    
    # 3. Calcular distância ATUAL entre linhas
    current_macd = df['macd'].iloc[-1]
    current_signal = df['signal'].iloc[-1]
    current_distance = abs(current_macd - current_signal)
    current_hist = abs(df['hist'].iloc[-1])
    
    # 4. Verificar condição principal: distância ≥ 2x pico do histograma
    distance_ratio = current_distance / max_hist_value if max_hist_value > 0 else 0
    condition_met = distance_ratio >= 2.0
    
    # 5. Validação de volume (filtro institucional)
    volume_score, volume_msg, volume_ratio, taker_ratio = validate_volume(symbol, df, zero_cross_idx)
    
    # 6. Decisão final: só dispara se condição MACD + volume mínimo (score ≥ 5)
    alert_triggered = condition_met and (volume_score >= 5)
    
    # Mensagem de diagnóstico detalhada
    diag = (
        f"Direção: {'🔼 Bullish' if direction == 'bullish' else '🔽 Bearish'} | "
        f"Zero cross: {zero_cross_time.strftime('%H:%M')} | "
        f"Pico hist: {max_hist_value:.4f} | "
        f"Distância atual: {current_distance:.4f} ({distance_ratio:.1f}x) | "
        f"{volume_msg}"
    )
    
    return (
        alert_triggered,
        df['open_time'].iloc[-1],
        current_distance,
        max_hist_value,
        volume_score,
        volume_ratio,
        taker_ratio,
        diag,
        condition_met
    )

def send_telegram_alert(symbol, timestamp, distance, max_hist, volume_score, volume_ratio, taker_ratio, direction):
    """Envia alerta formatado via Telegram com score de confiança"""
    if not bot:
        logger.warning("⚠️ Telegram não configurado - alerta não enviado")
        return False
    
    # Calcular score de confiança (0-100)
    confidence = min(100, volume_score * 10 + 20)  # Base 20 + volume_score*10
    
    # Direção do trade
    trade_dir = "🔼 LONG" if direction == 'bullish' else "🔽 SHORT"
    
    # Nível de confiança
    if confidence >= 80:
        confidence_emoji = "💎"
        confidence_label = "ALTA"
    elif confidence >= 60:
        confidence_emoji = "✅"
        confidence_label = "MÉDIA-ALTA"
    else:
        confidence_emoji = "⚠️"
        confidence_label = "MÉDIA"
    
    msg = (
        f"🚨 *ALERTA MACD 5m* {symbol}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕗 Horário (UTC): {timestamp.strftime('%Y-%m-%d %H:%M')}\n"
        f"📊 Padrão: Zero Line Cross + Expansão 2x\n"
        f"📈 Distância atual: {distance:.4f}\n"
        f"📏 Pico histograma: {max_hist:.4f}\n"
        f"✅ Condição: {distance:.4f} ≥ 2×{max_hist:.4f}\n"
        f"💧 Volume: {volume_ratio:.1f}x média\n"
        f"🏦 Taker Buy: {taker_ratio:.0f}%\n"
        f"{confidence_emoji} Confiança: {confidence_label} ({confidence}%)\n"
        f"💡 Ação sugerida: {trade_dir}\n"
        f"⚠️ *Validação:* Só opere com confirmação adicional (ex: FGI, volume sustentado)"
    )
    
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode='Markdown')
        logger.info(f"✅ Telegram enviado para {symbol} | Confiança: {confidence}%")
        return True
    except Exception as e:
        logger.error(f"❌ Falha ao enviar Telegram: {e}")
        return False

def log_to_history(symbol, timestamp, distance, max_hist, volume_ratio, taker_ratio, volume_score, decision):
    """Registra histórico de alertas para análise posterior"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO alert_history 
            (symbol, timestamp, macd_distance, max_histogram, volume_ratio, taker_buy_ratio, volume_score, decision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            symbol,
            int(timestamp.timestamp()),
            distance,
            max_hist,
            volume_ratio,
            taker_ratio,
            volume_score,
            decision
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"⚠️ Erro ao registrar histórico: {e}")

def check_all_symbols():
    """Verifica todos os símbolos e dispara alertas conforme critério"""
    logger.info("🔍 Iniciando verificação MACD 5m...")
    
    # Verificar horário de trading
    in_trading_hour, hour_msg = is_trading_hour()
    logger.info(hour_msg)
    
    if not in_trading_hour:
        logger.info("⏭️ Pulando verificação - fora do horário de alta liquidez")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    alert_count = 0
    current_ts = int(time.time())
    
    for symbol in SYMBOLS:
        logger.info(f"\n{'='*50}")
        logger.info(f"🔍 Analisando {symbol}...")
        
        # Obter estado anterior
        cursor.execute("SELECT last_zero_cross, max_histogram, alert_sent, last_check FROM alerts WHERE symbol=?", (symbol,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO alerts (symbol, last_zero_cross, max_histogram, alert_sent, last_check) VALUES (?, ?, ?, ?, ?)",
                         (symbol, 0, 0.0, 0, 0))
            conn.commit()
            continue
        
        last_zero_cross, prev_max_hist, alert_sent, last_check = row
        
        # Detectar padrão
        triggered, timestamp, distance, max_hist, volume_score, volume_ratio, taker_ratio, diag, macd_condition = detect_macd_pattern(symbol)
        
        logger.info(f"📊 {diag}")
        
        if triggered:
            # Evitar spam: cooldown de 15 minutos (900 segundos)
            if alert_sent == 1 and (current_ts - last_check) < 900:
                logger.warning(f"⏳ Cooldown ativo para {symbol} ({(current_ts - last_check)}s)")
                continue
            
            # Determinar direção (bullish/bearish) para o alerta
            df = get_klines(symbol)
            if not df.empty:
                macd, _, _ = calculate_macd(df)
                _, direction = find_last_zero_cross(macd)
            else:
                direction = 'bullish'
            
            # Enviar alerta
            if send_telegram_alert(symbol, timestamp, distance, max_hist, volume_score, volume_ratio, taker_ratio, direction):
                cursor.execute(
                    "UPDATE alerts SET alert_sent=1, last_check=?, volume_score=? WHERE symbol=?",
                    (current_ts, volume_score, symbol)
                )
                log_to_history(symbol, timestamp, distance, max_hist, volume_ratio, taker_ratio, volume_score, "ALERTA_ENVIADO")
                alert_count += 1
                logger.info(f"🚨 ALERTA DISPARADO para {symbol}")
            else:
                logger.warning(f"⚠️ Alerta não enviado (falha Telegram) para {symbol}")
        
        else:
            # Resetar alert_sent se condição não atendida
            if alert_sent == 1:
                cursor.execute("UPDATE alerts SET alert_sent=0 WHERE symbol=?", (symbol,))
                log_to_history(symbol, datetime.now(timezone.utc), distance, max_hist, volume_ratio, taker_ratio, volume_score, "RESET")
            
            status = "✅ Condição atendida" if macd_condition else "❌ Condição não atendida"
            logger.info(f"{status} | Score volume: {volume_score}/10")
    
    conn.commit()
    conn.close()
    
    logger.info(f"\n{'='*50}")
    logger.info(f"✅ Verificação concluída | Alertas disparados: {alert_count}")
    logger.info(f"⏰ Próxima verificação em 5 minutos")

def main():
    """Função principal - executada a cada 5 minutos pelo GitHub Actions"""
    try:
        init_database()
        check_all_symbols()
    except KeyboardInterrupt:
        logger.info("\n⏹️ Execução interrompida pelo usuário")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"❌ Erro crítico: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
