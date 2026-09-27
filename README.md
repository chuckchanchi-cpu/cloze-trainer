# 🔤 填充練習生成器（Cloze Trainer）

中文詞語填充訓練 app — 唔使再 Copy & Paste Google Form script！

## 功能

- **揀主題（可多選）**：第1課《諾貝爾——炸藥之父》／第七課《要挑最大的》第一・二回／第八課《啟示的啟示》（基礎填空＋進階應用＋背默第3段＋課後練習六）
- **兩種生成模式**：
  - 📖 **教材原句**：直接由 76 條教材題庫抽題（100% 教材、即時、唔使 API）
  - ✨ **AI 生成新句**：qwen3.8-flash 用詞語銀行生成全新句子（每輪新鮮；答案自動校驗必須來自詞語銀行；第八課詞語銀行＝官方詞語表 16 詞）
- **每輪 5-20 題**（預設 10），選項自動洗牌
- **即場作答自動批改**：得分 + 每題 ✅/❌ + 💡 詞語解釋

## 本地執行

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 填入 API key
streamlit run app.py
```

## 部署（Streamlit Cloud）

1. 開一個新 GitHub repo（例如 `cloze-trainer`），把本資料夾內容 push 上去
2. Streamlit Cloud → Create app → 揀該 repo，Main file 填 `app.py`
3. Settings → Secrets 貼入：

```toml
OPENAI_API_KEY = "sk-..."
SILRA_API_URL = "https://api.silra.cn/v1/chat/completions"
MODEL_NAME = "qwen3.8-flash"
```

4. Deploy 完成即有公開網址，電話/平板開都得

## 題庫來源

76 條教材原句題目（第1課 18 題・第七課兩回 34 題・第八課 24 題），由 2026-09-27 綜合訓練內容直接轉換，只保留**填充題型**（工作紙近義詞運用、詞義辨析圈詞除外），保證與教材一致。AI 模式嘅詞語銀行全部來自教材詞語表（第八課用官方詞語表 16 詞）。

## 目錄

```
app.py                        # 主程式（題庫 + 兩種模式 + 自動批改）
requirements.txt
.streamlit/secrets.toml.example
```