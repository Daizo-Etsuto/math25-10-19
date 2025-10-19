import os
import io
import time
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image
import tempfile

# =========================
# 基本設定
# =========================
try:
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="数学（高速・モバイル対応）", layout="wide")
st.markdown("<h1 style='font-size:20pt;'>数学（高速・モバイル対応）</h1>", unsafe_allow_html=True)

# =================
# ユーティリティ
# =================
def find_files(root: str, pattern_exts: Tuple[str, ...]) -> List[Path]:
    p = Path(root)
    found = []
    for ext in pattern_exts:
        found.extend(sorted(p.glob(f"*{ext}")))
    return found

def as_str(x) -> str:
    if pd.isna(x):
        return ""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)

def seconds_to_hms(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"

@st.cache_data
def load_image(file_path: Path):
    """画像をキャッシュして高速表示"""
    img = Image.open(file_path)
    return img

def b64_of_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")

def png_to_pdf_bytes(png_path: Path) -> bytes:
    """PNGを1ページのPDFに変換"""
    img = Image.open(png_path).convert("RGB")
    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    width, height = A4
    img_w, img_h = img.size
    ratio = min(width / img_w, height / img_h)
    new_w, new_h = img_w * ratio, img_h * ratio
    x_offset = (width - new_w) / 2
    y_offset = (height - new_h) / 2
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        img.save(tmp.name, format="JPEG", dpi=(250, 250))
        c.drawImage(tmp.name, x_offset, y_offset, new_w, new_h)
    c.showPage()
    c.save()
    return pdf_buf.getvalue()

def show_image_with_tools(file_path: Path):
    """画像をキャッシュして表示＋PDFダウンロード＋別タブ拡大"""
    img = load_image(file_path)
    st.image(img, caption=file_path.name, width=900)
    b64 = b64_of_file(file_path)
    st.markdown(
        f'<a href="data:image/png;base64,{b64}" target="_blank">🔎 別タブで拡大（スマホでピンチズーム可）</a>',
        unsafe_allow_html=True
    )
    pdf_bytes = png_to_pdf_bytes(file_path)
    st.download_button(
        label=f"📥 {file_path.stem}.pdf をダウンロード",
        data=pdf_bytes,
        file_name=f"{file_path.stem}.pdf",
        mime="application/pdf",
        key=f"dl_{file_path.name}"
    )

# =================
# データ読み込み
# =================
root = "."
images = find_files(root, (".png", ".jpg", ".jpeg"))
csvs = find_files(root, (".csv",))
problems, solutions = {}, {}

for p in images:
    n = p.stem
    if n.startswith("問題"):
        try:
            problems[int(n.replace("問題", ""))] = p
        except Exception:
            pass
    elif n.startswith("解答") or n.startswith("解説"):
        try:
            solutions[int(n.replace("解答", "").replace("解説", ""))] = p
        except Exception:
            pass

answer_df = None
for csv_path in csvs:
    try:
        answer_df = pd.read_csv(csv_path, encoding="utf-8-sig")
        break
    except Exception:
        pass
if answer_df is None:
    st.error("CSVファイルが見つかりません。")
    st.stop()

for col in ["タイトル", "ID", "小問", "問題レベル", "答え", "解説動画"]:
    if col not in answer_df.columns:
        answer_df[col] = pd.NA

answer_df["ID"] = answer_df["ID"].astype(str)
answer_df["小問"] = answer_df["小問"].astype(str)
answer_df["答え"] = answer_df["答え"].apply(as_str)
available_ids = sorted({int(x) for x in answer_df["ID"].unique() if x.isdigit()})

# =================
# セッション状態
# =================
ss = st.session_state
ss.setdefault("phase", "problem")
ss.setdefault("current_id_idx", 0)
ss.setdefault("start_time", time.time())
ss.setdefault("problem_start_time", time.time())
ss.setdefault("answers", {})
ss.setdefault("graded", False)
ss.setdefault("user_name", "")

def get_current_id():
    if not available_ids:
        return None
    if ss.current_id_idx < 0 or ss.current_id_idx >= len(available_ids):
        return None
    return available_ids[ss.current_id_idx]

def rows_for_id(i: int):
    return answer_df[answer_df["ID"] == str(i)].sort_values(by=["小問"], key=lambda s: s.astype(str))

# =================
# 経過時間更新用
# =================
def show_timer(start_time):
    elapsed = int(time.time() - start_time)
    st.markdown(f"⏱️ 経過時間：{seconds_to_hms(elapsed)}", unsafe_allow_html=True)
    st.experimental_rerun()

# =================
# 問題画面
# =================
def render_problem(i: int):
    st.markdown(f"<h2>問題 {i}</h2>", unsafe_allow_html=True)
    elapsed = int(time.time() - ss.problem_start_time)
    total = int(time.time() - ss.start_time)
    st.caption(f"経過時間：{seconds_to_hms(elapsed)}　｜　累計：{seconds_to_hms(total)}")

    if i in problems:
        show_image_with_tools(problems[i])
    else:
        st.info("問題画像が見つかりません。")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("解答記入 ▶", use_container_width=True):
            ss.phase = "solution"
            st.rerun()
    with c2:
        if st.button("問題パス ▶", use_container_width=True):
            ss.phase = "explain"
            st.rerun()

# =================
# 解答画面
# =================
def render_solution(i: int):
    st.subheader(f"解答記入 {i}")
    rows = rows_for_id(i)
    st.caption(f"経過：{seconds_to_hms(int(time.time() - ss.problem_start_time))}")

    for _, r in rows.iterrows():
        sub = as_str(r["小問"])
        key = (str(i), sub)
        colL, colM, colR = st.columns([1,2,2])
        with colL:
            st.write(f"小問 {sub}")
        with colM:
            val = st.text_input("入力", value=ss.answers.get(key, {}).get("入力", ""), key=f"in_{i}_{sub}")
            ss.answers[key] = {"入力": val}
        with colR:
            result = ss.answers.get(key, {}).get("判定", "")
            if result:
                st.write(result)

    if st.button("🔎 採点", type="primary"):
        per_elapsed = int(time.time() - ss.problem_start_time)
        total_elapsed = int(time.time() - ss.start_time)
        for _, r in rows.iterrows():
            sub = as_str(r["小問"])
            key = (str(i), sub)
            user_inp = ss.answers.get(key, {}).get("入力", "").strip()
            correct = as_str(r["答え"]).strip()
            ss.answers[key].update({
                "正解": correct,
                "判定": "正解！" if user_inp == correct else "不正解",
                "経過秒": per_elapsed,
                "累計秒": total_elapsed
            })
        ss.graded = True
        st.rerun()

    if ss.graded:
        st.divider()
        if st.button("解説を見る ▶"):
            ss.phase = "explain"
            st.rerun()

# =================
# 解説画面
# =================
def render_explain(i: int):
    st.subheader(f"解説 {i}")
    if i in solutions:
        show_image_with_tools(solutions[i])
    else:
        st.info("解説画像が見つかりません。")
    st.divider()

    if ss.current_id_idx + 1 < len(available_ids):
        if st.button("次の問題へ ▶", use_container_width=True):
            ss.current_id_idx += 1
            ss.problem_start_time = time.time()
            ss.phase = "problem"
            ss.graded = False
            st.rerun()
    else:
        st.success("全ての問題が終了しました。結果画面に移動します。")
        ss.phase = "end"
        st.rerun()

# =================
# 結果画面
# =================
def render_end():
    st.subheader("結果")
    ss.user_name = st.text_input("氏名を入力してください", value=ss.user_name)
    rows = []
    for (ID, sub), rec in ss.answers.items():
        rows.append({
            "ID": ID,
            "小問": sub,
            "入力": rec.get("入力", ""),
            "正解": rec.get("正解", ""),
            "判定": rec.get("判定", ""),
            "経過時間": seconds_to_hms(int(rec.get("経過秒",0))),
            "累計時間": seconds_to_hms(int(rec.get("累計秒",0))),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)
    if ss.user_name:
        buf = io.StringIO()
        ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        st.download_button("結果CSVをダウンロード", buf.getvalue().encode("utf-8-sig"),
                           file_name=f"{ss.user_name}_結果_{ts}.csv", mime="text/csv")
    st.button("はじめから", on_click=lambda: ss.clear())

# =================
# ルーター
# =================
current_id = get_current_id()
if current_id is None:
    st.error("CSVのIDが不正です。")
    st.stop()

st.caption(f"進行状況： {ss.current_id_idx+1}/{len(available_ids)}　｜　現在ID：{current_id}")

if ss.phase == "problem":
    render_problem(current_id)
elif ss.phase == "solution":
    render_solution(current_id)
elif ss.phase == "explain":
    render_explain(current_id)
else:
    render_end()
