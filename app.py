"""
app.py: Sang Juru Kisah, AI Dungeon Master
==========================================
UI Streamlit untuk chatbot D&D berbasis Gemini + LangGraph agent.

Jalankan:
    streamlit run app.py
"""

import os
import uuid

import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver

from dm_agent import (DIFFICULTIES, LANGUAGES, MODELS, NARRATION_LENGTHS, TONES,
                      WORLDS, DMSettings, build_agent, run_turn)
from game_tools import ABILITIES, XP_THRESHOLDS, GameState, fmt_mod

# ── 1. Konfigurasi halaman ───────────────────────────────────────────────────
st.set_page_config(page_title="Sang Juru Kisah | AI Dungeon Master",
                   page_icon="🐉", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&display=swap');
    h1, h2, h3 { font-family: 'Cinzel', serif !important; letter-spacing: .02em; }
    [data-testid="stChatMessage"] { border-radius: 12px; }
    .ability-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin:4px 0 8px; }
    .ability { border:1px solid rgba(201,162,39,.45); border-radius:8px; padding:4px 0; text-align:center; }
    .ability b { display:block; font-size:.72rem; opacity:.75; }
    .ability span { font-size:1.05rem; font-weight:700; }
    .ability small { display:block; font-size:.72rem; opacity:.8; }
    </style>
    """,
    unsafe_allow_html=True,
)

DM_AVATAR, PLAYER_AVATAR = "🧙", "🗡️"
KICKOFF = ("[SISTEM] Sesi baru dimulai dan pemain belum menulis apa pun. Buka petualangan "
           "sesuai parameter sesi, lalu mulai pembuatan karakter.")


# ── 2. Session state ─────────────────────────────────────────────────────────
# Streamlit menjalankan ulang skrip setiap interaksi, jadi semua yang harus
# bertahan (state game, memory agent, riwayat chat) disimpan di session_state.
def new_game() -> None:
    st.session_state.game = GameState()                 # state mekanik (HP, item, dll.)
    st.session_state.checkpointer = InMemorySaver()     # memory percakapan LangGraph
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.messages = []                      # riwayat untuk ditampilkan
    st.session_state.agent = None
    st.session_state.agent_key = None
    st.session_state.started = False


if "game" not in st.session_state:
    new_game()


def default_api_key() -> str:
    """Ambil key dari env var atau .streamlit/secrets.toml jika ada (opsional)."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    try:
        return st.secrets.get("GOOGLE_API_KEY", "")
    except Exception:
        return ""


# ── 3. Sidebar: pengaturan & parameter kreatif ──────────────────────────────
with st.sidebar:
    st.header("⚙️ Pengaturan")
    api_key = st.text_input("Google AI API Key", type="password", value=default_api_key(),
                            help="Dapatkan gratis di https://aistudio.google.com")

    with st.expander("🎭 Parameter Kreatif", expanded=True):
        world = st.selectbox("Setting dunia", list(WORLDS))
        tone = st.selectbox("Gaya narasi", list(TONES))
        difficulty = st.select_slider("Tingkat kesulitan", list(DIFFICULTIES), value="Normal")
        language = st.radio("Bahasa", list(LANGUAGES), horizontal=True)
        narration = st.select_slider("Panjang narasi", list(NARRATION_LENGTHS), value="Sedang")

    with st.expander("🤖 Model AI"):
        model_name = st.selectbox("Model Gemini", MODELS)
        temperature = st.slider("Temperature (kreativitas)", 0.0, 1.5, 0.9, 0.05,
                                help="Rendah = konsisten & patuh aturan, tinggi = lebih imajinatif.")

    if st.button("🔄 Petualangan Baru", width="stretch",
                 help="Hapus karakter, memory, dan riwayat chat."):
        new_game()
        st.rerun()

    st.divider()
    sheet_box = st.container()   # character sheet diisi di akhir skrip (setelah DM menjawab)


