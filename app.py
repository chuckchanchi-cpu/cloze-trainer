#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔤 填充練習生成器 — 中文詞語填充訓練（獨立 app）

Chuck 要求（2026-09-27）：
  - 唔使再 Copy & Paste Google Form script 去整填充練習
  - 揀主題（可多選）→ 每輪 10 題 → 自動批改 + 解釋

兩種模式：
  📖 教材原句 — 直接由教材題庫抽題（100% 教材、即時、唔使 API）
  ✨ AI 生成新句 — qwen3.8-flash 用詞語銀行生成全新句子（每輪新鮮）

部署：
  GitHub repo → Streamlit Cloud；Secrets 設定：
  OPENAI_API_KEY / SILRA_API_URL / MODEL_NAME
"""

import os
import json
import re
import random
import unicodedata
import requests
import streamlit as st

st.set_page_config(page_title="🔤 填充練習生成器", page_icon="🔤", layout="wide")

# 將 Streamlit Secrets 注入環境變數（每個 page 獨立執行，要自己注入！）
if hasattr(st, "secrets") and len(st.secrets) > 0:
    for k, v in st.secrets.items():
        os.environ[k] = str(v)

# ===== API 配置（env-first，兼容 OPENAI_* / SILRA_* 舊設定名）=====
def get_api_config():
    base = os.environ.get("OPENAI_API_BASE", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("SILRA_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL_NAME", "") or os.environ.get("MODEL_NAME", "deepseek-chat")
    if not base:
        silra_url = os.environ.get("SILRA_API_URL", "")
        if silra_url:
            base = silra_url.replace("/chat/completions", "").rstrip("/")
    if not base:
        base = "https://api.deepseek.com"
    return base, key, model

# ===== AI JSON 解析（fence 清理 + LaTeX 符號轉換 + 雜質文字抽取）=====
def parse_ai_json(content):
    """將 AI 回覆轉成 Python object；失敗回傳 None"""
    if not content:
        return None
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    # LaTeX/backslash 清理（模型有時用 \div \times \frac → 非法 JSON escape）
    # 第一步：collapse 雙反斜線（模型會將字面 \div 寫成 \\div）→ 變返單 \ 等 map 處理
    content = content.replace("\\\\", "\\")
    content = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", content)
    for tok, rep in [("\\div", "÷"), ("\\times", "×"), ("\\cdot", "·"), ("\\pm", "±"),
                     ("\\le", "≤"), ("\\ge", "≥"), ("\\neq", "≠"), ("\\%", "%"),
                     ("\\times", "×")]:
        content = content.replace(tok, rep)
    # 清除剩餘嘅 LaTeX 指令（\approx \text \left \right \mathrm...）→ 防止非法 JSON escape
    # lookahead 確保唔會連後面嘅英文字母（例如 \nA. 嘅 A）一齊食走；(?!u) 保護 \uXXXX unicode escape
    content = re.sub(r"\\(?!n|t|r|f|b|u[0-9a-fA-F]{4}|/|\"|\\\\|')[a-zA-Z]+", "", content)
    # 反斜線+符號（\÷ \× \≈ 等）→ 直接去返斜線（呢啲都係非法 JSON escape）
    content = re.sub(r"\\([^nrtbfu/\"\\0-9])", r"\1", content)
    content = content.replace("\\ ", " ").replace("\\{", "{").replace("\\}", "}")
    content = content.replace("$", "")
    def _unwrap(obj):
        # 模型有時會包多層（例如 {"questions": [...]}）→ 自動拆返個 array 出嚟
        if isinstance(obj, dict):
            for k in ("questions", "question", "題目", "data", "quiz", "items", "results", "exercises"):
                v = obj.get(k)
                if isinstance(v, list):
                    return v
        return obj

    try:
        return _unwrap(json.loads(content))
    except json.JSONDecodeError:
        m = re.search(r'[\[{].*[\]}]', content, re.S)
        if not m:
            return None
        try:
            return _unwrap(json.loads(m.group(0)))
        except json.JSONDecodeError:
            return None

def _norm(s):
    """正規化文字：全形→半形、刪走空白同引號，用嚟做寬鬆比對"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s「」『』\"'“”’（）()]+", "", s)

def _match_answer(ans, opts):
    """AI 嘅 answer 可能加咗 A/B/C/D 前綴、淨係寫字母，或者寫多咗字 — 寬鬆比對返正確選項"""
    if not ans:
        return None
    if ans in opts:
        return ans
    na = _norm(ans)
    if not na:
        return None
    for o in opts:
        if _norm(o) == na:
            return o
    m = re.fullmatch(r"[a-dA-D]", na)
    if m:
        idx = ord(m.group(0).upper()) - ord("A")
        if idx < len(opts):
            return opts[idx]
    m = re.match(r"^[a-dA-D][.、)）:：]\s*(.+)$", ans.strip())
    if m:
        cand = m.group(1).strip()
        for o in opts:
            if _norm(cand) == _norm(o):
                return o
        if cand in opts:
            return cand
    for o in opts:
        if _norm(o) and _norm(o) in na:
            return o
    return None

