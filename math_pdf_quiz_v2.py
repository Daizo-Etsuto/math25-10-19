import os
import io
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# =========================
# 基本設定
# =========================
try:
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="数学（PNG／超高速 v8）", layout="wide")
st.markdown("<h1 style='font-size:20pt;'>数学（PNG／超高速 v8）</h1>", unsafe_allow_html=True)

# =========================
# ユーティリティ
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

def load_answer_csv(csv_paths: List[Path]) -> Optional[pd.DataFrame]:
    """CSV（回答定義）をロード（複数エンコーディング試行）"""
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

def resize_to_width(img: Image.Image, target_w: int) -> Image.Image:
    """画面表示用に一度だけ軽量リサイズ（高品質・文字くっきりのまま）"""
    w, h = img.size
    if w <= target_w:
        return img
    ratio = target_w / w
    new_size = (target_w, max(1, int(h * ratio)))
    return img.resize(new_size, Image.LANCZOS)

def img_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")  # 文字のにじみを避けるためPNGを維持
    return buf.getvalue()

def png_to_pdf_bytes(png_path: Path) -> bytes:
    """元PNGをA4に等比フィットでPDF化（ダウンロード用のみ実行）"""
    img = Image.open(png_path).convert("RGB")
    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    width, height = A4
    img_w, img_h = img.size
    ratio = min(width / img_w, height / img_h)
    new_w, new_h = img_w * ratio, img_h * ratio
    x_offset = (width - new_w) / 2
    y_offset = (height - new_h) / 2
    # 一時JPEG経由で高速・軽量配置（PDFの埋め込み互換性向上）
    tmp = io.BytesIO()
    img.save(tmp, format="JPEG", quality=95)  # 品質高め
    tmp.seek(0)
    # reportlabはファイルパスが不要、BytesIOを受け付けないためdrawImageは名前が必要
    # → 一時ファイルを使う
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
        f.write(tmp.read())
        temp_name = f.name
    c.drawImage(temp_name, x_offset, y_offset, new_w, new_h)
    c.showPage()
    c.save()
    try:
        os.unlink(temp_name)
    except Exception:
        pass
    return pdf_buf.getvalue()

# =========================
# データ読み込み（画像＆CSV）
# =========================
root = "."
image_paths = find_files(root, (".png", ".jpg", ".jpeg"))
csv_paths = find_files(root, (".csv",))

answer_df = load_answer_csv(csv_paths)
if answer_df is None:
    st.error("CSVファイルが見つかりません（例：数学解答_見本.csv）。")
    st.stop()

# 必須列を補完
for col in ["タイトル", "ID", "小問", "問題レベル", "答え", "解説動画"]:
    if col not in answer_df.columns:
        answer_df[col] = pd.NA
answer_df["ID"] = answer_df["ID"].astype(str)
answer_df["小問"] = answer_df["小問"].astype(str)
answer_df["答え"] = answer_df["答え"].apply(as_str)

available_ids = sorted({int(x) for x in answer_df["ID"].unique() if x.isdigit()})
if not available_ids:
    st.error("CSVのIDが不正です。")
    st.stop()

# 問題・解説画像のパス辞書化
problem_paths: Dict[int, Path] = {}
solution_paths: Dict[int, Path] = {}
for p in image_paths:
    name = p.stem
    if name.startswith("問題"):
        try:
            problem_paths[int(name.replace("問題", ""))] = p
        except Exception:
            pass
    elif name.startswith("解答") or name.startswith("解説"):
        try:
            solution_paths[int(name.replace("解答", "").replace("解説", ""))] = p
        except Exception:
            pass

# =========================
# セッション管理
# =========================
ss = st.session_state
ss.setdefault("phase", "problem")             # problem / solution / explain / end
ss.setdefault("current_id_idx", 0)
ss.setdefault("start_time", time.time())
ss.setdefault("problem_start_time", time.time())
ss.setdefault("answers", {})                  # {(ID,小問): {...}}
ss.setdefault("graded", False)
ss.setdefault("user_name", "")

# 画像プリロード（起動時1回のみ）
if "image_cache" not in ss:
    ss.image_cache = {}  # {("problem"/"solution", id): {"display": bytes, "orig": Path}}
    TARGET_WIDTH = 900
    for key_id, pth in problem_paths.items():
        try:
            img = Image.open(pth).convert("RGB")
            disp = resize_to_width(img, TARGET_WIDTH)
            ss.image_cache[("problem", key_id)] = {"display": img_to_png_bytes(disp), "orig": pth}
        except Exception:
            pass
    for key_id, pth in solution_paths.items():
        try:
            img = Image.open(pth).convert("RGB")
            disp = resize_to_width(img, TARGET_WIDTH)
            ss.image_cache[("solution", key_id)] = {"display": img_to_png_bytes(disp), "orig": pth}
        except Exception:
            pass

def get_current_id() -> Optional[int]:
    if ss.current_id_idx < 0 or ss.current_id_idx >= len(available_ids):
        return None
    return available_ids[ss.current_id_idx]

def rows_for_id(i: int) -> pd.DataFrame:
    rows = answer_df[answer_df["ID"] == str(i)].copy()
    if rows.empty:
        return rows
    return rows.sort_values(by=["小問"], key=lambda s: s.astype(str))

def header_timer():
    # （B）操作時のみ更新：ここでは表示のみ
    elapsed = int(time.time() - ss.problem_start_time)
    total = int(time.time() - ss.start_time)
    st.caption(f"経過時間：{seconds_to_hms(elapsed)}　｜　累計：{seconds_to_hms(total)}")

