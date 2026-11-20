import datetime
import re
import urllib.parse
import requests
import streamlit as st

# ページ設定
st.set_page_config(page_title="数学 理解度テスト（デモ）", layout="centered")

# --- 1. GitHub (pngfiles ブランチ) の画像URL生成 ---
GITHUB_USER = "Daizo-Etsuto"
GITHUB_REPO = "math25-10-19"
GITHUB_BRANCH = "pngfiles"


def get_github_raw_url(filename: str) -> str:
    encoded_name = urllib.parse.quote(filename)
    return f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{encoded_name}"


def build_result_filename(student_name: str, timestamp: str) -> str:
    """氏名_math_YYYYMMDD_HHMMSS.csv 形式でファイル名を生成する"""
    clean_name = re.sub(r'[\\/:*?"<>|]+', "_", student_name.strip())
    clean_name = re.sub(r"\s+", "_", clean_name) or "未入力"
    return f"{clean_name}_math_{timestamp}.csv"


# --- 2. デモ用問題データ（今回は問題1と解説1を使用） ---
QUESTIONS = [
    {
        "title": "2025千葉県関数（ひし形）",
        "q_id": "1",
        "sub_q": "1",
        "level": "基本",
        "image_url": get_github_raw_url("問題1.png"),
        "answer": "14",
        "explanation_url": get_github_raw_url("解答1.png"),
    }
]

# --- 3. セッション状態の初期化 ---
if "q_index" not in st.session_state:
    st.session_state.q_index = 0
if "current_answer" not in st.session_state:
    st.session_state.current_answer = ""
if "results" not in st.session_state:
    st.session_state.results = []
if "is_finished" not in st.session_state:
    st.session_state.is_finished = False
if "show_explanation" not in st.session_state:
    st.session_state.show_explanation = False
if "is_sent" not in st.session_state:
    st.session_state.is_sent = False
if "send_status" not in st.session_state:
    st.session_state.send_status = None
if "session_timestamp" not in st.session_state:
    jst = datetime.timezone(datetime.timedelta(hours=9))
    st.session_state.session_timestamp = datetime.datetime.now(jst).strftime("%Y%m%d_%H%M%S")


def reset_test():
    jst = datetime.timezone(datetime.timedelta(hours=9))
    st.session_state.q_index = 0
    st.session_state.current_answer = ""
    st.session_state.results = []
    st.session_state.is_finished = False
    st.session_state.show_explanation = False
    st.session_state.is_sent = False
    st.session_state.send_status = None
    st.session_state.session_timestamp = datetime.datetime.now(jst).strftime("%Y%m%d_%H%M%S")


def move_to_next_or_finish():
    st.session_state.current_answer = ""
    st.session_state.show_explanation = False
    if st.session_state.q_index + 1 < len(QUESTIONS):
        st.session_state.q_index += 1
    else:
        st.session_state.is_finished = True


# --- 4. 電卓ボタン・解答確定のコールバック ---
def append_char(char: str):
    st.session_state.current_answer += char


def backspace():
    st.session_state.current_answer = st.session_state.current_answer[:-1]


def clear_answer():
    st.session_state.current_answer = ""


def submit_answer():
    q = QUESTIONS[st.session_state.q_index]
    user_ans = st.session_state.current_answer.strip()
    is_correct = user_ans == q["answer"]

    st.session_state.results.append({
        "title": q["title"],
        "q_id": q["q_id"],
        "sub_q": q["sub_q"],
        "user_answer": user_ans,
        "correct_answer": q["answer"],
        "is_correct": is_correct,
    })

    exp_url = (q.get("explanation_url") or "").strip()
    if exp_url:
        st.session_state.current_answer = ""
        st.session_state.show_explanation = True
    else:
        move_to_next_or_finish()


# --- 5. GAS 送信関数 ---
def send_results_to_gas(
    student_name: str,
    results: list[dict],
    score: int,
    total: int,
    timestamp: str,
) -> tuple[bool, str]:
    gas_url = st.secrets.get("GAS_URL", "")
    if not gas_url:
        return False, "Streamlit Secrets に GAS_URL が設定されていません。"

    filename = build_result_filename(student_name, timestamp)
    payload = {
        "timestamp": timestamp,
        "filename": filename,
        "subject": "数学",
        "student_name": student_name.strip(),
        "score": score,
        "total": total,
        "details": results,
    }

    try:
        response = requests.post(gas_url, json=payload, timeout=15)
        response.raise_for_status()
        res_json = response.json()
        if res_json.get("status") == "ok":
            saved_name = res_json.get("filename", filename)
            return True, f"Google ドライブに「{saved_name}」として保存しました。"
        return False, f"GAS側でエラーが発生しました: {res_json.get('message', '不明なエラー')}"
    except Exception as e:
        return False, f"送信エラーが発生しました: {e}"


