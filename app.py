"""Kids' Textbook Quiz — a friendly Streamlit app with a parent dashboard.

Practice view: upload a PDF of textbook pages, and Claude generates a mixed quiz
(multiple-choice + short-answer) tuned for ages 9-12, with encouraging graded
feedback and a score summary.

Parent Dashboard view: tracks history across sessions — topics covered, questions
done, % right/wrong, and capability level by question type.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import history
from quiz_engine import explain_concepts, generate_questions, grade_short_answer

# --------------------------------------------------- Advent AI Solutions brand
TEAL = "#1FB8A0"
BLUE = "#2E7CB7"
PURPLE = "#6C5CA6"
LOGO_PATH = Path(__file__).with_name("logo.png")
APP_NAME = "🧮 Lianne's Math Buddy"

st.set_page_config(
    page_title="Lianne's Math Buddy",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else "🧮",
)

BRAND_CSS = f"""
<style>
/* Gradient brand headings (teal → blue → purple, like the logo star) */
h1 {{
    background: linear-gradient(90deg, {TEAL}, {BLUE}, {PURPLE});
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-weight: 800;
}}
h2, h3 {{ color: {PURPLE}; }}

/* Branded buttons */
div.stButton > button {{
    background: linear-gradient(90deg, {TEAL}, {BLUE});
    color: #ffffff;
    border: none;
    border-radius: 10px;
    font-weight: 600;
    padding: 0.5rem 1.3rem;
    transition: filter 0.15s ease;
}}
div.stButton > button:hover {{ filter: brightness(1.08); color: #ffffff; }}
div.stButton > button:disabled {{ background: #d9d9e3; color: #ffffff; }}

/* Progress bar in brand teal */
.stProgress > div > div > div > div {{ background-color: {TEAL}; }}

/* Metric values in brand purple */
[data-testid="stMetricValue"] {{ color: {PURPLE}; }}
</style>
"""
st.markdown(BRAND_CSS, unsafe_allow_html=True)


def render_brand():
    """Show the Advent AI Solutions logo as a header banner."""
    if not LOGO_PATH.exists():
        return
    # Small corner logo for in-app branding...
    try:
        st.logo(str(LOGO_PATH), size="small")
    except TypeError:
        # Older Streamlit without the `size` parameter.
        st.logo(str(LOGO_PATH))
    # ...plus a header banner spanning the full content width.
    try:
        st.image(str(LOGO_PATH), use_container_width=True)
    except TypeError:
        # Older Streamlit used a different keyword.
        st.image(str(LOGO_PATH), use_column_width=True)


# --------------------------------------------------------------- state helpers
def reset_to_upload():
    """Clear quiz state and go back to the upload screen."""
    for key in (
        "stage",
        "questions",
        "current",
        "score",
        "answered",
        "feedback",
        "results",
        "concepts",
        "pdf_bytes",
        "num_questions",
    ):
        st.session_state.pop(key, None)


def restart_same_questions():
    """Replay the same quiz from the beginning."""
    st.session_state.current = 0
    st.session_state.score = 0
    st.session_state.answered = False
    st.session_state.feedback = None
    st.session_state.results = []
    st.session_state.stage = "quiz"


# ============================================================== Practice view
def render_practice():
    if "stage" not in st.session_state:
        st.session_state.stage = "upload"
    stage = st.session_state.stage

    def begin_quiz():
        """Generate questions from the stored PDF and enter the quiz."""
        with st.spinner("Making fun questions for you..."):
            questions = generate_questions(
                st.session_state.pdf_bytes, st.session_state.num_questions
            )
        if not questions:
            st.error("Hmm, I couldn't make questions from that file. Try another page!")
            return
        st.session_state.questions = questions
        st.session_state.current = 0
        st.session_state.score = 0
        st.session_state.answered = False
        st.session_state.feedback = None
        st.session_state.results = []
        st.session_state.stage = "quiz"
        st.rerun()

    # ------------------------------------------------------------ Upload stage
    if stage == "upload":
        st.title(APP_NAME)
        st.write(
            "Upload a page or two from your math textbook, and I'll explain the key "
            "ideas and make some practice questions just for you. Ready? Let's go! 🚀"
        )

        pdf_file = st.file_uploader("Upload your textbook page (PDF)", type=["pdf"])
        num_questions = st.slider("How many questions?", 3, 15, 8)
        skip_revision = st.checkbox("Skip the revision and go straight to the quiz")

        if st.button("Let's go! ✨", disabled=pdf_file is None):
            st.session_state.pdf_bytes = pdf_file.getvalue()
            st.session_state.num_questions = num_questions
            if skip_revision:
                begin_quiz()
            else:
                with st.spinner("Reading your pages and getting the key ideas ready..."):
                    st.session_state.concepts = explain_concepts(
                        st.session_state.pdf_bytes
                    )
                st.session_state.stage = "revision"
                st.rerun()

    # ---------------------------------------------------------- Revision stage
    elif stage == "revision":
        st.title("📖 Let's review the key ideas")
        st.write("Read these first, then jump into the quiz when you're ready!")

        concepts = st.session_state.get("concepts", [])
        if not concepts:
            st.info("No key concepts found — let's go straight to the quiz!")
        for c in concepts:
            st.subheader(c["title"])
            st.write(c["explanation"])

        st.divider()
        if st.button("I'm ready — start the quiz! 🎯"):
            begin_quiz()

    # -------------------------------------------------------------- Quiz stage
    elif stage == "quiz":
        questions = st.session_state.questions
        idx = st.session_state.current
        total = len(questions)
        q = questions[idx]

        st.progress(idx / total)
        st.caption(f"Question {idx + 1} of {total}  •  Score: {st.session_state.score}")
        st.caption(f"Topic: {q.get('topic', 'General')}")
        st.subheader(q["question"])

        def record_result(is_correct: bool):
            """Update score + per-question log exactly once when answered."""
            if is_correct:
                st.session_state.score += 1
            st.session_state.results.append(
                {
                    "topic": q.get("topic", "General"),
                    "type": q["type"],
                    "correct": is_correct,
                }
            )
            st.session_state.answered = True

        # --- Multiple choice ---------------------------------------------
        if q["type"] == "multiple_choice":
            choice = st.radio(
                "Pick your answer:",
                q["options"],
                index=None,
                key=f"choice_{idx}",
                disabled=st.session_state.answered,
            )
            if not st.session_state.answered and st.button(
                "Check answer", disabled=choice is None
            ):
                is_correct = choice == q["correct_answer"]
                record_result(is_correct)
                st.session_state.feedback = {
                    "is_correct": is_correct,
                    "text": q["explanation"],
                }
                st.rerun()

        # --- Short answer ------------------------------------------------
        else:
            answer = st.text_input(
                "Type your answer:",
                key=f"answer_{idx}",
                disabled=st.session_state.answered,
            )
            if not st.session_state.answered and st.button(
                "Check answer", disabled=not answer.strip()
            ):
                with st.spinner("Checking your answer..."):
                    result = grade_short_answer(
                        q["question"], q["correct_answer"], answer
                    )
                record_result(result["is_correct"])
                st.session_state.feedback = {
                    "is_correct": result["is_correct"],
                    "text": result["feedback"],
                }
                st.rerun()

        # --- Feedback + advance ------------------------------------------
        if st.session_state.answered and st.session_state.feedback:
            fb = st.session_state.feedback
            if fb["is_correct"]:
                st.success(f"✅ Correct! {fb['text']}")
            else:
                st.error(f"❌ Not quite. {fb['text']}")
                if q["type"] == "short_answer":
                    st.info(f"A good answer would be: {q['correct_answer']}")

            last = idx == total - 1
            if st.button("See my results 🎉" if last else "Next question →"):
                if last:
                    # Save this completed quiz to the parent dashboard history.
                    history.record_attempt(
                        st.session_state.score, total, st.session_state.results
                    )
                    st.session_state.stage = "done"
                else:
                    st.session_state.current += 1
                    st.session_state.answered = False
                    st.session_state.feedback = None
                st.rerun()

    # -------------------------------------------------------------- Done stage
    elif stage == "done":
        score = st.session_state.score
        total = len(st.session_state.questions)
        pct = score / total if total else 0

        st.title("🎉 All done!")
        st.header(f"You scored {score} out of {total}!")

        if pct == 1:
            st.success("Perfect score! You're a superstar! 🌟🌟🌟")
            st.balloons()
        elif pct >= 0.7:
            st.success("Great job! You really know your stuff! 🌟🌟")
        elif pct >= 0.4:
            st.info("Nice effort! A little more practice and you'll ace it! 🌟")
        else:
            st.info("Good try! Learning takes practice — let's go again! 💪")

        col1, col2 = st.columns(2)
        with col1:
            st.button("Practice these again 🔁", on_click=restart_same_questions)
        with col2:
            st.button("Upload a new page 📄", on_click=reset_to_upload)


# ============================================================== Dashboard view
def render_dashboard():
    st.title("📊 Parent Dashboard")
    attempts = history.load_attempts()

    if not attempts:
        st.info(
            "No practice sessions yet. Head to **🎮 Practice** to complete a quiz, "
            "and progress will show up here."
        )
        return

    summary = history.summarize(attempts)

    # --- Headline metrics -------------------------------------------------
    c1, c2, c3 = st.columns(3)
    c1.metric("Quizzes completed", summary["quizzes"])
    c2.metric("Questions answered", summary["questions"])
    c3.metric("Overall accuracy", f"{summary['overall_pct'] * 100:.0f}%")
    st.caption(f"✅ {summary['correct']} right  •  ❌ {summary['wrong']} wrong")

    # --- Topics covered ---------------------------------------------------
    st.subheader("Topics covered")
    topic_df = pd.DataFrame(
        [
            {
                "Topic": t["name"],
                "Questions": t["done"],
                "% Correct": round(t["pct"] * 100),
                "Capability": t["level"],
            }
            for t in summary["topics"]
        ]
    )
    st.dataframe(topic_df, hide_index=True, use_container_width=True)

    # --- Capability by question type -------------------------------------
    st.subheader("Capability by question type")
    type_df = pd.DataFrame(
        [
            {
                "Question type": t["name"],
                "Questions": t["done"],
                "% Correct": round(t["pct"] * 100),
                "Capability": t["level"],
            }
            for t in summary["types"]
        ]
    )
    st.dataframe(type_df, hide_index=True, use_container_width=True)

    # --- Accuracy trend over time ----------------------------------------
    st.subheader("Accuracy over time")
    trend = pd.DataFrame(
        [
            {
                "Quiz": f"#{i + 1}",
                "% Correct": round(a["score"] / a["total"] * 100) if a["total"] else 0,
            }
            for i, a in enumerate(attempts)
        ]
    ).set_index("Quiz")
    st.line_chart(trend, y="% Correct")

    # --- Recent activity --------------------------------------------------
    st.subheader("Recent activity")
    recent = []
    for a in reversed(attempts):
        topics = sorted({r.get("topic", "General") for r in a.get("results", [])})
        recent.append(
            {
                "When": a["timestamp"].replace("T", "  "),
                "Topics": ", ".join(topics) if topics else "—",
                "Score": f"{a['score']}/{a['total']}",
                "% Correct": round(a["score"] / a["total"] * 100) if a["total"] else 0,
            }
        )
    st.dataframe(pd.DataFrame(recent), hide_index=True, use_container_width=True)

    # --- Manage -----------------------------------------------------------
    with st.expander("Manage history"):
        st.warning("Clearing history permanently deletes all tracked progress.")
        if st.checkbox("Yes, I want to clear all history"):
            if st.button("Clear history now"):
                history.clear_history()
                st.success("History cleared.")
                st.rerun()


# ===================================================================== Router
render_brand()
view = st.sidebar.radio("Menu", ["🎮 Practice", "📊 Parent Dashboard"])
if view == "🎮 Practice":
    render_practice()
else:
    render_dashboard()
