# AI Dungeon Master - Sang Juru Kisah

Chatbot yang berperan sebagai Dungeon Master untuk permainan bergaya Dungeons & Dragons 5e.
Pemain bermain sendirian, DM-nya AI. Dibuat dengan Gemini, agent LangGraph, dan Streamlit.

Final Project *LLM-Based Tools and Gemini API Integration for Data Scientists* (Hacktiv8).

## Cara kerjanya

Gemini yang bercerita dan memerankan NPC. Angka-angka permainan seperti dadu, HP, AC, gold,
dan XP dihitung oleh fungsi Python lewat tool calling, jadi DM tidak bisa asal mengarang hasil
lemparan. Setiap jawaban DM punya expander "🎲 Mekanik permainan" yang menampilkan hasil tools
apa adanya.

Fiturnya:

- 19 tools untuk dadu, ability check, karakter, inventaris, combat, XP, dan quest
- Data monster, spell, kondisi, dan item diambil dari [D&D 5e SRD API](https://www.dnd5eapi.co)
- Memory percakapan dengan `InMemorySaver` LangGraph
- Character sheet di sidebar yang ikut berubah setiap giliran
- Parameter kreatif di sidebar: setting dunia (termasuk *Nusantara Mistis* yang terinspirasi
  folklor Indonesia), gaya narasi, tingkat kesulitan, bahasa, panjang narasi, model, dan temperature

Pengaturan bisa diganti di tengah permainan. DM akan menyesuaikan gayanya tapi tetap ingat cerita
sebelumnya.

## Menjalankan di Google Colab

Cara utama proyek ini dijalankan, sama seperti di materi kelas.

1. Buka `Sang_Juru_Kisah_AI_Dungeon_Master.ipynb` di Colab.
2. Di Colab Secrets (ikon 🔑), tambahkan `NGROK_TOKEN` dan `GEMINI` (API key dari
   [Google AI Studio](https://aistudio.google.com)). Nyalakan *Notebook access*.
3. Pilih **Runtime > Run all**, lalu buka URL ngrok yang muncul.

Notebook menulis semua file aplikasi (`game_tools.py`, `dm_agent.py`, `app.py`) dengan
`%%writefile`, lalu menjalankan Streamlit dan membuka tunnel ngrok.

## Menjalankan di laptop

```bash
pip install -r requirements.txt
streamlit run app.py
```

Masukkan API key Gemini di sidebar. Kalau tidak mau mengetik ulang setiap kali, salin
`.streamlit/secrets.toml.example` menjadi `.streamlit/secrets.toml` lalu isi key-nya. File itu
sudah masuk `.gitignore`, jadi tidak ikut ter-push.

## Isi repo

| File | Isi |
|---|---|
| `Sang_Juru_Kisah_AI_Dungeon_Master.ipynb` | Notebook lengkap untuk Colab + ngrok |
| `game_tools.py` | `GameState`, mesin dadu, tools, dan klien SRD API |
| `dm_agent.py` | Parameter kreatif, system prompt, dan pembuatan agent |
| `app.py` | Tampilan Streamlit |
| `tests/test_game_tools.py` | Unit test mekanik permainan, jalankan dengan `pytest -q` |

## Lisensi dan atribusi

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by
Wizards of the Coast LLC and available at
https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under
the Creative Commons Attribution 4.0 International License available at
https://creativecommons.org/licenses/by/4.0/legalcode.

Proyek ini tidak berafiliasi dengan Wizards of the Coast.