QUESTION_BANK = {
    'nb': {
        'name': '第1課《諾貝爾——炸藥之父》（18 詞）',
        "questions": [
            ('諾貝爾一生＿＿＿＿＿＿研究炸藥，即使多次失敗也從不氣餒。', ['頒發', '瀰漫', '屢次', '研製'], '屢次', '屢次 = 一次又一次（副詞，放動詞前）'),
            ('他＿＿＿＿＿＿於科學實驗，常常在實驗室工作至深夜。', ['醉心', '依賴', '置身', '扭曲'], '醉心', '醉心 = 沉迷、專心於某事（褒義）'),
            ('實驗發生＿＿＿＿＿＿，濃煙瞬間瀰漫在整個工場內。', ['震盪', '威脅', '炸藥', '爆炸'], '爆炸', '爆炸 = 物體劇烈破裂並發出巨響'),
            ('實驗發生爆炸，濃煙瞬間＿＿＿＿＿＿在整個工場內。', ['扭曲', '瀰漫', '震盪', '頒發'], '瀰漫', '瀰漫 = （煙、氣味等）充滿四處'),
            ('這次事故＿＿＿＿＿＿到附近居民的安全，大家都要留神。', ['獎勵', '遺囑', '研製', '威脅'], '威脅', '威脅 = 用威力逼迫、使危險'),
            ('這次事故威脅到附近居民的安全，大家都要＿＿＿＿＿＿。', ['留神', '醉心', '依賴', '置身'], '留神', '留神 = 小心、注意'),
            ('經過多年＿＿＿＿＿＿，諾貝爾終於成功製造出穩定的炸藥。', ['刨', '頒發', '研製', '震盪'], '研製', '研製 = 研究製造'),
            ('實驗失敗令儀器嚴重＿＿＿＿＿＿，但他仍堅持不懈。', ['爆炸', '依賴', '扭曲', '震盪'], '扭曲', '扭曲 = 扭得變了形'),
            ('每次實驗都令他緊張得＿＿＿＿＿＿，但他從不退縮。', ['百折不撓', '屢次', '醉心', '汗流浹背'], '汗流浹背', '汗流浹背 = 汗水濕透背脊，形容極累或非常緊張'),
            ('社會對炸藥的質疑使局勢一度＿＿＿＿＿＿。', ['扭曲', '瀰漫', '震盪', '留神'], '震盪', '震盪 = 劇烈動盪不安'),
            ('諾貝爾在＿＿＿＿＿＿中決定把遺產設立為獎金。', ['頒發', '獎勵', '遺囑', '研製'], '遺囑', '遺囑 = 生前交代後事的文件'),
            ('每年都會向傑出科學家＿＿＿＿＿＿諾貝爾獎，以獎勵他們對人類的貢獻。', ['獎勵', '依賴', '頒發', '刨'], '頒發', '頒發 = 發布、授予（獎項、證書）'),
            ('每年都會向傑出科學家頒發諾貝爾獎，以＿＿＿＿＿＿他們對人類的貢獻。', ['頒發', '醉心', '震盪', '獎勵'], '獎勵', '獎勵 = 用榮譽或財物鼓勵'),
            ('他這種＿＿＿＿＿＿的精神，值得我們學習。', ['汗流浹背', '依賴', '屢次', '百折不撓'], '百折不撓', '百折不撓 = 受盡挫折仍不屈服'),
            ('我們不能一味＿＿＿＿＿＿他人，要學懂獨立思考。', ['醉心', '留神', '依賴', '置身'], '依賴', '依賴 = 依靠別人或事物'),
            ('弟弟＿＿＿＿＿＿蘋果皮時，不小心割傷了手。', ['炸藥', '頒發', '扭曲', '刨'], '刨', '刨（páo）= 用刀削（皮），唔係 bào（刨頭）'),
            ('一旦＿＿＿＿＿＿於名利之中，便會失去方向。', ['醉心', '依賴', '留神', '置身'], '置身', '置身（於）= 把自己放在（某環境）'),
            ('諾貝爾花了畢生精力研製＿＿＿＿＿＿，希望用它來開鑿隧道、興建道路。', ['遺囑', '爆炸', '震盪', '炸藥'], '炸藥', '炸藥 = 能爆炸的藥料'),
        ],
    },
    'ch7a': {
        'name': '第七課《要挑最大的》· 第一回（17 詞）',
        "questions": [
            ('這間博物館非常有名，許多人＿＿＿＿＿＿而來參觀。', ['慕名', '捨棄', '錯過', '躊躇'], '慕名', '慕名 = 仰慕名聲（因仰慕名聲而前來）'),
            ('農夫在田裏收割金黃的＿＿＿＿＿＿，臉上掛着豐收的喜悅。', ['良機', '盡頭', '麥穗', '規矩'], '麥穗', '麥穗 = 麥子的穗；課文中比喻機會'),
            ('他輸了比賽，心裏十分＿＿＿＿＿＿，決心下次一定要贏回來。', ['漫長', '不忿', '慕名', '唯一'], '不忿', '不忿 = 心中不服氣、不高興'),
            ('湖面平靜無波，＿＿＿＿＿＿一面鏡子，倒映着藍天白雲。', ['不約而同', '金燦燦', '恍然大悟', '宛如'], '宛如', '宛如 = 好像、彷彿（書面語）'),
            ('面對兩個同樣吸引的選擇，他＿＿＿＿＿＿了很久，還是決定不了。', ['捨棄', '錯過', '漫長', '躊躇'], '躊躇', '躊躇 = 猶豫不決、拿不定主意'),
            ('＿＿＿＿＿＿的陽光灑在麥田上，整片田野都閃閃發光。', ['金燦燦', '沉甸甸', '漫長', '規矩'], '金燦燦', '金燦燦 = 金光閃閃、十分明亮的樣子'),
            ('為了追求音樂夢想，他＿＿＿＿＿＿了舒適的生活，毅然踏上創作之路。', ['錯過', '慕名', '捨棄', '躊躇'], '捨棄', '捨棄 = 丟掉、放棄不要'),
            ('麥田裏的麥穗＿＿＿＿＿＿地垂下頭來，看來今年的收成很好。', ['唯一', '盡頭', '金燦燦', '沉甸甸'], '沉甸甸', '沉甸甸 = 形容很沉重的樣子'),
            ('玩遊戲之前，要先說清楚＿＿＿＿＿＿，大家才能公平地玩。', ['麥穗', '規矩', '良機', '盡頭'], '規矩', '規矩 = 規則、標準'),
            ('他一口氣跑到街道的＿＿＿＿＿＿，才停下來喘氣。', ['良機', '規矩', '麥穗', '盡頭'], '盡頭', '盡頭 = 終點、末端'),
            ('聽到這個好消息，大家＿＿＿＿＿＿地拍手叫好。', ['恍然大悟', '躊躇', '不約而同', '捨棄'], '不約而同', '不約而同 = 沒有約定卻做出相同的事'),
            ('因為猶豫不決，他＿＿＿＿＿＿了採摘麥穗的最好時機。', ['錯過', '良機', '盡頭', '唯一'], '錯過', '錯過 = 失去（機會或時間）'),
            ('老師＿＿＿＿＿＿地對我們說：「時間一去不返，要好好珍惜。」', ['金燦燦', '語重心長', '沉甸甸', '漫長'], '語重心長', '語重心長 = 說話真誠而深刻（多指長輩教導）'),
            ('聽完老師的解釋，我＿＿＿＿＿＿，原來道理是這樣的！', ['語重心長', '不約而同', '恍然大悟', '慕名'], '恍然大悟', '恍然大悟 = 忽然明白過來'),
            ('人生的道路很＿＿＿＿＿＿，我們要一步一步踏實地走下去。', ['金燦燦', '沉甸甸', '唯一', '漫長'], '漫長', '漫長 = 很長（形容時間、道路）'),
            ('這是他＿＿＿＿＿＿的機會，一定要好好把握。', ['唯一', '良機', '漫長', '慕名'], '唯一', '唯一 = 只有一個、獨一無二'),
            ('機會來了就要馬上把握，否則就會錯失＿＿＿＿＿＿。', ['盡頭', '規矩', '良機', '麥穗'], '良機', '良機 = 良好的機會'),
        ],
    },
    'ch7b': {
        'name': '第七課 · 第二回（17 詞）',
        "questions": [
            ('這家老字號茶樓遠近馳名，不少遊客都＿＿＿＿＿＿前來一試。', ['錯過', '慕名', '躊躇', '唯一'], '慕名', '慕名 = 仰慕名聲（因仰慕名聲而前來）'),
            ('秋風吹過，田裏的＿＿＿＿＿＿隨風搖擺，像一片金色的海洋。', ['麥穗', '良機', '規矩', '盡頭'], '麥穗', '麥穗 = 麥子的穗；課文中比喻機會'),
            ('明明是他先動手，卻要罰我，我實在＿＿＿＿＿＿！', ['捨棄', '恍然大悟', '不忿', '慕名'], '不忿', '不忿 = 心中不服氣、不高興'),
            ('雨後的彩虹掛在天邊，＿＿＿＿＿＿一座七彩的橋。', ['金燦燦', '沉甸甸', '不約而同', '宛如'], '宛如', '宛如 = 好像、彷彿（書面語）'),
            ('他站在門口＿＿＿＿＿＿了一會，終於鼓起勇氣敲門。', ['捨棄', '錯過', '慕名', '躊躇'], '躊躇', '躊躇 = 猶豫不決、拿不定主意'),
            ('沙灘上＿＿＿＿＿＿的幼沙，在陽光下閃閃發亮。', ['沉甸甸', '金燦燦', '漫長', '規矩'], '金燦燦', '金燦燦 = 金光閃閃、十分明亮的樣子'),
            ('為了照顧生病的媽媽，她＿＿＿＿＿＿了出國進修的機會。', ['捨棄', '錯過', '躊躇', '慕名'], '捨棄', '捨棄 = 丟掉、放棄不要'),
            ('他背着＿＿＿＿＿＿的書包，一步一步走上樓梯。', ['金燦燦', '唯一', '沉甸甸', '盡頭'], '沉甸甸', '沉甸甸 = 形容很沉重的樣子'),
            ('在圖書館要保持安靜，這是人人都要遵守的＿＿＿＿＿＿。', ['盡頭', '良機', '規矩', '麥穗'], '規矩', '規矩 = 規則、標準'),
            ('沿着這條小路走到＿＿＿＿＿＿，就會看到一座燈塔。', ['規矩', '良機', '麥穗', '盡頭'], '盡頭', '盡頭 = 終點、末端'),
            ('考試結束的鈴聲一響，同學們＿＿＿＿＿＿地放下鉛筆。', ['躊躇', '捨棄', '恍然大悟', '不約而同'], '不約而同', '不約而同 = 沒有約定卻做出相同的事'),
            ('因為遲到，他＿＿＿＿＿＿了巴士，只好等下一班。', ['良機', '盡頭', '錯過', '唯一'], '錯過', '錯過 = 失去（機會或時間）'),
            ('爸爸＿＿＿＿＿＿地提醒我：「做人要腳踏實地。」', ['沉甸甸', '金燦燦', '語重心長', '漫長'], '語重心長', '語重心長 = 說話真誠而深刻（多指長輩教導）'),
            ('看到答案的那一刻，我＿＿＿＿＿＿，原來自己算漏了一步。', ['不約而同', '恍然大悟', '語重心長', '慕名'], '恍然大悟', '恍然大悟 = 忽然明白過來'),
            ('在＿＿＿＿＿＿的暑假裏，他讀完了五本課外書。', ['沉甸甸', '金燦燦', '唯一', '漫長'], '漫長', '漫長 = 很長（形容時間、道路）'),
            ('這條鑰匙是＿＿＿＿＿＿一條，千萬不要弄丟。', ['良機', '漫長', '慕名', '唯一'], '唯一', '唯一 = 只有一個、獨一無二'),
            ('航空公司推出優惠，正是出外旅遊的＿＿＿＿＿＿。', ['盡頭', '規矩', '麥穗', '良機'], '良機', '良機 = 良好的機會'),
        ],
    },
    'ch8a': {
        'name': '第八課《啟示的啟示》· 基礎填空（10 題）',
        "questions": [
            ('牆壁上，一隻蟲子在艱難地往上爬，爬到一大半，忽然＿＿＿＿＿＿了下來。這是牠又一次失敗的紀錄。', ['爬', '嘆氣', '跌落', '反省'], '跌落', '跌落 = 從高處掉下來'),
            ('然而，過了一會兒，牠又沿着牆根，一步一步地往上＿＿＿＿＿＿了。', ['跌落', '執著', '盲目', '爬'], '爬', '爬 = 向上移動'),
            ('第一個人注視着這隻蟲子，感嘆説：「一隻小小的蟲子，這樣的＿＿＿＿＿＿、頑強；失敗了，不屈服；跌倒了，從頭來；真是百折不回啊！」', ['退縮', '執著', '盲目', '反省'], '執著', '執著 = 堅持不懈'),
            ('第一個人注視着這隻蟲子，感嘆説：「一隻小小的蟲子，這樣的執著、頑強；失敗了，不屈服；跌倒了，從頭來；真是＿＿＿＿＿＿啊！」', ['執著', '頑強', '百折不回', '可悲'], '百折不回', '百折不回 = 經歷多次挫折也不退縮'),
            ('第二個人注視着這隻蟲子，禁不住＿＿＿＿＿＿説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？」', ['反省', '可悲', '嘆氣', '見解'], '嘆氣', '嘆氣 = 因失望而呼氣'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣＿＿＿＿＿＿地爬行，甚麼時候才能爬到牆頭呢？」', ['稍微', '執著', '跌落', '盲目'], '盲目', '盲目 = 沒有主見、不清楚目標'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？只要＿＿＿＿＿＿改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願反省，不肯想一想。」', ['反省', '退縮', '稍微', '盲目'], '稍微', '稍微 = 略微、一點點'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？只要稍微改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願＿＿＿＿＿＿，不肯想一想。」', ['自暴自棄', '稍微', '盲目', '反省'], '反省', '反省 = 自我檢討、反思'),
            ('唉——＿＿＿＿＿＿的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭蠻幹一氣了——我是個有頭腦的人，可不是蟲子！', ['頑強', '可悲', '執著', '百折不回'], '可悲', '可悲 = 值得同情、令人悲哀'),
            ('唉——可悲的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭＿＿＿＿＿＿一氣了——我是個有頭腦的人，可不是蟲子！', ['反省', '盲目', '爬', '蠻幹'], '蠻幹', '蠻幹 = 不講方法地硬幹'),
        ],
    },
    'ch8b': {
        'name': '第八課 · 進階應用（4 題）',
        "questions": [
            ('智者回答：「兩個人都對。」因為他們的＿＿＿＿＿＿都來自於對同一隻蟲子的觀察，只是角度不同。', ['啓示', '反省', '見解', '退縮'], '見解', '見解 = 看問題的角度和立場'),
            ('第三個人詢問智者：「觀察同一隻蟲子，兩個人的見解和判斷截然相反，得到的＿＿＿＿＿＿迥然不同。可敬的智者，請您說說，他們哪一個對呢？」', ['見解', '可悲', '反省', '啓示'], '啓示', '啓示 = 領悟的道理、教訓'),
            ('這則故事告訴我們：面對困難，不能＿＿＿＿＿＿或自暴自棄；但也不能蠻幹，要懂得反省和改變方向。', ['蠻幹', '盲目', '退縮', '可悲'], '退縮', '退縮 = 畏懼困難而後退'),
            ('這則故事告訴我們：面對困難，不能退縮或自暴自棄；但也不能＿＿＿＿＿＿，要懂得反省和改變方向。', ['反省', '盲目', '稍微', '蠻幹'], '蠻幹', '蠻幹 = 不講方法地硬幹'),
        ],
    },
    'ch8m': {
        'name': '第八課 · 背默第 3 段（5 題漸進式）',
        "questions": [
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣＿＿＿＿＿＿地爬行，甚麼時候才能爬到牆頭呢？只要稍微改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願反省，不肯想一想。唉——可悲的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭蠻幹一氣了——我是個有頭腦的人，可不是蟲子！」', ['稍微', '執著', '盲目', '反省'], '盲目', '提示：第一個空格，形容爬行方式'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？只要＿＿＿＿＿＿改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願反省，不肯想一想。唉——可悲的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭蠻幹一氣了——我是個有頭腦的人，可不是蟲子！」', ['盲目', '反省', '退縮', '稍微'], '稍微', '提示：第二個空格，表示程度輕微'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？只要稍微改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願＿＿＿＿＿＿，不肯想一想。唉——可悲的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭蠻幹一氣了——我是個有頭腦的人，可不是蟲子！」', ['自暴自棄', '盲目', '反省', '稍微'], '反省', '提示：第三個空格，與「不願」搭配'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？只要稍微改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願反省，不肯想一想。唉——＿＿＿＿＿＿的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭蠻幹一氣了——我是個有頭腦的人，可不是蟲子！」', ['頑強', '可悲', '執著', '百折不回'], '可悲', '提示：第四個空格，表達感慨'),
            ('第二個人注視着這隻蟲子，禁不住嘆氣説：「可憐的蟲子！這樣盲目地爬行，甚麼時候才能爬到牆頭呢？只要稍微改變一下方向，牠就能夠很容易地爬上去；可是牠就是不願反省，不肯想一想。唉——可悲的蟲子！咦？我自己呢？我正在做的那件事一再失利，似乎應該聰明一點兒，不可以再悶着頭＿＿＿＿＿＿一氣了——我是個有頭腦的人，可不是蟲子！」', ['反省', '盲目', '蠻幹', '爬'], '蠻幹', '提示：最後一個空格，與「悶着頭」搭配'),
        ],
    },
    'ch8h': {
        'name': '第八課 · 課後練習六（5 題）',
        "questions": [
            ('他少年時結交損友，染上毒癮，最後更落得眾叛親離的結局，實在＿＿＿＿＿＿。', ['反省', '可悲', '自暴自棄', '百折不回'], '可悲', '可悲 = 值得同情、令人悲哀'),
            ('我們來到泳灘才看見掛上了紅旗，不能下水游泳，妹妹失望得不斷＿＿＿＿＿＿。', ['可悲', '自暴自棄', '嘆氣', '見解'], '嘆氣', '嘆氣 = 因失望、傷感而呼氣'),
            ('叔叔失業後，不但沒有＿＿＿＿＿＿，反而努力進修，學習新技能。', ['反省', '退縮', '嘆氣', '自暴自棄'], '自暴自棄', '自暴自棄 = 自己輕視自己，不求上進'),
            ('你遇到挫折時，不要先急着埋怨別人，而是應該好好＿＿＿＿＿＿，尋找解決問題的方法，這樣才會進步。', ['自暴自棄', '退縮', '盲目', '反省'], '反省', '反省 = 自我檢討、反思'),
            ('這位科學家憑著＿＿＿＿＿＿的精神，經歷無數次試驗失敗仍能再接再厲，最終取得豐碩的成果。', ['執著', '頑強', '可悲', '百折不回'], '百折不回', '百折不回 = 經歷多次挫折也不退縮'),
        ],
    },
}

