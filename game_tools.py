"""
game_tools.py
=============
Semua MEKANIK permainan ada di sini: lempar dadu, karakter, HP, inventaris,
quest, combat, XP, dan pencarian aturan dari D&D 5e SRD API.

Prinsip utamanya: LLM hanya bercerita, angka dihitung oleh KODE.
LLM (Gemini) tidak boleh mengarang hasil dadu atau HP; ia wajib memanggil
tools di file ini.

Setiap sesi Streamlit punya satu objek `GameState`. Tools dibuat sebagai
closure yang "mengikat" objek tersebut lewat `build_tools(state)`, sehingga
dua pemain di dua tab browser tidak saling mengganggu.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

import requests
from langchain_core.tools import tool

# ─────────────────────────────────────────────────────────────────────────────
# 1. Data aturan (diambil dari SRD 5.1, lisensi CC-BY-4.0)
# ─────────────────────────────────────────────────────────────────────────────

ABILITIES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]

# Ambang XP untuk naik level (SRD 5.1)
XP_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
                 85000, 100000, 120000, 140000, 165000, 195000, 225000,
                 265000, 305000, 355000]

ClassName = Literal["Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk",
                    "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard"]

# armor: (nama, jenis, nilai dasar)
#   jenis "heavy" -> AC = dasar
#   jenis "medium" -> AC = dasar + min(DEX, 2)
#   jenis "light" -> AC = dasar + DEX
#   jenis "none" -> AC = 10 + DEX
#   jenis "barbarian"/"monk" -> unarmored defense
CLASS_DATA: dict[str, dict] = {
    "Barbarian": dict(hit_die=12, priority=["STR", "CON", "DEX", "WIS", "CHA", "INT"],
                      armor=("Tanpa armor", "barbarian", 10), shield=False, spell=None,
                      weapon=("Greataxe", "1d12", "STR"),
                      items={"Greataxe": 1, "Handaxe": 2, "Javelin": 4, "Explorer's Pack": 1}),
    "Bard": dict(hit_die=8, priority=["CHA", "DEX", "CON", "WIS", "INT", "STR"],
                 armor=("Leather Armor", "light", 11), shield=False, spell="CHA",
                 weapon=("Rapier", "1d8", "DEX"),
                 items={"Rapier": 1, "Dagger": 1, "Lute": 1, "Leather Armor": 1, "Entertainer's Pack": 1}),
    "Cleric": dict(hit_die=8, priority=["WIS", "CON", "STR", "DEX", "CHA", "INT"],
                   armor=("Scale Mail", "medium", 14), shield=True, spell="WIS",
                   weapon=("Mace", "1d6", "STR"),
                   items={"Mace": 1, "Scale Mail": 1, "Shield": 1, "Holy Symbol": 1, "Priest's Pack": 1}),
    "Druid": dict(hit_die=8, priority=["WIS", "CON", "DEX", "INT", "CHA", "STR"],
                  armor=("Leather Armor", "light", 11), shield=True, spell="WIS",
                  weapon=("Scimitar", "1d6", "DEX"),
                  items={"Scimitar": 1, "Wooden Shield": 1, "Leather Armor": 1, "Druidic Focus": 1, "Explorer's Pack": 1}),
    "Fighter": dict(hit_die=10, priority=["STR", "CON", "DEX", "WIS", "CHA", "INT"],
                    armor=("Chain Mail", "heavy", 16), shield=True, spell=None,
                    weapon=("Longsword", "1d8", "STR"),
                    items={"Longsword": 1, "Shield": 1, "Chain Mail": 1, "Light Crossbow": 1, "Dungeoneer's Pack": 1}),
    "Monk": dict(hit_die=8, priority=["DEX", "WIS", "CON", "STR", "INT", "CHA"],
                 armor=("Tanpa armor", "monk", 10), shield=False, spell=None,
                 weapon=("Shortsword", "1d6", "DEX"),
                 items={"Shortsword": 1, "Dart": 10, "Explorer's Pack": 1}),
    "Paladin": dict(hit_die=10, priority=["STR", "CHA", "CON", "WIS", "DEX", "INT"],
                    armor=("Chain Mail", "heavy", 16), shield=True, spell="CHA",
                    weapon=("Longsword", "1d8", "STR"),
                    items={"Longsword": 1, "Shield": 1, "Chain Mail": 1, "Holy Symbol": 1, "Priest's Pack": 1}),
    "Ranger": dict(hit_die=10, priority=["DEX", "WIS", "CON", "STR", "INT", "CHA"],
                   armor=("Scale Mail", "medium", 14), shield=False, spell="WIS",
                   weapon=("Longbow", "1d8", "DEX"),
                   items={"Longbow": 1, "Arrow": 20, "Shortsword": 2, "Scale Mail": 1, "Explorer's Pack": 1}),
    "Rogue": dict(hit_die=8, priority=["DEX", "CON", "INT", "WIS", "CHA", "STR"],
                  armor=("Leather Armor", "light", 11), shield=False, spell=None,
                  weapon=("Shortsword", "1d6", "DEX"),
                  items={"Shortsword": 1, "Shortbow": 1, "Arrow": 20, "Dagger": 2, "Thieves' Tools": 1, "Leather Armor": 1}),
    "Sorcerer": dict(hit_die=6, priority=["CHA", "CON", "DEX", "WIS", "INT", "STR"],
                     armor=("Tanpa armor", "none", 10), shield=False, spell="CHA",
                     weapon=("Dagger", "1d4", "DEX"),
                     items={"Dagger": 2, "Arcane Focus": 1, "Light Crossbow": 1, "Dungeoneer's Pack": 1}),
    "Warlock": dict(hit_die=8, priority=["CHA", "CON", "DEX", "WIS", "INT", "STR"],
                    armor=("Leather Armor", "light", 11), shield=False, spell="CHA",
                    weapon=("Dagger", "1d4", "DEX"),
                    items={"Dagger": 2, "Arcane Focus": 1, "Leather Armor": 1, "Scholar's Pack": 1}),
    "Wizard": dict(hit_die=6, priority=["INT", "CON", "DEX", "WIS", "CHA", "STR"],
                   armor=("Tanpa armor", "none", 10), shield=False, spell="INT",
                   weapon=("Quarterstaff", "1d6", "STR"),
                   items={"Quarterstaff": 1, "Spellbook": 1, "Arcane Focus": 1, "Scholar's Pack": 1}),
}

SRD_API_BASES = ["https://www.dnd5eapi.co/api/2014", "https://www.dnd5eapi.co/api"]


def ability_mod(score: int) -> int:
    """Modifier ability score D&D: (skor - 10) // 2."""
    return (score - 10) // 2