# ── 4. Komponen tampilan ─────────────────────────────────────────────────────
def render_sheet(game: GameState) -> None:
    """Character sheet, musuh, quest, dan log dadu di sidebar."""
    with sheet_box:
        c = game.character
        if c is None:
            st.subheader("📜 Character Sheet")
            st.caption("Belum ada karakter. Ceritakan pada Sang Juru Kisah siapa dirimu!")
            return

        st.subheader(f"🛡️ {c.name}")
        st.caption(f"{c.species} {c.char_class} · Level {c.level}"
                   + (f" · {c.background}" if c.background else ""))
        st.progress(c.hp / c.max_hp if c.max_hp else 0, text=f"❤️ HP {c.hp}/{c.max_hp}")
        next_xp = XP_THRESHOLDS[c.level] if c.level < 20 else c.xp
        prev_xp = XP_THRESHOLDS[c.level - 1]
        xp_ratio = 1.0 if c.level >= 20 else (c.xp - prev_xp) / (next_xp - prev_xp)
        st.progress(min(1.0, max(0.0, xp_ratio)), text=f"⭐ XP {c.xp}/{next_xp}")

        col1, col2, col3 = st.columns(3)
        col1.metric("AC", c.ac)
        col2.metric("Gold", f"{c.gold}")
        col3.metric("Prof", fmt_mod(c.prof_bonus))

        cells = "".join(
            f"<div class='ability'><b>{a}</b><span>{c.abilities[a]}</span>"
            f"<small>{fmt_mod(c.mod(a))}</small></div>" for a in ABILITIES)
        st.markdown(f"<div class='ability-grid'>{cells}</div>", unsafe_allow_html=True)

        st.markdown(f"**Senjata:** {c.weapon[0]} ({c.weapon[1]})  \n"
                    f"**Armor:** {c.armor_name}  \n"
                    f"**Kondisi:** {', '.join(c.conditions) or 'normal'}  \n"
                    f"**Lokasi:** {game.location}")

        with st.expander(f"🎒 Inventaris ({sum(c.inventory.values())})"):
            for item, qty in c.inventory.items():
                st.markdown(f"- {item} × {qty}")

        if game.quests:
            with st.expander("📜 Quest Log", expanded=True):
                icons = {"aktif": "🟡", "selesai": "✅", "gagal": "❌"}
                for title, q in game.quests.items():
                    st.markdown(f"{icons.get(q['status'], '•')} **{title}**  \n"
                                f"<small>{q['note']}</small>", unsafe_allow_html=True)

        if game.enemies:
            st.markdown("#### ⚔️ Combat")
            for e in game.enemies.values():
                st.progress(e.hp / e.max_hp if e.max_hp else 0,
                            text=f"👹 {e.name} · HP {e.hp}/{e.max_hp} · AC {e.ac}")
            if game.initiative_order:
                st.caption("Giliran: " + " → ".join(n for n, _ in game.initiative_order))

    if game.roll_log:
        with sheet_box.expander("🎲 Log Dadu & Mekanik"):
            for line in reversed(game.roll_log[-12:]):
                st.markdown(line)


def render_message(msg: dict) -> None:
    avatar = DM_AVATAR if msg["role"] == "assistant" else PLAYER_AVATAR
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        if msg.get("mechanics"):
            with st.expander(f"🎲 Mekanik permainan ({len(msg['mechanics'])})"):
                for line in msg["mechanics"]:
                    st.markdown(line)


def ask_dm(text: str) -> None:
    """Kirim teks ke agent DM, tampilkan jawabannya, lalu simpan ke riwayat."""
    with st.chat_message("assistant", avatar=DM_AVATAR):
        with st.spinner("Sang Juru Kisah sedang merangkai kisah..."):
            try:
                answer, mechanics = run_turn(st.session_state.agent, text,
                                             st.session_state.thread_id)
            except Exception as e:  # rate limit, key salah, koneksi, dll.
                answer, mechanics = f"⚠️ Terjadi error saat menghubungi Gemini:\n\n`{e}`", []
        st.markdown(answer)
        if mechanics:
            with st.expander(f"🎲 Mekanik permainan ({len(mechanics)})"):
                for line in mechanics:
                    st.markdown(line)
    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "mechanics": mechanics})


# ── 5. Header ────────────────────────────────────────────────────────────────
st.title("🐉 Sang Juru Kisah")
st.caption(f"AI Dungeon Master · {world} · {tone} · {difficulty} · {model_name} "
           f"(temp {temperature})")

if not api_key:
    st.info("Masukkan Google AI API Key di sidebar untuk memulai petualangan.", icon="🗝️")
    render_sheet(st.session_state.game)
    st.stop()

# ── 6. Agent: dibangun ulang hanya jika key/pengaturan berubah ───────────────
settings = DMSettings(world=world, tone=tone, difficulty=difficulty, language=language,
                      narration=narration, model=model_name, temperature=temperature)
agent_key = (api_key, settings)
if st.session_state.agent_key != agent_key:
    try:
        st.session_state.agent = build_agent(api_key, settings, st.session_state.game,
                                             st.session_state.checkpointer)
    except Exception as e:
        st.error(f"Gagal menyiapkan model: {e}")
        st.stop()
    if st.session_state.agent_key is not None:
        st.toast("Pengaturan DM diperbarui. Memory petualangan tetap tersimpan.", icon="✨")
    st.session_state.agent_key = agent_key

# ── 7. Riwayat & pembuka otomatis ────────────────────────────────────────────
# Semua bubble chat ditaruh di container ini supaya tombol aksi cepat selalu
# berada di bawah percakapan.
chat_area = st.container()
with chat_area:
    for msg in st.session_state.messages:
        render_message(msg)

    if not st.session_state.started:
        st.session_state.started = True
        ask_dm(KICKOFF)

# ── 8. Aksi cepat & input pemain ─────────────────────────────────────────────
QUICK_ACTIONS = {
    "🔍 Amati sekitar": "Aku mengamati sekelilingku dengan saksama.",
    "📋 Status karakter": "(OOC) Tolong ringkas kondisi karakterku dan quest yang sedang aktif.",
    "🏕️ Istirahat sejenak": "Aku mencari tempat aman untuk short rest.",
    "❓ Tanya aturan": "(OOC) Jelaskan secara singkat aksi apa saja yang bisa kulakukan sekarang.",
}
quick_prompt = None
cols = st.columns(len(QUICK_ACTIONS))
for col, (label, text) in zip(cols, QUICK_ACTIONS.items()):
    if col.button(label, width="stretch"):
        quick_prompt = text

prompt = st.chat_input("Apa yang kamu lakukan?") or quick_prompt
if prompt:
    user_msg = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_msg)
    with chat_area:
        render_message(user_msg)
        ask_dm(prompt)

# ── 9. Character sheet (di akhir agar mencerminkan hasil giliran ini) ───────
render_sheet(st.session_state.game)