AI_TOPICS = {
    "nb": {
        "name": "第1課《諾貝爾——炸藥之父》",
        "context": "課文講諾貝爾醉心研究炸藥，屢次失敗仍不放棄；實驗室發生爆炸、濃煙瀰漫，威脅居民安全；他汗流浹背仍堅持，百折不撓，最終成功研製穩定炸藥；晚年立下遺囑，用遺產設立諾貝爾獎，頒發給傑出科學家作為獎勵。",
        "words": [
            ("炸藥", "能爆炸的藥料"),
            ("刨", "用刀削（皮）；呢度讀 páo，唔係 bào"),
            ("爆炸", "物體劇烈破裂並發出巨響"),
            ("瀰漫", "（煙、氣味等）充滿四處"),
            ("扭曲", "扭得變了形"),
            ("遺囑", "生前交代後事的文件"),
            ("留神", "小心、注意"),
            ("置身", "把自己放在（某環境）"),
            ("威脅", "用威力逼迫、使危險"),
            ("研製", "研究製造"),
            ("醉心", "沉迷、專心於某事"),
            ("依賴", "依靠別人或事物"),
            ("汗流浹背", "汗水濕透背脊，形容極累或非常緊張"),
            ("震盪", "劇烈動盪不安"),
            ("屢次", "一次又一次"),
            ("百折不撓", "受盡挫折仍不屈服"),
            ("頒發", "發布、授予（獎項、證書）"),
            ("獎勵", "用榮譽或財物鼓勵"),
        ],
    },
    "ch7": {
        "name": "第七課《要挑最大的》（兩回 + 工作紙）",
        "context": "課文講蘇格拉底帶學生到麥田，要學生由田頭行到田尾，揀一棵最大嘅麥穗，但不能回頭；學生見到金燦燦、沉甸甸嘅麥穗，卻因躊躇而錯過良機，最後空手而回，恍然大悟：機會一閃即逝，唯一嘅麥穗往往喺盡頭，要把握時機，唔好一味捨棄。",
        "words": [
            ("慕名", "仰慕名聲"),
            ("麥穗", "麥子的穗；課文中比喻機會"),
            ("不忿", "心中不服氣、不高興"),
            ("宛如", "好像、彷彿"),
            ("躊躇", "猶豫不決、拿不定主意"),
            ("金燦燦", "金光閃閃、十分明亮"),
            ("捨棄", "丟掉、放棄不要"),
            ("沉甸甸", "形容很沉重的樣子"),
            ("規矩", "規則、標準"),
            ("盡頭", "終點、末端"),
            ("不約而同", "沒有約定卻做出相同的事"),
            ("錯過", "失去（機會或時間）"),
            ("語重心長", "說話真誠而深刻"),
            ("恍然大悟", "忽然明白過來"),
            ("漫長", "很長（形容時間、道路）"),
            ("唯一", "只有一個、獨一無二"),
            ("良機", "良好的機會"),
            ("時機", "做事的適當時間"),
            ("機會", "有利的境遇"),
        ],
    },
    "ch8": {
        "name": "第八課《啟示的啟示》（官方詞語表 16 詞）",
        "context": "課文講牆上一隻蟲子盲目咁向上爬，跌落又再爬；第一個人讚佢執著頑強、百折不回；第二個人感歎話佢盲目可悲，只要稍微改變方向就易爬上去，但佢唔願反省；兩個人的見解迥然不同，智者話兩個人嘅觀點都啱；故事教訓：面對困難唔可以退縮或自暴自棄，但亦唔可以蠻幹，要懂得反省，改變方向。",
        "words": [
            ("啟示", "領悟到的道理、教訓（寫「啓示」亦算啱）"),
            ("執著", "堅持不懈、不放棄"),
            ("退縮", "畏懼困難而後退"),
            ("蠻幹", "不講方法地硬幹"),
            ("迥然", "形容差別很大、完全不一樣（迥然不同）"),
            ("感歎", "因有所感觸而嘆息"),
            ("屈服", "低頭認輸、放棄抵抗"),
            ("百折不回", "經歷多次挫折也不退縮"),
            ("自暴自棄", "自己輕視自己，不求上進"),
            ("歎氣", "因失望、傷感而呼氣（寫「嘆氣」亦算啱）"),
            ("盲目", "沒有主見、不清楚目標"),
            ("稍微", "略微、一點點"),
            ("改變", "使事物和原來不一樣；改動"),
            ("反省", "自我檢討、反思"),
            ("可悲", "值得同情、令人悲哀"),
            ("觀點", "對事物的看法、立場"),
        ],
    },
}

