import os
import io
import time
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

st.set_page_config(page_title="数学（PNG→PDF対応）", layout="wide")
st.markdown("<h1 style='font-size:20pt;'>数学（PNG→PDF対応）</h1>", unsafe_allow_html=True)

# ==============
# ユーティリティ
# ==============
def find_files(root: str, pattern_exts: Tuple[str, ...]) -> List[Path]:
    """指定拡張子のファイルを収集"""
    p = Path(root)
    found = []
    for ext in pattern_exts:
        found.extend(sorted(p.glob(f"*{ext}")))
    return found

def load_answer_csv(csv_paths: List[Path]) -> Optional[pd.DataFrame]:
    """CSV（または解答ファイル）をロード"""
    priority = [p for p in csv_paths if ("解答" in p.stem or "answer" in p.stem)]
    ordered = priority + [p for p in csv_paths if p not in priority]
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift-jis"):
        for path in ordered:
            try:
                df = pd.read_csv(path, encoding=enc)
                df["__csv_path__"] = str(path)
                return df
            except Exception:
                continue
    return None

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
    if h:
        return f"{h}時間{m}分{s}秒"
    return f"{m}分{s}秒"

# ======================
# PNG → PDF変換関数
# ======================
def png_to_pdf_bytes(png_path: Path) -> bytes:
    """PNGを1ページのPDFに変換してバイト列を返す"""
    img = Image.open(png_path).convert("RGB")
    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    width, height = A4
    img_w, img_h = img.size

    # 縦横比を保ってA4に収まるようにリサイズ
    ratio = min(width / img_w, height / img_h)
    new_w, new_h = img_w * ratio, img_h * ratio
    x_offset = (width - new_w) / 2
    y_offset = (height - new_h) / 2
    img_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    img.save(img_temp.name, format="JPEG")
    c.drawImage(img_temp.name, x_offset, y_offset, new_w, new_h)
    c.showPage()
    c.save()
    pdf_data = pdf_buf.getvalue()
    img_temp.close()
    os.unlink(img_temp.name)
    return pdf_data

# ======================
# 画像表示＆PDFダウンロード
# ======================
def show_image_with_pdf_download(file_path: Path):
    """PNG画像を表示し、PDFとしてダウンロードできるようにする"""
    st.image(str(file_path), caption=file_path.name, use_container_width=True)
    pdf_bytes = png_to_pdf_bytes(file_path)
    st.download_button(
        label=f"📥 {file_path.name.replace('.png','.pdf')} をダウンロード",
        data=pdf_bytes,
        file_name=file_path.name.replace(".png", ".pdf"),
        mime="application/pdf",
        key=f"dl_{file_path.name}"
    )
    ss.png_displayed = True

# ======================
# ファイル収集
# ======================
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
    st.error("ルートにCSVが見つかりません。")
    st.stop()

for col in ["タイトル","ID","小問","問題レベル","答え","解説動画"]:
    if col not in answer_df.columns:
        answer_df[col] = pd.NA

answer_df["ID"] = answer_df["ID"].astype(str)
answer_df["小問"] = answer_df["小問"].astype(str)
answer_df["答え"] = answer_df["答え"].apply(as_str)
available_ids = sorted({int(x) for x in answer_df["ID"].unique() if str(x).isdigit()})

# =================
# セッション管理
# =================
ss = st.session_state
ss.setdefault("phase", "problem")
ss.setdefault("current_id_idx", 0)
ss.setdefault("start_time", time.time())
ss.setdefault("problem_start_time", time.time())
ss.setdefault("answers", {})
ss.setdefault("user_name", "")
ss.setdefault("png_displayed", False)
ss.setdefault("graded", False)

def get_current_id():
    if not available_ids:
        return None
    if ss.current_id_idx < 0 or ss.current_id_idx >= len(available_ids):
        return None
    return available_ids[ss.current_id_idx]

def rows_for_id(i: int):
    return answer_df[answer_df["ID"] == str(i)].sort_values(by=["小問"], key=lambda s: s.astype(str))

# =======================
# 問題画面
# =======================
def render_problem(i: int):
    st.markdown(f"<h2 style='font-size:20pt;'>問題 {i}</h2>", unsafe_allow_html=True)
    elapsed = int(time.time() - ss.problem_start_time)
    st.caption(f"経過時間：{seconds_to_hms(elapsed)}　｜　累計時間：{seconds_to_hms(int(time.time() - ss.start_time))}")

    if i in problems:
        show_image_with_pdf_download(problems[i])
    else:
        st.info("問題画像が見つかりません。")

    if ss.png_displayed:
        st.divider()
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button("解答記入", use_container_width=True):
                ss.phase = "solution"
                ss.graded = False
                st.rerun()
        with c2:
            if st.button("問題パス", use_container_width=True):
                ss.phase = "explain"
                st.rerun()