# --- 6. メイン画面表示 ---
st.title("数学 理解度テスト")

# 【終了画面】結果表示と Google ドライブ送信
if st.session_state.is_finished:
    st.success("テスト終了です！お疲れさまでした。")

    score = sum(1 for r in st.session_state.results if r["is_correct"])
    total = len(st.session_state.results)
    st.subheader(f"得点: {score} / {total}")

    for r in st.session_state.results:
        mark = "⭕" if r["is_correct"] else "❌"
        st.write(
            f"{mark} **{r['title']}（ID:{r['q_id']} 小問{r['sub_q']}）**: "
            f"あなたの解答 `{r['user_answer']}` （正解: `{r['correct_answer']}`）"
        )

    st.divider()
    st.markdown("### 学習結果の記録")
    student_name = st.text_input(
        "生徒名を入力してください",
        key="student_name_input",
        disabled=st.session_state.is_sent,
    )

    preview_filename = build_result_filename(student_name, st.session_state.session_timestamp)
    st.caption(f"保存ファイル名: `{preview_filename}`")

    if st.button(
        "結果を Google ドライブに送信する",
        type="primary",
        disabled=st.session_state.is_sent,
        use_container_width=True,
    ):
        if not student_name.strip():
            st.session_state.send_status = ("error", "生徒名を入力してから送信してください。")
        else:
            ok, msg = send_results_to_gas(
                student_name=student_name,
                results=st.session_state.results,
                score=score,
                total=total,
                timestamp=st.session_state.session_timestamp,
            )
            if ok:
                st.session_state.is_sent = True
                st.session_state.send_status = ("success", msg)
            else:
                st.session_state.send_status = ("error", msg)
        st.rerun()

    if st.session_state.send_status:
        kind, msg = st.session_state.send_status
        if kind == "success":
            st.success(msg)
        else:
            st.error(msg)

    st.divider()
    if st.button("最初からやり直す", on_click=reset_test, use_container_width=True):
        st.rerun()
    st.stop()

current_q = QUESTIONS[st.session_state.q_index]
latest_result = st.session_state.results[-1] if st.session_state.results else None

# 【解説画面】解説URLがある場合のみ表示
if st.session_state.show_explanation:
    st.caption(
        f"解説：{current_q['title']} ｜ 問題 {st.session_state.q_index + 1} / {len(QUESTIONS)}"
    )

    if latest_result:
        if latest_result["is_correct"]:
            st.success(f"⭕ 正解！（解答: `{latest_result['user_answer']}` / 正解: `{latest_result['correct_answer']}`）")
        else:
            st.error(f"❌ 不正解（解答: `{latest_result['user_answer']}` / 正解: `{latest_result['correct_answer']}`）")

    with st.container(border=True):
        st.image(current_q["explanation_url"], use_container_width=True)

    next_label = "結果画面へ進む ➡" if st.session_state.q_index + 1 >= len(QUESTIONS) else "次の問題へ進む ➡"
    st.button(next_label, type="primary", on_click=move_to_next_or_finish, use_container_width=True)
    st.stop()

# 【出題画面】上段：問題画像 / 下段：解答欄と数学電卓
st.caption(
    f"{current_q['title']}（{current_q['level']}）｜ 問題 {st.session_state.q_index + 1} / {len(QUESTIONS)}"
)

with st.container(border=True):
    st.image(current_q["image_url"], use_container_width=True)

st.markdown("### 解答欄")

display_text = st.session_state.current_answer if st.session_state.current_answer else "（下のボタンで入力してください）"
st.markdown(
    f"""
    <div style="
        background-color: #f0f2f6;
        border: 2px solid #4a90e2;
        border-radius: 8px;
        padding: 12px 16px;
        font-size: 24px;
        font-weight: bold;
        text-align: right;
        margin-bottom: 12px;
        font-family: monospace;
    ">
        {display_text}
    </div>
    """,
    unsafe_allow_html=True,
)

keypad_rows = [
    ["7", "8", "9", "√"],
    ["4", "5", "6", "/"],
    ["1", "2", "3", "^2"],
    ["0", "-", "+", "±"],
    ["x", "y", "=", "π"],
]

for row in keypad_rows:
    cols = st.columns(4)
    for idx, label in enumerate(row):
        cols[idx].button(
            label,
            key=f"btn_{label}",
            on_click=append_char,
            args=(label,),
            use_container_width=True,
        )

ctrl_cols = st.columns([1, 1, 2])
ctrl_cols[0].button("⌫ 1文字消す", on_click=backspace, use_container_width=True)
ctrl_cols[1].button("C クリア", on_click=clear_answer, use_container_width=True)
ctrl_cols[2].button(
    "解答を確定する ➡",
    type="primary",
    on_click=submit_answer,
    disabled=(st.session_state.current_answer == ""),
    use_container_width=True,
)
