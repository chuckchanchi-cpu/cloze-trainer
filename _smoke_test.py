# -*- coding: utf-8 -*-
"""Smoke test：語法 + AI 主題覆蓋檢查（教材主題必須有對應 AI 生成選項）"""
import py_compile, ast, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
py_compile.compile("app.py", doraise=True)
print("✅ syntax OK")

tree = ast.parse(open("app.py", encoding="utf-8").read())
ns = {}
for node in tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in ("AI_TOPICS", "QUESTION_BANK"):
                ns[t.id] = ast.literal_eval(node.value)
qb, ai = ns["QUESTION_BANK"], ns["AI_TOPICS"]
print(f"✅ QUESTION_BANK: {len(qb)} 主題 / AI_TOPICS: {len(ai)} 主題")

# 教材子主題 → AI 彙整主題（ch7 兩回 → ch7；ch8 四份 → ch8）
mapping = {"ch7a": "ch7", "ch7b": "ch7", "ch8a": "ch8", "ch8b": "ch8", "ch8m": "ch8", "ch8h": "ch8"}
for qk in qb:
    aik = mapping.get(qk, qk)
    if aik not in ai:
        print(f"❌ {qk} 冇對應 AI 主題！")
        continue
    words = {w for w, _ in ai[aik]["words"]}
    answers = {q[2] for q in qb[qk]["questions"]}
    gaps = answers - words
    flag = "✅" if not gaps else "⚠️"
    print(f"{flag} {qk} → AI[{aik}]: 答案覆蓋 {len(answers & words)}/{len(answers)}" + (f"（詞語銀行未含 {gaps}，屬正常）" if gaps else ""))
print("done")
