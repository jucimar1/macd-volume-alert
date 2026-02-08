## 🚨 Alerta MACD 5m com Validação Institucional via Volume

Sistema automatizado que dispara alertas quando:
1. Ocorre **zero line cross** no MACD (reversão de tendência)
2. A **distância entre linhas MACD ≥ 2x o pico do histograma** desde a reversão
3. **Volume confirma participação institucional** (filtro anti-retail)

> ✅ Funciona 100% offline após setup inicial  
> ✅ Alertas inteligentes via Telegram (só quando condições críticas atendidas)  
> ✅ Foco em horários de alta liquidez (UTC 07:00-10:00 / 12:00-16:00)

---

## 📌 Como Funciona o Critério

| Etapa | O Que Analisa | Por Que Importa |
|-------|---------------|-----------------|
| **1. Zero Line Cross** | Linha MACD cruza linha 0 | Marca início da reversão de tendência |
| **2. Pico do Histograma** | Maior valor absoluto do histograma desde a reversão | Mede força máxima do momentum inicial |
| **3. Expansão 2x** | Distância atual entre linhas ≥ 2x pico do histograma | Confirma **reaquecimento do momentum** (continuação da tendência) |
| **4. Volume Institucional** | Volume > 1.8x média + Taker Buy > 65% | Elimina fakeouts retail - só dispara com lastro real |

---

## ⚙️ Setup Passo a Passo

### 1. Criar Secrets no GitHub (Segurança Máxima)

No seu repositório GitHub:
1. **Settings → Secrets and variables → Actions → New repository secret**
2. Crie estes 4 secrets:
   - `TELEGRAM_TOKEN` = seu token do [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` = seu ID de chat (use [@userinfobot](https://t.me/userinfobot))
   - `BINANCE_API_KEY` = sua API Key da Binance (permissões: **Read-Only**)
   - `BINANCE_API_SECRET` = seu API Secret da Binance

> ⚠️ **NUNCA commite chaves no código!** Sempre use GitHub Secrets.

### 2. Configurar Símbolos (Opcional)

Edite `config.py.example` e ajuste:
```python
SYMBOLS = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]  # Adicione/remova pares macd-volume-alert
