#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
lookup_to_anki.py — CLI vocab capturer for EN/SV (multi-language ready)

- --lang lets you force language (auto|en|sv|zh|de|fr|...); default auto
- Auto-detect via langdetect (if installed), else translate-shell
- EN input: English definitions (dictionaryapi.dev) + ZH gloss
- SV input: EN gloss + ZH gloss
- Appends TSV: Word<TAB>EN<TAB>ZH to ./anki-vocab/vocab.tsv
- Speaks word with language-appropriate voice (disable via --no-audio)
"""

import os
import sys
import json
import argparse
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import quote

# -------------------- Paths & config --------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = Path(os.environ.get("VOCAB_REPO", SCRIPT_DIR))

PREFERRED_PLAYERS = [
    os.environ.get("MP3_PLAYER"),
    "mpv",
    "ffplay",
    "mpg123",
    "espeak-ng",
]

VOICE_MAP = {
    "en": os.environ.get("ESPEAK_VOICE_EN", "en-us"),
    "sv": os.environ.get("ESPEAK_VOICE_SV", "sv"),
    "zh": os.environ.get("ESPEAK_VOICE_ZH", "zh"),  # Mandarin voice varies by system
}
DEFAULT_VOICE = os.environ.get("ESPEAK_VOICE", "en-us")

TRANS_CMD = os.environ.get("TRANS_CMD", "trans")
AUTO_PUSH = os.environ.get("VOCAB_GIT_AUTO", "1") == "1"
HTTP_TIMEOUT = 8

# -------------------- helpers --------------------
def which(cmd):
    if not cmd:
        return None
    from shutil import which as _which
    return _which(cmd)

def sh(cmd, check=True, capture=False, quiet=False):
    if capture:
        return subprocess.run(
            cmd, shell=True, check=check,
            stdout=subprocess.PIPE,
            stderr=(subprocess.DEVNULL if quiet else subprocess.STDOUT),
            text=True
        ).stdout
    return subprocess.run(
        cmd, shell=True, check=check,
        stdout=(subprocess.DEVNULL if quiet else None),
        stderr=(subprocess.DEVNULL if quiet else None),
    )

def fetch_json(url, timeout=HTTP_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))

# -------------------- detection & translation --------------------
def detect_lang_auto(text):
    # 1) langdetect (best) if installed
    try:
        from langdetect import detect
        code = detect(text)  # e.g., 'en', 'sv', 'zh-cn' -> keep 2-letter base
        if code:
            return code.split("-")[0]
    except Exception:
        pass
    # 2) translate-shell fallback
    try:
        out = sh(f'{TRANS_CMD} -id -b "{text}"', check=False, capture=True, quiet=True)
        code = (out or "").strip().lower()
        # normalize common strings like "swedish", "english", etc.
        mapping = {
            "english": "en", "swedish": "sv", "svenska": "sv",
            "chinese": "zh", "chinese (simplified)": "zh"
        }
        if code in mapping:
            return mapping[code]
        if code:
            return code.split("-")[0][:2]
    except Exception:
        pass
    return "en"

def trans_brief(src, dst, text):
    try:
        out = sh(f'{TRANS_CMD} -b {src}:{dst} "{text}"', check=False, capture=True, quiet=True)
        for line in (out or "").splitlines():
            s = line.strip()
            if s:
                return s
    except Exception:
        pass
    return ""

# -------------------- dictionary for EN --------------------
def english_defs_from_dictionaryapi(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
    try:
        data = fetch_json(url)
        defs, audio_url = [], None
        if isinstance(data, list) and data:
            entry = data[0]
            for p in entry.get("phonetics", []):
                au = p.get("audio")
                if au:
                    audio_url = au
                    break
            for m in entry.get("meanings", []):
                part = m.get("partOfSpeech") or ""
                for d in m.get("definitions", []):
                    defi = d.get("definition", "")
                    ex = d.get("example")
                    short = f"[{part}] {defi}".strip()
                    if ex:
                        short += f" (e.g. {ex})"
                    if short:
                        defs.append(short)
        return audio_url, defs
    except urllib.error.HTTPError as e:
        return None, [f"(dictapi HTTP {e.code})"]
    except Exception as e:
        return None, [f"(dictapi error: {e})"]

# -------------------- audio --------------------
def pick_player():
    for p in PREFERRED_PLAYERS:
        exe = which(p)
        if exe:
            return Path(exe).name
    return None

def speak_with_espeak(word, lang_code):
    voice = VOICE_MAP.get(lang_code, DEFAULT_VOICE)
    try:
        sh(f'espeak-ng -v {voice} "{word}"', check=False, quiet=True)
    except Exception:
        pass

def play_audio(word, lang_code, audio_url=None, enable=True):
    if not enable:
        return
    player = pick_player()
    if audio_url and player in ("mpv", "ffplay", "mpg123"):
        try:
            if player == "mpv":
                sh(f'mpv --really-quiet --no-video "{audio_url}"', check=False, quiet=True)
                return
            elif player == "ffplay":
                sh(f'ffplay -autoexit -nodisp -loglevel quiet "{audio_url}"', check=False, quiet=True)
                return
            elif player == "mpg123":
                sh(f'mpg123 -q "{audio_url}"', check=False, quiet=True)
                return
        except Exception:
            pass
    speak_with_espeak(word, lang_code)

# -------------------- file & git --------------------
def ensure_repo():
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if not (REPO_DIR / ".git").exists():
        sh(f'git -C "{REPO_DIR}" init', check=False)

def append_tsv(tsv_path: Path, word: str, en_text: str, zh_text: str):
    ensure_repo()
    tsv_path.touch(exist_ok=True)
    line = f"{word}\t{en_text}\t{zh_text}\n"
    with tsv_path.open("a", encoding="utf-8") as f:
        f.write(line)
    return line

def has_remote():
    try:
        out = sh(f'git -C "{REPO_DIR}" remote -v', check=False, capture=True, quiet=True)
        return bool(out.strip())
    except Exception:
        return False

def git_commit_push(message):
    try:
        sh(f'git -C "{REPO_DIR}" add "{tsv_path.name}"', check=False, quiet=True)
        sh(f'git -C "{REPO_DIR}" commit -m "{message}"', check=False, quiet=True)
        if AUTO_PUSH and has_remote():
            sh(f'git -C "{REPO_DIR}" push', check=False)
    except Exception:
        pass

def tsv_path_for_lang(lang_code: str) -> Path:
    """
    Determine TSV path based on source language code.
    Unknown languages will still map to vocab_<code>.tsv
    """
    code = (lang_code or "en").lower()
    if len(code) > 2:  # normalize like 'zh-cn' -> 'zh'
        code = code.split("-")[0]
    fname = f"vocab_{code}.tsv"
    return REPO_DIR / fname

# -------------------- main --------------------
def main():
    ap = argparse.ArgumentParser(description="Lookup word/phrase and append to Anki TSV")
    ap.add_argument("term", nargs="+", help="Word or phrase")
    ap.add_argument("--lang", "-l", default="auto",
                    help="Source language code (e.g., auto|en|sv|zh|de|fr). Default: auto")
    ap.add_argument("--no-audio", action="store_true", help="Disable audio playback")
    args = ap.parse_args()

    term = " ".join(args.term).strip()
    lang = args.lang.lower()

    if lang == "auto":
        lang = detect_lang_auto(term)

    tsv_path = tsv_path_for_lang(lang)

    en_text, zh_text, audio_url = "", "", None

    if lang == "en":
        audio_url, en_defs = english_defs_from_dictionaryapi(term)
        en_text = " ; ".join(en_defs) if en_defs else ""
        zh_text = trans_brief("en", "zh-CN", term) or ""
        play_audio(term, "en", audio_url=audio_url, enable=not args.no_audio)

    elif lang == "sv":
        en_text = trans_brief("sv", "en", term) or ""
        zh_text = trans_brief("sv", "zh-CN", term) or ""
        play_audio(term, "sv", audio_url=None, enable=not args.no_audio)
    else:
        # generic: translate to EN + ZH and speak in EN
        en_text = trans_brief(lang, "en", term) or ""
        zh_text = trans_brief(lang, "zh-CN", term) or ""
        play_audio(term, "en", audio_url=None, enable=not args.no_audio)

    saved = append_tsv(tsv_path, term, en_text, zh_text)
    git_commit_push(f"add {term}")

    print("Saved (TSV):")
    print(saved, end="")
    print(f"\nFile: {tsv_path}")
    if AUTO_PUSH and not has_remote():
        print("\n[hint] No git remote set. Add one:\n"
              f'  git -C "{REPO_DIR}" remote add origin <YOUR_GITHUB_URL>\n'
              f'  git -C "{REPO_DIR}" branch -M main && git -C "{REPO_DIR}" push -u origin main')

if __name__ == "__main__":
    main()
