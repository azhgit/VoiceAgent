# Voice Agent POC — 執行計劃

求職 demo 用技術規劃書：一支能真的打電話進去、即時對話、查詢並寫入模擬 CRM 的語音客服 agent。

- 可用時間：1 週以上
- 預估建置：4–5 個工作天
- 預估成本：< US$30

## 目標與定位

目標職缺要的是「能接電話、能對話、能解決問題」的 voice agent 工程能力，明確提到 conversation quality、latency、reliability，以及 CRM／business system 整合。這個 POC 刻意不用 ElevenLabs Agents 這類全託管方案——那樣做出來的是「我會組裝別人的產品」，而這裡要證明的是「我能自己維護一條即時語音管線」。

## 場景設定（Day 0 決定）

**建議場景：水電／HVAC 深夜代接派工** — 對應 JD 的 home services 垂直，情境單純但完整：

1. 來電者描述問題（漏水／無暖氣等）
2. agent 判斷緊急程度（今晚必須處理 vs 可等明天）——採固定分類規則，不靠自由心證：
   - **緊急**：明顯漏水造成損害、無暖氣且室外接近冰點、聞到瓦斯味、污水回流
   - **非緊急**：水龍頭滴水、無熱水、一般異音／保養需求
3. 呼叫工具查詢模擬 CRM 的技師排班／可預約時段
4. 訂下時段並向來電者複誦確認，或標記為緊急並模擬轉接真人

可換成汽車保養預約或物業報修，架構不受影響——換的只是 system prompt 與 mock CRM 的資料結構，建議 Day 0 早上定案就不要再換。

## 技術架構

```
來電 (Twilio Media Streams)
  → Pipecat pipeline（骨架）
  → Deepgram Nova-3（STT）
  → Claude + tool calling（對話 / 讀寫 mock CRM）
  → ElevenLabs Turbo v2.5（串流 TTS）
  → 回撥 Twilio
```

Claude 透過 tool calling 讀寫一個自建的 FastAPI mock CRM（技師排班、預約表）——這塊直接沿用 mission-app 累積的 FastAPI 經驗。ElevenLabs 帳號與 key 已驗證可用，可直接沿用；`tts.py` 的串接邏輯可作為起點，但要改寫成串流輸出而非現有的整段生成。

**Mock CRM 資料模型**：`Technician`（name、specialty、on-call flag）＋ `Appointment`（technician_id、time_slot、customer info、urgency flag、status）。可預約時段由每位技師的既有 Appointment 對照工作時段推算。種子資料規模：2–3 位技師、約 1 週排班，足以讓「查詢可預約時段」有真正的空檔可比，又不用手刻太多假資料。

**模型選擇**：預設用 Haiku（time-to-first-token 較低），只有在測試通話中明顯搞砸 tool calling 或緊急判斷時才退回 Sonnet——延遲優先、品質設下限，不是兩個都試了再選。

### 建置策略：Pipecat 打底，自己動手改

不手刻 WebSocket／音訊緩衝／VAD（太耗時），也不用託管 Agent 平台（太黑盒）。用 Pipecat 處理音訊串流骨架，但親自：

- 調整 VAD／turn-taking 的敏感度參數，理解它怎麼判斷「使用者講完了」
- 加自己的 latency instrumentation：記錄 STT 出結果、LLM 第一個 token、TTS 第一個音訊 chunk 的時間戳
- 100% 自己寫業務邏輯：system prompt、tool calling、mock CRM

這樣面試時能具體回答「延遲瓶頸在哪一段、怎麼調的」，而不是只會說「我接了一個 API」。

## 帳號與工具清單

- [ ] Twilio 帳號 + 一支美加號碼（trial 額度通常夠 demo 用）
- [ ] Deepgram 帳號 + API key（有免費試用額度）
- [ ] Anthropic API key（沿用既有的）
- [ ] ElevenLabs API key（沿用 mission-app 已驗證的那組）
- [ ] ngrok（開發期打通 Twilio webhook 用，demo 錄影也直接用這個——不部署 Railway。demo 交付物是錄影檔，不是常駐服務，省下部署這個項目）

## 時程規劃