# ===== 頁面 =====
st.title("🔤 填充練習生成器")
st.caption("中文詞語填充訓練 — 揀主題 → 每輪出題 → 即場作答自動批改。唔使再 Copy & Paste Google Form！")

if "fill_questions" not in st.session_state:
    st.session_state.fill_questions = []
if "fill_checked" not in st.session_state:
    st.session_state.fill_checked = False

def options_for_mode(mode_is_ai):
    if mode_is_ai:
        return [k for k in AI_TOPICS]
    return list(QUESTION_BANK.keys())

def label_for(k, mode_is_ai):
    return AI_TOPICS[k]["name"] if mode_is_ai else QUESTION_BANK[k]["name"]

def ai_generate(count, topics):
    api_base, api_key, model = get_api_config()
    if not api_key:
        st.error("⚠️ 未偵測到 API key — 請喺 Streamlit Cloud Secrets 設定 OPENAI_API_KEY（或本地 .streamlit/secrets.toml）")
        return []
    bank_lines, ctx_lines, word_set = [], [], set()
    for t in topics:
        info = AI_TOPICS[t]
        ctx_lines.append(f"【{info['name']}】{info['context']}")
        for w, d in info["words"]:
            bank_lines.append(f"- {w}：{d}")
            word_set.add(w)
    system_prompt = f"""你係一位經驗豐富嘅小學六年級中文科老師，專責出「詞語填充」練習題。

**詞語銀行（只准用呢啲詞語出題，一個都唔可以超出；正確答案必須原字照寫）：**
{chr(10).join(bank_lines)}

**課文主題情境（出句要圍繞呢啲情境，唔可以加教材內容以外嘅事實）：**
{chr(10).join(ctx_lines)}

**題目要求：**
1. 每題一條完整句子，正式書面語、繁體中文（學校測驗卷風格），內容符合課文情境
2. 每題得一個空格，用「＿＿＿＿＿＿」表示
3. 4 個選項：1 個正確答案 + 3 個干擾詞，全部必須嚟自詞語銀行；「answer」欄必須同「options」入面正確嗰個選項**字面完全一樣**（原字照寫詞語銀行嘅詞，唔准加 A/B/C/D 前綴、唔准加括號或任何備註）
4. 干擾詞要「似層層」：近義／同詞性／喺課文同一情境出現過，唔好一眼就睇出錯
5. 唔可以自創詞語或改寫詞語（例如唔可以將「汗流浹背」寫成「汗流夾背」）
6. 每題附 hint：用詞語銀行嘅解釋，書面語講解點解揀呢個詞

**輸出格式（只輸出 JSON array，唔好有其他文字）：**
[{{"question": "...", "options": ["...", "...", "...", "..."], "answer": "...", "hint": "..."}}]"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"請根據詞語銀行生成 {count} 條填充選擇題（每題一個空格、4 個選項、附 hint；answer 必須原字照寫 options 入面正確嗰個詞語，唔准加 A/B/C/D 前綴）。"},
        ],
        "max_tokens": 6000,
        "temperature": 0.8,
        "enable_thinking": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{api_base}/chat/completions", json=payload, headers=headers, timeout=180)
    except requests.exceptions.RequestException as e:
        st.error(f"❌ 連唔到 API：{e}")
        return []
    if r.status_code != 200:
        st.error(f"❌ AI 生成失敗（錯誤碼 {r.status_code}）：{r.text[:200]}")
        return []
    content = r.json()["choices"][0]["message"]["content"]
    data = parse_ai_json(content)
    if not isinstance(data, list):
        st.error("❌ AI 回覆格式唔啱，再試一次？")
        return []
    valid = []
    for item in data:
        q = (item.get("question") or "").strip()
        opts = item.get("options") or []
        ans = (item.get("answer") or "").strip()
        hint = (item.get("hint") or "").strip()
        if not q or not isinstance(opts, list) or len(opts) != 4:
            continue
        clean_opts = [o.strip() for o in opts]
        matched = _match_answer(ans, clean_opts)
        if matched is None or matched not in word_set:
            continue
        valid.append({"q": q, "options": clean_opts, "answer": matched, "hint": hint})
    if not valid:
        st.error("❌ AI 生成嘅題目全部唔合格（答案唔喺詞語銀行）— 再試一次？")
    return valid[:count]

def build_round(mode_is_ai, topics, count):
    """生成一輪題目；成功回 True，失敗（例如 AI 出錯）回 False — 失敗時唔 rerun，等錯誤訊息留喺畫面"""
    if mode_is_ai:
        with st.spinner("✨ AI 生成緊句子，請稍候…（約 10–30 秒）"):
            qs = ai_generate(count, topics)
    else:
        pool = [q for t in topics for q in QUESTION_BANK[t]["questions"]]
        random.shuffle(pool)
        qs = []
        for q, choices, ans, hint in pool[:count]:
            opts = list(choices)
            random.shuffle(opts)
            qs.append({"q": q, "options": opts, "answer": ans, "hint": hint})
    if not qs:
        return False
    st.session_state.fill_questions = qs
    st.session_state.fill_checked = False
    return True

# ===== Sidebar =====
with st.sidebar:
    st.header("⚙️ 設定")
    mode_is_ai = st.radio("生成模式", ["📖 教材原句（即時・100% 教材）", "✨ AI 生成新句（qwen3.8-flash）"], key="fill_mode") == "✨ AI 生成新句（qwen3.8-flash）"
    all_opts = options_for_mode(mode_is_ai)
    topics = st.multiselect(
        "揀主題（可多選）",
        all_opts,
        format_func=lambda k: label_for(k, mode_is_ai),
        key="fill_topics",
    )
    count = st.slider("每輪題數", 5, 20, 10, key="fill_count")
    if st.button("🎲 生成題目", type="primary", use_container_width=True):
        if not topics:
            st.warning("⚠️ 請先揀至少一個主題")
        else:
            try:
                if build_round(mode_is_ai, topics, count):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ 出錯：{e}")
    if topics:
        with st.expander("📚 詞語銀行"):
            if mode_is_ai:
                for t in topics:
                    st.markdown(f"**{AI_TOPICS[t]['name']}**（{len(AI_TOPICS[t]['words'])} 詞）")
                    st.write("、".join(w for w, _ in AI_TOPICS[t]["words"]))
            else:
                for t in topics:
                    st.markdown(f"**{QUESTION_BANK[t]['name']}**（{len(QUESTION_BANK[t]['questions'])} 題）")

st.divider()

# ===== 出題 =====
if not st.session_state.fill_questions:
    st.info("👈 左邊 sidebar：揀生成模式 → 揀主題（可多選）→ 㩒「🎲 生成題目」開始！")
    bank_total = sum(len(v["questions"]) for v in QUESTION_BANK.values())
    st.markdown(f"📚 **題庫規模：** 共 {bank_total} 條教材原句題目，涵蓋第1・7・8課全部填充內容。")
    st.stop()

qs = st.session_state.fill_questions
st.subheader(f"📝 今輪 {len(qs)} 題")
for i, item in enumerate(qs):
    st.radio(f"**{i + 1}.** {item['q']}", item["options"], key=f"fill_a{i}", index=None)

c1, c2, c3 = st.columns([1, 1, 3])
if not st.session_state.fill_checked:
    if c1.button("✅ 檢查答案", type="primary"):
        st.session_state.fill_checked = True
        st.rerun()
else:
    results = []
    for i, item in enumerate(qs):
        user = st.session_state.get(f"fill_a{i}")
        results.append((i, user, user == item["answer"]))
    correct = sum(1 for _, _, ok in results if ok)
    st.metric("🏆 得分", f"{correct} / {len(qs)}")
    for i, user, ok in results:
        item = qs[i]
        if ok:
            st.success(f"**✅ 第 {i + 1} 題**（你揀咗「{user}」）")
        else:
            st.error(f"**❌ 第 {i + 1} 題**　你揀咗：「{user or '（未作答）'}」　正確答案：**{item['answer']}**")
        st.caption("💡 " + item["hint"])
    st.markdown("---")

if c2.button("🔄 再嚟一輪", use_container_width=True):
    mode_is_ai = st.session_state.fill_mode == "✨ AI 生成新句（qwen3.8-flash）"
    topics = st.session_state.fill_topics
    count = st.session_state.fill_count
    if topics:
        try:
            if build_round(mode_is_ai, topics, count):
                st.rerun()
        except Exception as e:
            st.error(f"❌ 出錯：{e}")
