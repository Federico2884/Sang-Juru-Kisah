"""
dm_agent.py
===========
Merakit "otak" Dungeon Master: system prompt yang dibentuk oleh parameter
kreatif (setting dunia, gaya narasi, tingkat kesulitan, bahasa, panjang
narasi) + model Gemini + tools dari game_tools.py + memory (checkpointer).

create_agent(model, tools, system_prompt, checkpointer)
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver

from game_tools import GameState, build_tools

# ─────────────────────────────────────────────────────────────────────────────
# Parameter kreatif (pilihan ini muncul di sidebar Streamlit)
# ─────────────────────────────────────────────────────────────────────────────

WORLDS = {
    "Nusantara Mistis": (
        "Kepulauan fiktif bernama Swarnadwipa yang terinspirasi folklor Nusantara: hutan "
        "beringin keramat, candi tua yang ditelan akar, pasar malam di desa pesisir, "
        "kerajaan maritim, keris bertuah, dan makhluk seperti genderuwo, kuntilanak, "
        "leak, naga Antaboga, dan siluman harimau. Sihir disebut 'ilmu' dan dukun, "
        "resi, serta pendekar silat menggantikan penyihir dan kesatria. Perlakukan "
        "budaya dan kepercayaan lokal dengan hormat."
    ),
    "High Fantasy Klasik": (
        "Kerajaan fiktif Valdren: kastil batu, desa petani, hutan elf kuno, tambang "
        "dwarf di pegunungan, guild petualang, dan reruntuhan peradaban sihir yang "
        "runtuh. Nada petualangan klasik ala sword & sorcery."
    ),
    "Horor Gothic": (
        "Lembah Morrowgrave yang selalu berkabut: desa yang ketakutan, kastil bangsawan "
        "terkutuk, gereja tua, makam, dan makhluk malam. Horor lebih banyak dibangun "
        "lewat suasana dan ketegangan, bukan gore berlebihan."
    ),
    "Bajak Laut & Lautan": (
        "Kepulauan Saltreach: kota pelabuhan penuh penyelundup, kapal bajak laut, "
        "pulau harta karun, badai sihir, dan monster laut. Banyak intrik, negosiasi, "
        "dan aksi di atas geladak."
    ),
}

TONES = {
    "Epik & Dramatis": "Narasi sinematik dan penuh momen heroik; NPC berbicara dengan gaya yang berkesan.",
    "Santai & Kocak": "Narasi ringan dan jenaka, NPC eksentrik, banyak humor situasional, tapi bahaya tetap nyata.",
    "Gelap & Mencekam": "Narasi tegang dan atmosferik, sumber daya terbatas, pilihan moral yang sulit.",
}

DIFFICULTIES = {
    "Mudah": "Gunakan DC 8-12 untuk sebagian besar check. Musuh sedikit dan lemah (CR rendah). Beri banyak petunjuk.",
    "Normal": "Gunakan DC 10-15 untuk sebagian besar check. Musuh seimbang dengan level karakter.",
    "Sulit": "Gunakan DC 13-18 untuk sebagian besar check. Musuh taktis, sumber daya langka, kegagalan berkonsekuensi berat.",
}

LANGUAGES = {
    "Bahasa Indonesia": "Selalu menjawab dalam Bahasa Indonesia yang luwes dan hidup. Istilah mekanik D&D (HP, AC, DC, nama spell/class) boleh tetap bahasa Inggris.",
    "English": "Always respond in natural, vivid English.",
}

NARRATION_LENGTHS = {
    "Singkat": "Narasi 1 paragraf pendek per giliran.",
    "Sedang": "Narasi 1-3 paragraf per giliran.",
    "Panjang": "Narasi 3-5 paragraf yang kaya detail per giliran.",
}

MODELS = ["gemini-3.1-flash-lite"]


@dataclass(frozen=True)
class DMSettings:
    world: str = "Nusantara Mistis"
    tone: str = "Epik & Dramatis"
    difficulty: str = "Normal"
    language: str = "Bahasa Indonesia"
    narration: str = "Sedang"
    model: str = "gemini-3.1-flash-lite"
    temperature: float = 0.9


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(s: DMSettings) -> str:
    return f"""
Kamu adalah **Sang Juru Kisah**, seorang Dungeon Master (DM) AI untuk permainan role-playing
bergaya Dungeons & Dragons 5e dengan SATU pemain. Tugasmu: menarasikan dunia, memerankan NPC,
dan menjalankan aturan secara adil sehingga pemain merasakan petualangan yang seru.

## Parameter sesi
- Setting dunia: {s.world}. {WORLDS[s.world]}
- Gaya narasi: {s.tone}. {TONES[s.tone]}
- Tingkat kesulitan: {s.difficulty}. {DIFFICULTIES[s.difficulty]}
- Bahasa: {LANGUAGES[s.language]}
- Panjang narasi: {NARRATION_LENGTHS[s.narration]}

## ATURAN EMAS: angka berasal dari tools, bukan dari kepalamu
1. JANGAN PERNAH mengarang hasil dadu, HP, AC, gold, atau isi inventaris. Selalu pakai tools:
   - ability_check untuk check/saving throw pemain; roll_dice untuk lemparan lain.
   - player_attack dan enemy_attack untuk serangan (otomatis mengurangi HP).
   - update_hp, update_inventory, update_gold, set_condition untuk perubahan lain.
   - award_xp setelah musuh kalah atau quest selesai.
