import os
import io
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import base64
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image

# =========================
# 基本設定
# =========================
try:
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="数学（PNG／超軽量 v7）", layout="wide")
st.markdown("<h1 style='font-size:20pt;'>数学（PNG／超軽量 v7）</h1>", unsafe_allow_html=True)

# =========================
# ユーティリティ関数
# =========================
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
    sec = int(max(0, sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h}時間{m}分{s}秒"
    return f"{m}分{s}秒"

# =========================
# 軽量画像キャッシュ＆一時保存
# =========================
@st.cache_data(show_spinner=False)
def load_image_fast(file_path: Path) -> str:
    """画像をキャッシュし、一時JPEGファイルURLを返す"""
    img = Image.open(file_path).convert("RGB")
    img.thumbnail((1500, 1500))  # 軽量化（縮小表示でも十分）
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    img.save(tmp.name, format="JPEG", quality=85)
    return tmp.name

def png_to_pdf_bytes(png_path: Path) -> bytes:
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
        img.save(tmp.name, format="JPEG", dpi=(200, 200))
        c.drawImage(tmp.name, x_offset, y_offset, new_w, new_h)
    c.showPage()
    c.save()
    return pdf_buf.getvalue()

def show_image_with_tools(file_path: Path):
    """画像＋PDFダウンロード＋別タブ拡大"""
    try:
        tmp_img = load_image_fast(file_path)
        st.image(tmp_img, caption=file_path.name, width=850)
        st.markdown(
            f'<a href="file://{tmp_img}" target="_blank">🔎 別タブで拡大表示（スマホ対応）</a>',
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
    except Exception as e:
        st.error(f"画像表示エラー: {e}")

# =========================
# CSVロード
# =========================
def load_answer_csv(csv_paths: List[Path]) -> Optional[pd.DataFrame]:
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift-jis"):
        for path in csv_paths:
            try:
                df = pd.read_csv(path, encoding=enc)
                df["__csv_path__"] = str(path)
                return df
            except Exception:
                continue
    return None

# =========================
# データセット読み込み
# =========================
root = "."
images = find_files(root, (".png", ".jpg", ".jpeg"))
csvs = find_files(root, (".csv",))
problems, solutions = {}, {}

for p in images:
    name = p.stem
    if name.startswith("問題"):
        try:
            problems[int(name.replace("問題", ""))] = p
        except Exception:
            pass
    elif name.startswith("解答") or name.startswith("解説"):
        try:
            solutions[int(name.replace("解答", "").replace("解説", ""))] = p
        except Exception:
            pass

answer_df = load_answer_csv(csvs)
if answer_df is None:
    st.error("CSVファイルが見つかりません。")
    st.stop()

for col in ["タイトル","ID","小問","問題レベル","答え","解説動画"]:
    if col not in answer_df.columns:
        answer_df[col] = pd.NA

answer_df["ID"] = answer_df["ID"].astype(str)
answer_df["小問"] = answer_df["小問"].astype(str)
answer_df["答え"] = answer_df["答え"].apply(as_str)
available_ids = sorted({int(x) for x in answer_df["ID"].unique() if x.isdigit()})

# =========================
# セッション管理
# =========================
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

# =========================
# 共通タイマー
# =========================
def header_timer():
    elapsed = int(time.time() - ss.problem_start_time)
    total = int(time.time() - ss.start_time)
    st.caption(f"経過時間：{seconds_to_hms(elapsed)}　｜　累計：{seconds_to_hms(total)}")

# =========================
# 各画面
# =========================
def render_problem(i: int):
    st.markdown(f"<h2>問題 {i}</h2>", unsafe_allow_html=True)
    header_timer()
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

def render_solution(i: int):
    st.subheader(f"解答記入 {i}")
    header_timer()
    rows = rows_for_id(i)

    if i in problems:
        with st.expander("問題画像を表示", expanded=False):
            show_image_with_tools(problems[i])

    st.divider()
    for _, r in rows.iterrows():
        sub = as_str(r["小問"]); key = (str(i), sub)
        colL, colM, colR = st.columns([1,2,2])
        with colL:
            st.write(f"小問 {sub}")
        with colM:
            val = st.text_input("入力", value=ss.answers.get(key, {}).get("入力", ""), key=f"in_{i}_{sub}")
            ss.answers[key] = ss.answers.get(key, {})
            ss.answers[key]["入力"] = val
        with colR:
            if "判定" in ss.answers[key]:
                st.write(ss.answers[key]["判定"])

    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        if st.button("🔎 採点", type="primary", use_container_width=True):
            per_elapsed = int(time.time() - ss.problem_start_time)
            total_elapsed = int(time.time() - ss.start_time)
            for _, r in rows.iterrows():
                sub = as_str(r["小問"]); key = (str(i), sub)
                user_inp = ss.answers.get(key, {}).get("入力", "").strip()
                correct = as_str(r["答え"]).strip()
                ss.answers[key] = {
                    "入力": user_inp,
                    "正解": correct,
                    "判定": "正解！" if user_inp == correct else "不正解",
                    "経過秒": per_elapsed,
                    "累計秒": total_elapsed,
                    "タイトル": as_str(r["タイトル"]),
                }
            ss.graded = True
    with c2:
        if st.button("◀ 問題に戻る", use_container_width=True):
            ss.phase = "problem"; st.rerun()
    with c3:
        if st.button("解説へ ▶", use_container_width=True):
            ss.phase = "explain"; st.rerun()

    if ss.graded:
        st.success("採点結果")
        res = [{"小問": k[1], **v} for k, v in ss.answers.items() if k[0] == str(i)]
        st.dataframe(pd.DataFrame(res)[["小問","入力","正解","判定"]], hide_index=True)

def render_explain(i: int):
    st.subheader(f"解説 {i}")
    header_timer()
    rows = rows_for_id(i)
    video = next((as_str(v).strip() for v in rows["解説動画"].tolist() if as_str(v).strip()), "")
    if video:
        st.markdown(f"[🎬 解説動画を見る]({video})", unsafe_allow_html=True)
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
        ss.phase = "end"; st.rerun()

def render_end():
    st.subheader("結果")
    header_timer()
    ss.user_name = st.text_input("氏名を入力してください", value=ss.user_name)
    rows = [{
        "ID": k[0],
        "小問": k[1],
        "入力": v.get("入力",""),
        "正解": v.get("正解",""),
        "判定": v.get("判定",""),
        "経過時間": seconds_to_hms(int(v.get("経過秒",0))),
        "累計時間": seconds_to_hms(int(v.get("累計秒",0))),
        "タイトル": v.get("タイトル","")
    } for k,v in ss.answers.items()]
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)
    if ss.user_name:
        buf = io.StringIO()
        ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        st.download_button("結果CSVをダウンロード", buf.getvalue().encode("utf-8-sig"),
                           file_name=f"{ss.user_name}_結果_{ts}.csv", mime="text/csv")
    st.button("はじめから", on_click=lambda: ss.clear())

# =========================
# ページルーター
# =========================
current_id = get_current_id()
if current_id is None:
    st.error("CSVのIDが不正です。"); st.stop()

st.caption(f"進行状況： {ss.current_id_idx+1}/{len(available_ids)} ｜ 現在ID：{current_id}")

if ss.phase == "problem":
    render_problem(current_id)
elif ss.phase == "solution":
    render_solution(current_id)
elif ss.phase == "explain":
    render_explain(current_id)
else:
    render_end()