def show_cached_image(kind: str, i: int):
    """プリロードした画像bytesを即描画（超高速・ノー処理）"""
    rec = ss.image_cache.get((kind, i))
    if not rec:
        st.info("画像が見つかりません。")
        return
    st.image(rec["display"], caption=f"{'問題' if kind=='problem' else '解説'} {i}", use_container_width=False)

def pdf_download_button(kind: str, i: int):
    rec = ss.image_cache.get((kind, i))
    if not rec:
        return
    try:
        pdf_bytes = png_to_pdf_bytes(rec["orig"])
        st.download_button(
            label=f"📥 {('問題' if kind=='problem' else '解説')}{i}.pdf をダウンロード",
            data=pdf_bytes,
            file_name=f"{('問題' if kind=='problem' else '解説')}{i}.pdf",
            mime="application/pdf",
            key=f"dl_{kind}_{i}"
        )
    except Exception as e:
        st.error(f"PDF変換エラー: {e}")

# =========================
# 各画面
# =========================
def render_problem(i: int):
    st.markdown(f"<h2>問題 {i}</h2>", unsafe_allow_html=True)
    header_timer()

    show_cached_image("problem", i)
    pdf_download_button("problem", i)

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("解答記入 ▶", use_container_width=True):
            ss.phase = "solution"
            # （B）タイマーは更新しない
            st.rerun()
    with c2:
        if st.button("問題パス ▶", use_container_width=True):
            ss.phase = "explain"
            st.rerun()

def render_solution(i: int):
    st.subheader(f"解答記入 {i}")
    header_timer()

    # 画像は必要時のみ（折りたたみ）
    if ("problem", i) in ss.image_cache:
        with st.expander("問題画像を表示", expanded=False):
            show_cached_image("problem", i)
            pdf_download_button("problem", i)

    rows = rows_for_id(i)
    st.divider()
    for _, r in rows.iterrows():
        sub = as_str(r["小問"]); key = (str(i), sub)
        colL, colM, colR = st.columns([1,2,2])
        with colL:
            st.write(f"小問 {sub}")
        with colM:
            val = st.text_input("入力", value=ss.answers.get(key, {}).get("入力", ""), key=f"in_{i}_{sub}")
            cur = ss.answers.get(key, {})
            cur["入力"] = val
            ss.answers[key] = cur
        with colR:
            result = ss.answers.get(key, {}).get("判定", "")
            if result:
                st.write(result)

    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        if st.button("🔎 採点", type="primary", use_container_width=True):
            # （B）操作時にのみ時間を確定
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
                    "難易度": as_str(r["問題レベル"]),
                    "タイトル": as_str(r["タイトル"]),
                }
            ss.graded = True
            # rerunしない：即座に下で表示
    with c2:
        if st.button("◀ 問題に戻る", use_container_width=True):
            ss.phase = "problem"
            st.rerun()
    with c3:
        if st.button("解説へ ▶", use_container_width=True):
            ss.phase = "explain"
            st.rerun()

    if ss.graded:
        st.success("採点結果")
        res_rows = []
        for _, r in rows.iterrows():
            sub = as_str(r["小問"]); key = (str(i), sub)
            rec = ss.answers.get(key, {})
            res_rows.append({
                "小問": sub,
                "入力": rec.get("入力", ""),
                "正解": rec.get("正解", ""),
                "判定": rec.get("判定", ""),
            })
        st.dataframe(pd.DataFrame(res_rows), hide_index=True, use_container_width=True)

def render_explain(i: int):
    st.subheader(f"解説 {i}")
    header_timer()

    # 解説動画リンク（最初の非空）
    rows = rows_for_id(i)
    video_link = next((as_str(v).strip() for v in rows["解説動画"].tolist() if as_str(v).strip()), "")
    if video_link:
        st.markdown(f"[🎬 解説動画を見る]({video_link})", unsafe_allow_html=True)

    show_cached_image("solution", i)
    pdf_download_button("solution", i)

    st.divider()
    if ss.current_id_idx + 1 < len(available_ids):
        if st.button("次の問題へ ▶", use_container_width=True):
            ss.current_id_idx += 1
            ss.problem_start_time = time.time()  # 次の問題の開始時刻にリセット（B）
            ss.phase = "problem"
            ss.graded = False
            st.rerun()
    else:
        st.success("全ての問題が終了しました。結果画面に移動します。")
        ss.phase = "end"
        st.rerun()

def render_end():
    st.subheader("結果")
    header_timer()
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
            "難易度": rec.get("難易度",""),
            "タイトル": rec.get("タイトル",""),
        })
    df = pd.DataFrame(rows, columns=["ID","小問","入力","正解","判定","経過時間","累計時間","難易度","タイトル"])
    st.dataframe(df, hide_index=True, use_container_width=True)

    if ss.user_name:
        buf = io.StringIO()
        ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        st.download_button("結果CSVをダウンロード", buf.getvalue().encode("utf-8-sig"),
                           file_name=f"{ss.user_name}_結果_{ts}.csv", mime="text/csv")
    st.button("はじめから", on_click=lambda: ss.clear())

# =========================
# ルーター
# =========================
current_id = get_current_id()
if current_id is None:
    st.error("CSVのIDが不正です。"); st.stop()

st.caption(f"進行状況： {ss.current_id_idx+1}/{len(available_ids)}　｜　現在ID：{current_id}")

if ss.phase == "problem":
    render_problem(current_id)
elif ss.phase == "solution":
    render_solution(current_id)
elif ss.phase == "explain":
    render_explain(current_id)
else:
    render_end()