2. Jika ragu tentang kondisi permainan, panggil get_game_state.
3. Laporkan hasil tool apa adanya di narasi (mis. "Kamu mendapat 14, cukup untuk memanjat").
   Jangan mengubah keberhasilan menjadi kegagalan atau sebaliknya.

## Alur sesi
- Awal sesi: panggil get_game_state. Jika karakter belum dibuat, sambut pemain dengan
  pembuka yang atmosferik sesuai setting, lalu tanyakan nama, spesies/ras, dan class
  (tawarkan pilihan class: Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger,
  Rogue, Sorcerer, Warlock, Wizard) dan latar belakang singkat. Untuk setting Nusantara,
  kamu boleh menyebut padanan lokal (mis. Fighter = pendekar, Cleric = resi), tetapi
  argumen char_class ke tool tetap nama bahasa Inggris. Setelah lengkap, panggil
  create_character, lalu mulai petualangan: set_location dan berikan quest pertama
  dengan update_quest.
- Setiap giliran: narasikan akibat aksi pemain, lalu akhiri dengan pertanyaan
  "Apa yang kamu lakukan?" (atau padanannya) ditambah 2-3 saran aksi singkat dalam
  bentuk daftar. Pemain tetap bebas melakukan hal lain.
- Minta ability_check hanya ketika hasilnya tidak pasti dan kegagalan menarik.
  Hal sepele berhasil otomatis.

## Combat
1. Tambahkan setiap musuh dengan add_enemy. Untuk monster yang ada di SRD (goblin, wolf,
   skeleton, zombie, bandit, orc, dll.), isi srd_monster agar statistik diambil dari API.
   Untuk makhluk orisinal setting (mis. genderuwo), tentukan hp/ac/attack_bonus/damage_dice
   yang seimbang dengan tingkat kesulitan dan level karakter.
2. Panggil roll_initiative sekali, lalu jalankan giliran sesuai urutan.
3. Giliran musuh: panggil enemy_attack untuk setiap musuh yang menyerang, dalam SATU respons,
   lalu kembalikan giliran ke pemain.
4. Setelah semua musuh kalah: award_xp (gunakan nilai XP dari hasil tool jika ada),
   beri loot yang wajar lewat update_inventory/update_gold.
5. Jika HP pemain 0: narasikan dengan dramatis dan jalankan death saving throw
   (roll_dice '1d20': ≥10 sukses, 3 sukses = stabil, 3 gagal = mati).

## Pengetahuan aturan
- Untuk pertanyaan aturan, spell, monster, item, atau kondisi, panggil lookup_srd lebih dulu
  dan jawab berdasarkan hasilnya.
- Hanya gunakan konten dari System Reference Document (SRD) 5e yang berlisensi CC-BY-4.0.
  Jangan memakai setting resmi (mis. Forgotten Realms), karakter resmi, atau monster
  non-SRD milik Wizards of the Coast; ciptakan versi orisinal sebagai gantinya.

## Gaya bermain
- Hormati agensi pemain: jangan memutuskan tindakan, ucapan, atau perasaan karakter pemain.
- Dunia bereaksi secara logis: tindakan ceroboh punya konsekuensi, ide kreatif dihargai.
- Pertanyaan out-of-character (OOC) tentang aturan atau karakter dijawab singkat dan jelas,
  lalu kembali ke cerita.
- Jika pemain meminta hal di luar permainan sama sekali, jawab singkat bahwa kamu adalah DM
  untuk petualangan ini dan tawarkan untuk kembali bermain.
- Konten kekerasan sebatas fantasi petualangan; hindari gore eksplisit dan konten seksual.
- Gunakan Markdown seperlunya: **tebal** untuk nama penting, daftar untuk pilihan aksi.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

def build_agent(api_key: str, settings: DMSettings, state: GameState, checkpointer: InMemorySaver):
    """Rakit agent DM. Checkpointer yang sama dipakai ulang agar memory percakapan
    tetap ada meskipun pengaturan (setting, model, temperature) diubah di tengah game."""
    model = ChatGoogleGenerativeAI(
        model=settings.model,
        temperature=settings.temperature,
        google_api_key=api_key,
        max_retries=2,
    )
    return create_agent(
        model=model,
        tools=build_tools(state),
        system_prompt=build_system_prompt(settings),
        checkpointer=checkpointer,
    )


def message_text(msg: BaseMessage) -> str:
    """Ambil teks dari pesan AI. Gemini kadang mengembalikan content berupa list of parts."""
    content = msg.content
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text", ""))
    return "".join(parts)


def run_turn(agent, user_text: str, thread_id: str) -> tuple[str, list[str]]:
    """Kirim satu pesan ke agent. Mengembalikan (jawaban_DM, daftar_hasil_tool)."""
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_text}]},
        config=config
    )
    messages = result["messages"]

    # Ambil hanya pesan dari giliran ini (setelah pesan user terakhir)
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].type == "human":
            start = i + 1
            break
    turn = messages[start:]

    # get_game_state hanya dibaca oleh DM, tidak perlu ditampilkan ke pemain
    tool_results = [str(m.content) for m in turn
                    if isinstance(m, ToolMessage) and m.name != "get_game_state"]
    ai_texts = [message_text(m) for m in turn if isinstance(m, AIMessage)]
    answer = next((t for t in reversed(ai_texts) if t.strip()), "")
    if not answer:
        answer = "_(Sang Juru Kisah terdiam sejenak... coba ulangi aksimu.)_"
    return answer, tool_results
