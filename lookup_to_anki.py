#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import quote

# ---------- Configuration ----------
# Where to append the Anki-ready TSV (kept in a Git repo)
REPO_DIR = Path(os.environ.get("VOCAB_REPO", str(Path.home() / "anki-vocab")))
TSV_FILE = REPO_DIR / "vocab.tsv"

# Audio preference: try dictionaryapi.dev audio URL with mpg123; fallback to espeak-ng
MP3_PLAYER = os.environ.get("MP3_PLAYER", "mpg123")    # or "mpv", "ffplay"
ESPEAK_VOICE = os.environ.get("ESPEAK_VOICE", "en-us") # espeak-ng -v en-us

# Translator backend: translate-shell
TRANS_CMD = os.environ.get("TRANS_CMD", "trans")

# ---------- Helpers ----------
def sh(cmd, check=True, capture=False):
    if capture:
        return subprocess.run(cmd, shell=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
    else:
        return subprocess.run(cmd, shell=True, check=check)

def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))

def english_defs_from_dictionaryapi(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
    try:
        data = fetch_json(url)
        # data is a list; we’ll collect compact EN definitions + an example if present
        defs = []
        audio_url = None
        if isinstance(data, list) and data:
            entry = data[0]
            # phonetics audio
            for p in entry.get("phonetics", []):
                au = p.get("audio")
                if au:
                    audio_url = au
                    break
            # meanings
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

def chinese_gloss_with_trans(word):
    """
    Use translate-shell for an EN->ZH gloss of the headword (terse).
    -b : brief
    """
    try:
        out = sh(f'{TRANS_CMD} -b en:zh-CN "{word}"', check=False, capture=True).strip()
        # translate-shell may return multiple lines; take the first non-empty
        for line in out.splitlines():
            line = line.strip()
            if line:
                return line
        return ""
    except Exception:
        return ""

def play_audio(word, audio_url):
    if audio_url:
        # stream via mpg123 if available
        try:
            sh(f'{MP3_PLAYER} -q "{audio_url}"', check=False)
            return
        except Exception:
            pass
    # fallback: local TTS
    try:
        sh(f'espeak-ng -v {ESPEAK_VOICE} "{word}"', check=False)
    except Exception:
        pass

def append_tsv(word, en_defs, zh_gloss):
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    TSV_FILE.touch(exist_ok=True)
    # Join several EN definitions with " ; "
    en = " ; ".join(en_defs) if en_defs else ""
    zh = zh_gloss or ""
    line = f"{word}\t{en}\t{zh}\n"
    with TSV_FILE.open("a", encoding="utf-8") as f:
        f.write(line)
    return line

def git_commit_push(message):
    try:
        sh(f'git -C "{REPO_DIR}" add "{TSV_FILE.name}"', check=False)
        sh(f'git -C "{REPO_DIR}" commit -m "{message}"', check=False)
        sh(f'git -C "{REPO_DIR}" push', check=False)
    except Exception:
        pass

def main():
    if len(sys.argv) < 2:
        print("Usage: lookup_to_anki.py <word or phrase>")
        sys.exit(1)

    word = " ".join(sys.argv[1:]).strip()
    audio_url, en_defs = english_defs_from_dictionaryapi(word)
    zh_gloss = chinese_gloss_with_trans(word)

    # pronounce
    play_audio(word, audio_url)

    # save
    saved = append_tsv(word, en_defs, zh_gloss)

    # optional git sync
    if os.environ.get("VOCAB_GIT_AUTO", "1") == "1":
        git_commit_push(f"add {word}")

    # echo to terminal
    print("Saved (TSV):")
    print(saved, end="")
    print(f"\nFile: {TSV_FILE}")

if __name__ == "__main__":
    main()