# =======================
# 解答・採点
# =======================
def render_solution(i: int):
    st.subheader(f"解答記入 {i}")
    rows = rows_for_id(i)

    for _, r in rows.iterrows():
        sub = as_str(r["小問"])
        key = (str(i), sub)
        colL, colM, colR = st.columns([1,2,2])
        with colL:
            st.write(f"小問 {sub}")
        with colM:
            default_val = ss.answers.get(key, {}).get("入力", "")
            val = st.text_input("入力", value=default_val, max_chars=10, key=f"input_{i}_{sub}")
            if val != default_val:
                cur = ss.answers.get(key, {})
                cur["入力"] = val
                ss.answers[key] = cur
        with colR:
            result = ss.answers.get(key, {}).get("判定", "")
            if result:
                st.write(result)

    if st.button("採点", type="primary"):
        per_elapsed = int(time.time() - ss.problem_start_time)
        total_elapsed = int(time.time() - ss.start_time)
        for _, r in rows.iterrows():
            sub = as_str(r["小問"])
            key = (str(i), sub)
            user_inp = ss.answers.get(key, {}).get("入力", "").strip()
            correct = as_str(r["答え"]).strip()
            judge = "正解！" if user_inp == correct else "不正解"
            ss.answers[key] = {
                "入力": user_inp,
                "正解": correct,
                "判定": judge,
                "経過秒": per_elapsed,
                "累計秒": total_elapsed,
                "難易度": as_str(r["問題レベル"]),
                "タイトル": as_str(r["タイトル"]),
            }
        ss.graded = True
        st.rerun()

    if ss.graded:
        st.divider()
        if st.button("解説を見る ▶"):
            ss.phase = "explain"
            st.rerun()

# =======================
# 解説画面
# =======================
def render_explain(i: int):
    st.subheader(f"解説 {i}")
    rows = rows_for_id(i)
    video_links = [as_str(v) for v in rows["解説動画"].tolist() if isinstance(v, str) and v.strip()]
    if video_links:
        st.markdown(f"[🎬 解説動画を見る]({video_links[0]})", unsafe_allow_html=True)

    if i in solutions:
        show_image_with_pdf_download(solutions[i])
    else:
        st.info("解説画像が見つかりません。")

    st.divider()
    if ss.current_id_idx + 1 < len(available_ids):
        if st.button("次の問題へ ▶"):
            ss.current_id_idx += 1
            ss.problem_start_time = time.time()
            ss.png_displayed = False
            ss.phase = "problem"
            st.rerun()
    else:
        st.success("全ての問題が終了しました。結果画面に移動します。")
        ss.phase = "end"
        st.rerun()

# =======================
# 終了画面
# =======================
def render_end():
    st.subheader("終了")
    st.write("結果のCSVをダウンロードできます。")
    ss.user_name = st.text_input("氏名を入力してください", value=ss.user_name)
    rows = []
    for (ID, sub), rec in ss.answers.items():
        rows.append({
            "タイトル": rec.get("タイトル", ""),
            "小問": sub,
            "難易度": rec.get("難易度", ""),
            "正誤": "正解" if rec.get("判定","") == "正解！" else "不正解",
            "経過時間": seconds_to_hms(int(rec.get("経過秒",0))),
            "累計時間": seconds_to_hms(int(rec.get("累計秒",0))),
            "入力": rec.get("入力",""),
            "正解": rec.get("正解",""),
            "ID": ID,
        })
    df = pd.DataFrame(rows, columns=["タイトル","小問","難易度","正誤","経過時間","累計時間","入力","正解","ID"])
    st.dataframe(df, hide_index=True, use_container_width=True)

    if ss.user_name:
        buf = io.StringIO()
        timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
        filename = f"{ss.user_name}_結果_{timestamp}.csv"
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        st.download_button("結果CSVをダウンロード", buf.getvalue().encode("utf-8-sig"), file_name=filename, mime="text/csv")
    else:
        st.info("氏名を入力するとダウンロードできます。")

    st.button("はじめから", on_click=lambda: ss.clear())

# =======================
# ページルーター
# =======================
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