def fmt_mod(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Mesin dadu
# ─────────────────────────────────────────────────────────────────────────────

_TERM_RE = re.compile(r"([+-])?(?:(\d*)d(\d+)(?:(kh|kl)(\d+))?|(\d+))", re.IGNORECASE)


def roll_expression(expr: str, rng: random.Random, crit: bool = False) -> tuple[int, str]:
    """Lempar ekspresi dadu seperti '1d20+5', '2d6+1d4-1', '4d6kh3', '2d20kl1'.

    crit=True menggandakan JUMLAH dadu (aturan critical hit), bukan modifier.
    Mengembalikan (total, rincian_teks).
    """
    clean = expr.replace(" ", "").lower()
    if not clean:
        raise ValueError("Notasi dadu kosong.")

    pos, total, parts = 0, 0, []
    for m in _TERM_RE.finditer(clean):
        if m.start() != pos:
            raise ValueError(f"Notasi dadu tidak valid: '{expr}'")
        pos = m.end()
        sign = -1 if m.group(1) == "-" else 1
        sign_txt = "-" if sign < 0 else "+"

        if m.group(3):  # bagian dadu, mis. 2d6
            count = int(m.group(2) or 1)
            sides = int(m.group(3))
            if crit:
                count *= 2
            if not (1 <= count <= 100 and 2 <= sides <= 1000):
                raise ValueError("Jumlah dadu 1-100 dan sisi dadu 2-1000.")
            rolls = [rng.randint(1, sides) for _ in range(count)]
            kept = rolls
            if m.group(4):  # keep highest / keep lowest
                k = max(1, min(int(m.group(5)), count))
                kept = sorted(rolls, reverse=(m.group(4) == "kh"))[:k]
            subtotal = sum(kept)
            total += sign * subtotal
            note = f"{count}d{sides}{(m.group(4) or '') + (m.group(5) or '')}{rolls}"
            if kept is not rolls:
                note += f"→ambil {kept}"
            parts.append(f"{sign_txt} {note}")
        else:  # konstanta, mis. +5
            value = int(m.group(6))
            total += sign * value
            parts.append(f"{sign_txt} {value}")

    if pos != len(clean):
        raise ValueError(f"Notasi dadu tidak valid: '{expr}'")

    detail = " ".join(parts).lstrip("+ ").strip()
    return total, detail


def roll_d20(rng: random.Random, advantage: str = "normal") -> tuple[int, str]:
    """Lempar d20 dengan advantage/disadvantage. Mengembalikan (hasil, rincian)."""
    if advantage == "advantage":
        a, b = rng.randint(1, 20), rng.randint(1, 20)
        return max(a, b), f"d20 advantage [{a}, {b}] → {max(a, b)}"
    if advantage == "disadvantage":
        a, b = rng.randint(1, 20), rng.randint(1, 20)
        return min(a, b), f"d20 disadvantage [{a}, {b}] → {min(a, b)}"
    r = rng.randint(1, 20)
    return r, f"d20 [{r}]"


# ─────────────────────────────────────────────────────────────────────────────
# 3. State permainan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Character:
    name: str
    species: str
    char_class: str
    background: str
    abilities: dict[str, int]
    max_hp: int
    hp: int
    ac: int
    armor_name: str
    weapon: tuple[str, str, str]          # (nama, dadu damage, ability)
    spell_ability: Optional[str]
    level: int = 1
    xp: int = 0
    gold: int = 15
    hit_dice_left: int = 1
    inventory: dict[str, int] = field(default_factory=dict)
    conditions: list[str] = field(default_factory=list)

    @property
    def prof_bonus(self) -> int:
        return 2 + (self.level - 1) // 4

    def mod(self, ability: str) -> int:
        return ability_mod(self.abilities[ability.upper()])

    @property
    def hit_die(self) -> int:
        return CLASS_DATA[self.char_class]["hit_die"]


@dataclass
class Enemy:
    name: str
    max_hp: int
    hp: int
    ac: int
    attack_bonus: int
    damage_dice: str
    dex_mod: int = 0
    xp: int = 0


@dataclass
class GameState:
    character: Optional[Character] = None
    enemies: dict[str, Enemy] = field(default_factory=dict)
    initiative_order: list[tuple[str, int]] = field(default_factory=list)
    quests: dict[str, dict] = field(default_factory=dict)
    location: str = "Belum ditentukan"
    roll_log: list[str] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

    def log(self, text: str) -> str:
        """Catat kejadian mekanik (ditampilkan di sidebar UI)."""
        self.roll_log.append(text)
        self.roll_log[:] = self.roll_log[-30:]
        return text

    def find_enemy(self, name: str) -> Optional[Enemy]:
        if name in self.enemies:
            return self.enemies[name]
        lowered = name.lower().strip()
        for key, enemy in self.enemies.items():
            if key.lower() == lowered:
                return enemy
        matches = [e for k, e in self.enemies.items() if lowered in k.lower()]
        return matches[0] if len(matches) == 1 else None

    def summary(self) -> str:
        """Ringkasan state lengkap untuk LLM."""
        lines = [f"Lokasi: {self.location}"]
        c = self.character
        if c is None:
            lines.append("Karakter: BELUM DIBUAT. Pandu pemain membuat karakter dulu.")
        else:
            abil = ", ".join(f"{a} {c.abilities[a]} ({fmt_mod(c.mod(a))})" for a in ABILITIES)
            inv = ", ".join(f"{k} x{v}" for k, v in c.inventory.items()) or "kosong"
            next_xp = XP_THRESHOLDS[c.level] if c.level < 20 else "-"
            spell = ""
            if c.spell_ability:
                spell = (f"\nSpellcasting: {c.spell_ability}, spell attack "
                         f"{fmt_mod(c.mod(c.spell_ability) + c.prof_bonus)}, "
                         f"spell save DC {8 + c.prof_bonus + c.mod(c.spell_ability)}")
            lines.append(
                f"Karakter: {c.name}, {c.species} {c.char_class} level {c.level} "
                f"(XP {c.xp}/{next_xp})\n"
                f"Background: {c.background or '-'}\n"
                f"HP {c.hp}/{c.max_hp} | AC {c.ac} ({c.armor_name}) | "
                f"Proficiency {fmt_mod(c.prof_bonus)} | Gold {c.gold} gp | "
                f"Hit dice tersisa {c.hit_dice_left}d{c.hit_die}\n"
                f"Ability: {abil}\n"
                f"Senjata utama: {c.weapon[0]} ({c.weapon[1]} + {c.weapon[2]})"
                f"{spell}\n"
                f"Inventaris: {inv}\n"
                f"Kondisi: {', '.join(c.conditions) or 'normal'}"
            )
        if self.enemies:
            foes = "; ".join(f"{e.name} HP {e.hp}/{e.max_hp} AC {e.ac}"
                             for e in self.enemies.values())
            lines.append(f"Musuh aktif: {foes}")
            if self.initiative_order:
                order = " → ".join(f" {n} ({v})" for n, v in self.initiative_order)
                lines.append(f"Urutan inisiatif: {order}")
        else:
            lines.append("Musuh aktif: tidak ada (bukan mode combat)")
        if self.quests:
            q = "; ".join(f"[{v['status']}] {k}: {v['note']}" for k, v in self.quests.items())
            lines.append(f"Quest: {q}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Integrasi API eksternal: D&D 5e SRD API (dnd5eapi.co)
# ─────────────────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def srd_get(path: str, timeout: float = 8.0) -> Optional[dict]:
    """GET ke dnd5eapi.co, mencoba endpoint /api/2014 lalu /api (fallback)."""
    for base in SRD_API_BASES:
        try:
            resp = requests.get(f"{base}/{path.lstrip('/')}", timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            continue
    return None


def srd_find(category: str, name: str) -> Optional[dict]:
    """Cari entri SRD berdasarkan nama: coba index langsung, lalu pencarian nama."""
    data = srd_get(f"{category}/{slugify(name)}")
    if data and "index" in data:
        return data
    listing = srd_get(f"{category}?name={requests.utils.quote(name)}")
    if listing and listing.get("results"):
        return srd_get(f"{category}/{listing['results'][0]['index']}")
    return None


def _desc(data: dict, limit: int = 900) -> str:
    desc = data.get("desc", "")
    if isinstance(desc, list):
        desc = " ".join(desc)
    return desc[:limit] + ("…" if len(desc) > limit else "")


def format_srd(category: str, data: dict) -> str:
    """Ringkas JSON SRD menjadi teks pendek yang mudah dipakai LLM."""
    name = data.get("name", "?")
    if category == "spells":
        dmg = data.get("damage", {})
        dmg_txt = ""
        if isinstance(dmg, dict):
            if dmg.get("damage_at_slot_level"):
                dmg_txt = f"Damage per slot: {dmg['damage_at_slot_level']}"
            elif dmg.get("damage_at_character_level"):
                dmg_txt = f"Damage per level karakter: {dmg['damage_at_character_level']}"
        elif isinstance(dmg, list) and dmg:
            dmg_txt = f"Damage: {dmg}"
        save = data.get("dc", {}) or {}
        save_txt = f"Saving throw: {save.get('dc_type', {}).get('name', '')}" if save else ""
        return (f"{name} (level {data.get('level')}, {data.get('school', {}).get('name', '')})\n"
                f"Casting time {data.get('casting_time')}, range {data.get('range')}, "
                f"durasi {data.get('duration')}, komponen {''.join(data.get('components', []))}\n"
                f"{dmg_txt} {save_txt}\n{_desc(data)}")
    if category == "monsters":
        ac = data.get("armor_class", [{}])
        ac_val = ac[0].get("value") if isinstance(ac, list) and ac else ac
        actions = []
        for a in data.get("actions", [])[:4]:
            dmg = ", ".join(d.get("damage_dice", "") for d in a.get("damage", []) if "damage_dice" in d)
            bonus = a.get("attack_bonus")
            actions.append(f"{a.get('name')}" + (f" (+{bonus} to hit, {dmg})" if bonus is not None else ""))
        stats = " ".join(f"{k[:3].upper()} {data.get(k)}" for k in
                         ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"])
        return (f"{name}: {data.get('size')} {data.get('type')}, CR {data.get('challenge_rating')}, "
                f"XP {data.get('xp')}\nAC {ac_val}, HP {data.get('hit_points')} ({data.get('hit_points_dice', '')})\n"
                f"{stats}\nAksi: {'; '.join(actions) or '-'}")
    if category == "equipment":
        dmg = data.get("damage", {}) or {}
        extra = f"Damage {dmg.get('damage_dice')} {dmg.get('damage_type', {}).get('name', '')}" if dmg else ""
        ac = data.get("armor_class")
        if ac:
            extra += f" AC dasar {ac.get('base')}" + (" + DEX" if ac.get("dex_bonus") else "")
        cost = data.get("cost", {})
        return f"{name}: {data.get('equipment_category', {}).get('name', '')}. {extra}. Harga {cost.get('quantity', '?')} {cost.get('unit', '')}\n{_desc(data)}"
    return f"{name}\n{_desc(data, 1200)}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tools untuk agent
# ─────────────────────────────────────────────────────────────────────────────

def build_tools(state: GameState) -> list:
    """Buat semua tools yang terikat ke satu GameState (satu sesi pemain)."""

    def need_character() -> Optional[str]:
        if state.character is None:
            return "ERROR: Karakter belum dibuat. Panggil create_character terlebih dahulu."
        return None

    # ── Dadu & cek kemampuan ────────────────────────────────────────────────
    @tool
    def roll_dice(notation: str, reason: str) -> str:
        """Lempar dadu dengan notasi standar, mis. '1d20+3', '2d6+1d4', '4d6kh3'.
        Wajib dipakai untuk SETIAP lemparan dadu yang tidak tercakup tool lain.

        Args:
            notation: notasi dadu.
            reason: untuk apa lemparan ini (mis. 'damage fireball', 'tebakan acak NPC').
        """
        try:
            total, detail = roll_expression(notation, state.rng)
        except ValueError as e:
            return f"ERROR: {e}"
        return state.log(f"🎲 {reason}: {notation} → {detail} = **{total}**")

    @tool
    def ability_check(ability: Literal["STR", "DEX", "CON", "INT", "WIS", "CHA"],
                      dc: int,
                      skill_or_purpose: str,
                      proficient: bool = False,
                      advantage: Literal["normal", "advantage", "disadvantage"] = "normal",
                      kind: Literal["check", "save"] = "check") -> str:
        """Lakukan ability check atau saving throw karakter pemain melawan DC.
        Modifier dihitung otomatis dari character sheet.

        Args:
            ability: ability yang dipakai.
            dc: Difficulty Class (5 sangat mudah, 10 mudah, 15 sedang, 20 sulit, 25 sangat sulit).
            skill_or_purpose: nama skill atau tujuan, mis. 'Stealth', 'Perception', 'menahan racun'.
            proficient: True jika karakter mahir di skill/saving throw ini.
            advantage: 'advantage', 'disadvantage', atau 'normal'.
            kind: 'check' untuk ability/skill check, 'save' untuk saving throw.
        """
        if err := need_character():
            return err
        c = state.character
        roll, detail = roll_d20(state.rng, advantage)
        bonus = c.mod(ability) + (c.prof_bonus if proficient else 0)
        total = roll + bonus
        success = total >= dc
        label = "Saving throw" if kind == "save" else "Check"
        verdict = "BERHASIL ✅" if success else "GAGAL ❌"
        if roll == 20:
            verdict += " (natural 20!)"
        elif roll == 1:
            verdict += " (natural 1!)"
        return state.log(f"🎲 {label} {ability} ({skill_or_purpose}): {detail} {fmt_mod(bonus)} "
                         f"= **{total}** vs DC {dc} → {verdict}")

    # ── Karakter ─────────────────────────────────────────────────────────────
    @tool
    def create_character(name: str,
                         species: str,
                         char_class: ClassName,
                         background: str = "",
                         stat_method: Literal["standard", "roll"] = "standard") -> str:
        """Buat karakter pemain level 1. Ability score, HP, AC, senjata, dan
        perlengkapan awal dihitung otomatis sesuai class.

        Args:
            name: nama karakter.
            species: ras/spesies, mis. Human, Elf, Dwarf, Halfling, Gnome, Half-Orc, Tiefling, Dragonborn.
            char_class: class D&D (nama bahasa Inggris).
            background: latar belakang singkat karakter (opsional).
            stat_method: 'standard' (15,14,13,12,10,8) atau 'roll' (4d6 buang terendah).
        """
        data = CLASS_DATA[char_class]
        roll_note = ""
        if stat_method == "roll":
            scores = []
            for _ in range(6):
                rolls = [state.rng.randint(1, 6) for _ in range(4)]
                scores.append(sum(sorted(rolls)[1:]))
            scores.sort(reverse=True)
            roll_note = f" (hasil 4d6 drop lowest: {scores})"
        else:
            scores = list(STANDARD_ARRAY)
        abilities = {ab: scores[i] for i, ab in enumerate(data["priority"])}
        abilities = {ab: abilities[ab] for ab in ABILITIES}

        dex, con, wis = (ability_mod(abilities[a]) for a in ("DEX", "CON", "WIS"))
        armor_name, armor_kind, base = data["armor"]
        ac = {"heavy": base, "medium": base + min(dex, 2), "light": base + dex,
              "none": 10 + dex, "barbarian": 10 + dex + con, "monk": 10 + dex + wis}[armor_kind]
        if data["shield"]:
            ac += 2
            armor_name += " + Shield"
        max_hp = max(1, data["hit_die"] + con)

        state.character = Character(
            name=name, species=species, char_class=char_class, background=background,
            abilities=abilities, max_hp=max_hp, hp=max_hp, ac=ac, armor_name=armor_name,
            weapon=data["weapon"], spell_ability=data["spell"],
            inventory=dict(data["items"]), hit_dice_left=1,
        )
        state.log(f"🧙 Karakter dibuat: {name}, {species} {char_class}{roll_note}")
        return "Karakter berhasil dibuat.\n" + state.summary()

    @tool
    def get_game_state() -> str:
        """Lihat state permainan saat ini: character sheet, inventaris, kondisi,
        musuh aktif, urutan inisiatif, quest, dan lokasi. Panggil di awal sesi
        atau kapan pun kamu ragu tentang angka/fakta permainan."""
        return state.summary()

    @tool
    def update_hp(amount: int, reason: str) -> str:
        """Ubah HP karakter pemain. Angka negatif = damage, positif = heal.
        Gunakan untuk damage dari jebakan/lingkungan/efek, atau heal dari potion/spell.
        (Damage dari serangan musuh sudah otomatis lewat enemy_attack.)

        Args:
            amount: perubahan HP (mis. -7 atau +5).
            reason: penyebabnya.
        """
        if err := need_character():
            return err
        c = state.character
        before = c.hp
        c.hp = max(0, min(c.max_hp, c.hp + amount))
        msg = f"❤️ HP {c.name}: {before} → {c.hp}/{c.max_hp} ({fmt_mod(amount)}, {reason})"
        if c.hp == 0 and "Unconscious" not in c.conditions:
            c.conditions.append("Unconscious")
            msg += ". TUMBANG (Unconscious)! Mulai death saving throw."
        elif c.hp > 0 and "Unconscious" in c.conditions:
            c.conditions.remove("Unconscious")
            msg += ". Sadar kembali."
        return state.log(msg)

    @tool
    def update_inventory(item: str, quantity_change: int) -> str:
        """Tambah (angka positif) atau kurangi (angka negatif) item di inventaris.

        Args:
            item: nama item.
            quantity_change: mis. 1 untuk menambah satu, -1 untuk memakai/menjual satu.
        """
        if err := need_character():
            return err
        inv = state.character.inventory
        key = next((k for k in inv if k.lower() == item.lower()), item)
        current = inv.get(key, 0)
        if current + quantity_change < 0:
            return f"ERROR: {key} hanya ada {current}, tidak bisa dikurangi {abs(quantity_change)}."
        new = current + quantity_change
        if new == 0:
            inv.pop(key, None)
        else:
            inv[key] = new
        return state.log(f"🎒 {key}: {current} → {new}")

    @tool
    def update_gold(amount: int, reason: str) -> str:
        """Tambah/kurangi gold (gp) karakter. Negatif untuk membayar.

        Args:
            amount: perubahan gold.
            reason: alasannya (mis. 'hadiah quest', 'beli potion').
        """
        if err := need_character():
            return err
        c = state.character
        if c.gold + amount < 0:
            return f"ERROR: Gold tidak cukup. Saat ini {c.gold} gp, butuh {abs(amount)} gp."
        before = c.gold
        c.gold += amount
        return state.log(f"💰 Gold: {before} → {c.gold} gp ({reason})")

    @tool
    def set_condition(condition: str, active: bool) -> str:
        """Pasang atau hapus kondisi pada karakter (mis. Poisoned, Frightened, Prone, Blinded).

        Args:
            condition: nama kondisi (gunakan nama SRD dalam bahasa Inggris).
            active: True untuk memasang, False untuk menghapus.
        """
        if err := need_character():
            return err
        conds = state.character.conditions
        cond = condition.strip().title()
        if active and cond not in conds:
            conds.append(cond)
        elif not active and cond in conds:
            conds.remove(cond)
        return state.log(f"⚠️ Kondisi {cond}: {'aktif' if active else 'hilang'}")

    @tool
    def take_rest(kind: Literal["short", "long"]) -> str:
        """Karakter beristirahat. Short rest: pakai 1 hit die untuk heal.
        Long rest: HP penuh, hit dice pulih, kondisi ringan hilang."""
        if err := need_character():
            return err
        c = state.character
        if kind == "long":
            c.hp = c.max_hp
            c.hit_dice_left = c.level
            c.conditions = [x for x in c.conditions if x not in
                            ("Poisoned", "Frightened", "Unconscious", "Prone", "Exhaustion")]
            return state.log(f"🏕️ Long rest: HP penuh {c.hp}/{c.max_hp}, hit dice pulih.")
        if c.hp >= c.max_hp:
            return state.log(f"☕ Short rest: HP sudah penuh ({c.hp}/{c.max_hp}), hit dice tidak dipakai.")
        if c.hit_dice_left <= 0:
            return "Tidak ada hit dice tersisa. Butuh long rest."
        heal = max(1, state.rng.randint(1, c.hit_die) + c.mod("CON"))
        c.hit_dice_left -= 1
        before = c.hp
        c.hp = min(c.max_hp, c.hp + heal)
        return state.log(f"☕ Short rest: heal {heal}, HP {before} → {c.hp}/{c.max_hp}")

    @tool
    def award_xp(amount: int, reason: str) -> str:
        """Beri XP ke karakter (setelah mengalahkan musuh, menyelesaikan quest,
        atau roleplay yang bagus). Naik level dihitung otomatis.

        Args:
            amount: jumlah XP.
            reason: alasannya.
        """
        if err := need_character():
            return err
        c = state.character
        c.xp += amount
        msg = f"⭐ +{amount} XP ({reason}). Total {c.xp} XP."
        while c.level < 20 and c.xp >= XP_THRESHOLDS[c.level]:
            c.level += 1
            gain = max(1, c.hit_die // 2 + 1 + c.mod("CON"))
            c.max_hp += gain
            c.hp += gain
            c.hit_dice_left += 1
            msg += f" 🎉 NAIK LEVEL {c.level}! Max HP +{gain} → {c.max_hp}."
        return state.log(msg)

    # ── Dunia & quest ────────────────────────────────────────────────────────
    @tool
    def set_location(name: str) -> str:
        """Catat lokasi karakter saat ini setiap kali pindah tempat."""
        state.location = name
        return state.log(f"📍 Lokasi: {name}")

    @tool
    def update_quest(title: str, status: Literal["aktif", "selesai", "gagal"], note: str = "") -> str:
        """Tambah atau perbarui quest di quest log.

        Args:
            title: judul quest singkat.
            status: 'aktif', 'selesai', atau 'gagal'.
            note: tujuan/progres singkat.
        """
        prev = state.quests.get(title, {})
        state.quests[title] = {"status": status, "note": note or prev.get("note", "")}
        return state.log(f"📜 Quest '{title}': {status}")

    # ── Combat ───────────────────────────────────────────────────────────────
    @tool
    def add_enemy(name: str,
                  srd_monster: Optional[str] = None,
                  hp: Optional[int] = None,
                  ac: Optional[int] = None,
                  attack_bonus: Optional[int] = None,
                  damage_dice: Optional[str] = None) -> str:
        """Masukkan musuh ke arena combat.
        Isi `srd_monster` (nama monster SRD bahasa Inggris, mis. 'goblin', 'wolf',
        'skeleton', 'bandit') agar statistik diambil otomatis dari D&D 5e SRD API.
        Untuk musuh orisinal, isi hp, ac, attack_bonus, dan damage_dice sendiri.

        Args:
            name: nama unik musuh di cerita, mis. 'Goblin 1' atau 'Kuntilanak Rawa'.
            srd_monster: nama monster SRD (opsional).
            hp: hit points (wajib jika tanpa srd_monster).
            ac: armor class.
            attack_bonus: bonus serangan utama.
            damage_dice: damage serangan utama, mis. '1d6+2'.
        """
        dex_mod, xp, source = 0, 0, "custom"
        if srd_monster:
            data = srd_find("monsters", srd_monster)
            if data:
                source = "SRD API"
                hp = hp or data.get("hit_points")
                acs = data.get("armor_class", [{}])
                ac = ac or (acs[0].get("value") if isinstance(acs, list) and acs else acs)
                dex_mod = ability_mod(data.get("dexterity", 10))
                xp = data.get("xp", 0)
                for action in data.get("actions", []):
                    if action.get("attack_bonus") is not None:
                        attack_bonus = attack_bonus if attack_bonus is not None else action["attack_bonus"]
                        dice = [d.get("damage_dice") for d in action.get("damage", []) if d.get("damage_dice")]
                        damage_dice = damage_dice or (dice[0] if dice else None)
                        break
        if hp is None or ac is None:
            return ("ERROR: Statistik musuh tidak lengkap (SRD API tidak tersedia atau monster tidak "
                    "ditemukan). Panggil ulang dengan hp, ac, attack_bonus, dan damage_dice.")
        enemy = Enemy(name=name, max_hp=int(hp), hp=int(hp), ac=int(ac),
                      attack_bonus=int(attack_bonus if attack_bonus is not None else 3),
                      damage_dice=damage_dice or "1d6+1", dex_mod=dex_mod, xp=int(xp or 0))
        state.enemies[name] = enemy
        return state.log(f"👹 Musuh muncul: {name} (HP {enemy.hp}, AC {enemy.ac}, "
                         f"serangan {fmt_mod(enemy.attack_bonus)} / {enemy.damage_dice}) [{source}]")

    @tool
    def roll_initiative() -> str:
        """Lempar inisiatif untuk pemain dan semua musuh aktif, lalu tetapkan urutan giliran.
        Panggil sekali di awal setiap combat setelah semua musuh ditambahkan."""
        if err := need_character():
            return err
        order = []
        c = state.character
        r = state.rng.randint(1, 20)
        order.append((c.name, r + c.mod("DEX")))
        for e in state.enemies.values():
            order.append((e.name, state.rng.randint(1, 20) + e.dex_mod))
        order.sort(key=lambda x: x[1], reverse=True)
        state.initiative_order = order
        return state.log("⚔️ Inisiatif: " + " → ".join(f"{n} ({v})" for n, v in order))

    @tool
    def player_attack(target: str,
                      attack_type: Literal["weapon", "spell"] = "weapon",
                      damage_dice: Optional[str] = None,
                      advantage: Literal["normal", "advantage", "disadvantage"] = "normal",
                      description: str = "") -> str:
        """Pemain menyerang musuh. Attack roll vs AC dan damage dihitung otomatis;
        HP musuh langsung dikurangi. Natural 20 = critical hit (dadu damage ganda).

        Args:
            target: nama musuh (sesuai add_enemy).
            attack_type: 'weapon' memakai senjata utama, 'spell' memakai spell attack.
            damage_dice: override dadu damage (wajib untuk spell, mis. '1d10' Fire Bolt;
                         untuk weapon kosongkan agar memakai senjata utama).
            advantage: 'advantage', 'disadvantage', atau 'normal'.
            description: deskripsi singkat serangannya.
        """
        if err := need_character():
            return err
        c = state.character
        enemy = state.find_enemy(target)
        if enemy is None:
            names = ", ".join(state.enemies) or "tidak ada"
            return f"ERROR: Musuh '{target}' tidak ditemukan. Musuh aktif: {names}."

        if attack_type == "spell":
            if not c.spell_ability:
                return f"ERROR: {c.char_class} tidak punya spellcasting di level ini."
            ability = c.spell_ability
            dmg_expr = damage_dice or "1d8"
            dmg_bonus = 0
        else:
            ability = c.weapon[2]
            dmg_expr = damage_dice or c.weapon[1]
            dmg_bonus = c.mod(ability)

        roll, detail = roll_d20(state.rng, advantage)
        atk_bonus = c.mod(ability) + c.prof_bonus
        total = roll + atk_bonus
        what = description or (c.weapon[0] if attack_type == "weapon" else "spell")

        if roll == 1 or (total < enemy.ac and roll != 20):
            return state.log(f"🗡️ {c.name} menyerang {enemy.name} ({what}): {detail} {fmt_mod(atk_bonus)} "
                             f"= **{total}** vs AC {enemy.ac} → MELESET")

        crit = roll == 20
        dmg, dmg_detail = roll_expression(dmg_expr, state.rng, crit=crit)
        dmg = max(1, dmg + dmg_bonus)
        enemy.hp = max(0, enemy.hp - dmg)
        msg = (f"🗡️ {c.name} menyerang {enemy.name} ({what}): {detail} {fmt_mod(atk_bonus)} = **{total}** "
               f"vs AC {enemy.ac} → {'CRITICAL HIT! 💥' if crit else 'KENA'} "
               f"Damage {dmg_detail}{' ' + fmt_mod(dmg_bonus) if dmg_bonus else ''} = **{dmg}**. "
               f"HP {enemy.name}: {enemy.hp}/{enemy.max_hp}")
        if enemy.hp == 0:
            msg += f". {enemy.name} KALAH!"
            state.enemies.pop(enemy.name, None)
            state.initiative_order = [x for x in state.initiative_order if x[0] != enemy.name]
            if enemy.xp:
                msg += f" (bernilai {enemy.xp} XP, berikan dengan award_xp)"
            if not state.enemies:
                msg += " Semua musuh sudah kalah, combat selesai."
                state.initiative_order = []
        return state.log(msg)

    @tool
    def damage_enemy(target: str, amount: int, reason: str) -> str:
        """Kurangi HP musuh di luar attack roll, mis. musuh gagal saving throw
        terhadap spell area. Untuk serangan biasa pakai player_attack.

        Args:
            target: nama musuh.
            amount: jumlah damage (positif). Lempar dulu dengan roll_dice.
            reason: penyebab damage.
        """
        enemy = state.find_enemy(target)
        if enemy is None:
            return f"ERROR: Musuh '{target}' tidak ditemukan."
        enemy.hp = max(0, enemy.hp - abs(amount))
        msg = f"💥 {enemy.name} terkena {abs(amount)} damage ({reason}). HP {enemy.hp}/{enemy.max_hp}"
        if enemy.hp == 0:
            msg += f". {enemy.name} KALAH!"
            state.enemies.pop(enemy.name, None)
            state.initiative_order = [x for x in state.initiative_order if x[0] != enemy.name]
            if enemy.xp:
                msg += f" (bernilai {enemy.xp} XP)"
        return state.log(msg)

    @tool
    def enemy_attack(enemy_name: str,
                     advantage: Literal["normal", "advantage", "disadvantage"] = "normal",
                     description: str = "") -> str:
        """Musuh menyerang karakter pemain memakai statistik musuh tersebut.
        Attack roll vs AC pemain dan damage dihitung otomatis; HP pemain langsung dikurangi.

        Args:
            enemy_name: nama musuh yang menyerang.
            advantage: 'advantage', 'disadvantage', atau 'normal'.
            description: deskripsi singkat serangannya.
        """
        if err := need_character():
            return err
        c = state.character
        enemy = state.find_enemy(enemy_name)
        if enemy is None:
            return f"ERROR: Musuh '{enemy_name}' tidak ditemukan."
        roll, detail = roll_d20(state.rng, advantage)
        total = roll + enemy.attack_bonus
        what = description or "serangan"
        if roll == 1 or (total < c.ac and roll != 20):
            return state.log(f"🛡️ {enemy.name} menyerang {c.name} ({what}): {detail} "
                             f"{fmt_mod(enemy.attack_bonus)} = **{total}** vs AC {c.ac} → MELESET")
        crit = roll == 20
        dmg, dmg_detail = roll_expression(enemy.damage_dice, state.rng, crit=crit)
        dmg = max(1, dmg)
        before = c.hp
        c.hp = max(0, c.hp - dmg)
        msg = (f"🩸 {enemy.name} menyerang {c.name} ({what}): {detail} {fmt_mod(enemy.attack_bonus)} "
               f"= **{total}** vs AC {c.ac} → {'CRITICAL HIT! 💥' if crit else 'KENA'} "
               f"Damage {dmg_detail} = **{dmg}**. HP {c.name}: {before} → {c.hp}/{c.max_hp}")
        if c.hp == 0 and "Unconscious" not in c.conditions:
            c.conditions.append("Unconscious")
            msg += ". TUMBANG! Mulai death saving throw."
        return state.log(msg)

    @tool
    def end_combat(outcome: str) -> str:
        """Akhiri combat (musuh kabur, menyerah, atau pemain melarikan diri).
        Menghapus semua musuh aktif dan urutan inisiatif.

        Args:
            outcome: ringkasan hasil combat.
        """
        state.enemies.clear()
        state.initiative_order = []
        return state.log(f"🏁 Combat selesai: {outcome}")

    # ── Referensi aturan (API eksternal) ─────────────────────────────────────
    @tool
    def lookup_srd(category: Literal["spells", "monsters", "conditions", "equipment",
                                     "magic-items", "classes", "races", "features",
                                     "rule-sections"],
                   name: str) -> str:
        """Cari aturan resmi D&D 5e SRD dari dnd5eapi.co (API eksternal).
        Gunakan saat pemain bertanya tentang spell, monster, kondisi, item, atau aturan,
        dan sebelum menerapkan spell/monster agar angkanya akurat.

        Args:
            category: kategori SRD.
            name: nama dalam bahasa Inggris, mis. 'Fireball', 'Goblin', 'Poisoned', 'Longsword'.
        """
        data = srd_find(category, name)
        if data is None:
            return (f"Tidak ditemukan '{name}' di kategori {category} SRD, atau API sedang "
                    f"tidak bisa diakses. Jika ini konten di luar SRD, jelaskan secara umum "
                    f"tanpa mengutip buku resmi.")
        return f"[Sumber: D&D 5e SRD via dnd5eapi.co]\n{format_srd(category, data)}"

    return [
        roll_dice, ability_check, create_character, get_game_state, update_hp,
        update_inventory, update_gold, set_condition, take_rest, award_xp,
        set_location, update_quest, add_enemy, roll_initiative, player_attack,
        damage_enemy, enemy_attack, end_combat, lookup_srd,
    ]