| 階段 | 重點 | 交付物 | 風險 |
|---|---|---|---|
| Day 0（0.5 天） | 申請帳號、確認場景、scaffold Pipecat pipeline | 透過 ngrok 打通「hello world」round trip | |
| Day 1 | 寫業務邏輯 | system prompt、mock CRM endpoint、tool calling 串接 | |
| Day 2（1–1.5 天） | 延遲調校 | timing log、模型/設定比較（Haiku vs Sonnet）、VAD 閾值調整 | 高 |
| Day 3（0.5–1 天） | 打斷處理 + edge case | 插話即時停止 TTS、沉默逾時、聽不懂、掛斷 | 高 |
| Day 4（0.5 天） | demo 錄製 | 2–3 分鐘通話錄影、延遲數據視覺化 | |
| 緩衝 | 剩餘天數（1 週扣掉約 4–5 天） | 除錯與申請信文案撰寫，不要預先分配 | |

## 成本估算

| 項目 | 費率 | demo 規模估算 |
|---|---|---|
| Twilio 號碼 | $1–2/月 | $1–2 |
| Twilio 通話（in/out） | $0.0085 / $0.013 每分 | < $2 |
| Deepgram STT | $0.01–0.02 每分 | < $2 |
| Claude API | 依模型 | < $5 |
| ElevenLabs TTS（純 TTS 計費） | $0.015–0.03 每分 | < $3 |
| **合計** | | **約 $15–30** |

## 風險與對策

**Turn-taking / 打斷**
最容易吃掉整個時程的環節。對策：設 time-box，「堪用」就停手，別追求完美打斷邏輯。打斷邏輯定為 hard stop——VAD 偵測到來電者開口，立刻中止 TTS 播放、捨棄尚未說完的內容，直接處理新的來電者輸入，不做「記住沒說完的話」或緩衝判斷這類額外狀態管理。

**音訊格式**
Twilio 是 8kHz mulaw，STT/TTS 服務要對齊，否則會有雜音或延遲。對策：Day 0 就先跑通最小 round trip 驗證格式沒問題，別留到後面才發現。

**延遲疊加**
只要有一段是 batch（非 streaming），體感就會卡。對策：STT／LLM／TTS 三段都要確認是 streaming 模式，尤其 TTS 要從 mission-app 現有的整段生成邏輯改寫。

**範圍蔓延**
很容易忍不住一直加功能。對策：只做水電派工這一個情境，不做跨通話記憶、不做真人轉接的完整實作（模擬即可）。模擬轉接的具體做法：agent 唸一句台詞（「這聽起來很緊急，現在為您轉接值班技師」）後直接掛斷，不做任何真的撥號或保留音樂。訂位流程也劃線：查到可預約時段後固定回報兩個具體選項讓來電者選，不做「先問對方想要幾點、找不到再協商」這種多輪來回；技師／排班種子資料就是前面提到的 2–3 位技師、1 週份，不無限擴充。

## 交付物 / demo 成功標準

- [ ] 一通能真的打進去、agent 全程對話、能查詢並寫入 mock CRM 的通話
- [ ] agent 能被打斷且不失控（hard stop：立刻停 TTS、丟棄未講完的內容，見上方風險章節）
- [ ] edge case 都有明確行為，不是留白：
  - 沉默逾時：~8 秒無聲 → 「還在嗎？」確認一次；再 ~8–10 秒無聲 → 禮貌掛斷
  - 聽不懂：請對方重複一次；仍聽不懂 → 走模擬轉接真人流程
  - 查無可預約時段：緊急案件 → 模擬轉接真人；非緊急案件 → 提供時段外的最近可預約時間，並承諾若有空檔會回電
- [ ] 延遲數據的簡單視覺化（哪一段花多少 ms）——這本身就是申請信裡的加分展示物
- [ ] 2–3 分鐘 demo 錄影
- [ ] 一份簡短 README 說明架構，供申請信附連結

## 後續：申請信文案

demo 做完後，另外需要一份「怎麼用 AI 做的、最喜歡哪個部分」的文案。這份留到 demo 完成、有真實素材可寫的時候再處理，現在先不編。

---
