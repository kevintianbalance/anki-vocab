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
REPO_DIR = Path(os.environ.get("VOCAB_REPO", str(Path.home() / "anki-vocab")))
TSV_FILE = REPO_DIR / "vocab.tsv"

# Audio selection order; can be overridden by env MP3_PLAYER
PREFERRED_PLAYERS = [
    os.environ.get("MP3_PLAYER"),  # user override
    "mpv",
    "ffplay",  # from ffmpeg
    "mpg123",
    "espeak-ng",  # TTS fallback
]

ESPEAK_VOICE = os.environ.get("ESPEAK_VOICE", "en-us")
TRANS_CMD = os.environ.get("TRANS_CMD", "trans")
AUTO_PUSH = os.environ.get("VOCAB_GIT_AUTO", "1") == "1"

# ---------- Small helpers ----------
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
    else:
        return subprocess.run(
            cmd, shell=True, check=check,
            stdout=(subprocess.DEVNULL if quiet else None),
            stderr=(subprocess.DEVNULL if quiet else None),
        )

def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))

# ---------- Dictionary providers ----------
def english_defs_from_dictionaryapi(word):
    """Use dictionaryapi.dev for EN defs + audio URL."""
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
    try:
        data = fetch_json(url)
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
    """Use translate-shell for brief ZH gloss."""
    try:
        out = sh(f'{TRANS_CMD} -b en:zh-CN "{word}"', check=False, capture=True, quiet=True)
        for line in (out or "").splitlines():
            line = line.strip()
            if line:
                return line
        return ""
    except Exception:
        return ""

# ---------- Audio ----------
def pick_player():
    for p in PREFERRED_PLAYERS:
        exe = which(p)
        if exe:
            return Path(exe).name
    return None

def play_audio(word, audio_url):
    player = pick_player()
    if not player:
        return  # nothing available; stay quiet

    # Stream mp3 if we have a media player (mpv/ffplay/mpg123)
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

    # Fallback to local TTS with espeak-ng if available
    if player == "espeak-ng" or which("espeak-ng"):
        try:
            sh(f'espeak-ng -v {ESPEAK_VOICE} "{word}"', check=False, quiet=True)
        except Exception:
            pass

# ---------- Save + Git ----------
def append_tsv(word, en_defs, zh_gloss):
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    TSV_FILE.touch(exist_ok=True)
    en = " ; ".join(en_defs) if en_defs else ""
    zh = zh_gloss or ""
    line = f"{word}\t{en}\t{zh}\n"
    with TSV_FILE.open("a", encoding="utf-8") as f:
        f.write(line)
    return line

def git_remote_exists():
    try:
        out = sh(f'git -C "{REPO_DIR}" remote -v', check=False, capture=True, quiet=True)
        return bool(out.strip())
    except Exception:
        return False

def git_commit_push(message):
    try:
        sh(f'git -C "{REPO_DIR}" add "{TSV_FILE.name}"', check=False, quiet=True)
        sh(f'git -C "{REPO_DIR}" commit -m "{message}"', check=False, quiet=True)
        if AUTO_PUSH and git_remote_exists():
            sh(f'git -C "{REPO_DIR}" push', check=False)
    except Exception:
        pass

# ---------- Main ----------
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

    # commit/push (push only if a remote exists)
    git_commit_push(f"add {word}")

    # echo to terminal
    print("Saved (TSV):")
    print(saved, end="")
    print(f"\nFile: {TSV_FILE}")
    if AUTO_PUSH and not git_remote_exists():
        print("\n[hint] No git remote set. Add one:\n"
              f'  git -C "{REPO_DIR}" remote add origin <YOUR_GITHUB_URL>\n'
               "  git -C \"{repo}\" branch -M main && git -C \"{repo}\" push -u origin main".format(repo=str(REPO_DIR)))

if __name__ == "__main__":
    main()
