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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            if not content.strip():
                return None
            # Check if content is HTML (starts with < or <!)
            if content.strip().startswith("<"):
                return None
            return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    except Exception:
        return None

def fetch_folkets_lexikon(word, lang="en"):
    """Fetch and parse Folkets lexikon HTML response"""
    url = f"https://folkets-lexikon.csc.kth.se/folkets/service?word={quote(word)}&lang={lang}&output=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            
        import re
        translations = []
        
        # Extract content within <P></P> tags
        p_matches = re.findall(r'<P>(.*?)</P>', content, re.DOTALL | re.IGNORECASE)
        
        for p_content in p_matches[:2]:  # Limit to first 2 entries
            # Extract the main translation word (in <b> tags after the target language flag)
            if lang == "en":
                # Looking for Swedish word when translating from English
                sv_word_match = re.search(r'flag_18x12_sv\.png[^>]*>\s*<b>([^<]+)</b>', p_content)
                if sv_word_match:
                    translation = sv_word_match.group(1).strip()
                    
                    # Extract word class (verb, noun, etc.)
                    word_class_match = re.search(r'</b>\s+(\w+)', p_content)
                    word_class = word_class_match.group(1) if word_class_match else "word"
                    
                    # Extract examples
                    examples = []
                    example_matches = re.findall(r'Exempel:\s*([^<]+(?:<br>)?)', p_content)
                    if example_matches:
                        for ex in example_matches:
                            ex_clean = re.sub(r'<[^>]+>', '', ex).strip()
                            if ex_clean:
                                examples.append(ex_clean)
                    
                    translations.append({
                        "translation": translation,
                        "class": word_class,
                        "examples": examples
                    })
            else:
                # Looking for English word when translating from Swedish
                en_word_match = re.search(r'flag_18x12_en\.png[^>]*>\s*<b>([^<]+)</b>', p_content)
                if en_word_match:
                    translation = en_word_match.group(1).strip()
                    
                    word_class_match = re.search(r'</b>\s+(\w+)', p_content)
                    word_class = word_class_match.group(1) if word_class_match else "word"
                    
                    translations.append({
                        "translation": translation,
                        "class": word_class
                    })
        
        return translations if translations else None
        
    except Exception:
        return None

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

def trans_detailed(src, dst, text):
    """Get detailed translation with examples using translate-shell"""
    try:
        # Get detailed translation with examples
        out = sh(f'{TRANS_CMD} {src}:{dst} "{text}"', check=False, capture=True, quiet=True)
        lines = (out or "").splitlines()
        
        definitions = []
        current_pos = None
        in_definitions = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip the original word and simple translation
            if line.lower() == text.lower():
                continue
                
            # Look for definitions section
            if "Definitions of" in line:
                in_definitions = True
                continue
                
            if not in_definitions:
                continue
                
            # Skip language header like "[ Svenska -> English ]"
            if line.startswith("[") and "->" in line:
                continue
                
            # Detect part of speech (noun, verb, adjective, etc.)
            if line in ["noun", "verb", "adjective", "adverb", "conjunction", "preposition", "pronoun", "interjection"]:
                current_pos = line
                continue
                
            # Parse definition lines with examples
            if current_pos and line and not line.startswith("["):
                # Lines with translations and examples
                if "        " in line:  # Indented examples
                    parts = line.split()
                    if len(parts) >= 2:
                        translation = parts[0]
                        examples = ", ".join(parts[1:]) if len(parts) > 1 else ""
                        if examples:
                            definition = f"[{current_pos}] {translation} (e.g. {examples})"
                        else:
                            definition = f"[{current_pos}] {translation}"
                        definitions.append(definition)
                elif line and not line.startswith(text):
                    # Simple translation line
                    definition = f"[{current_pos}] {line}"
                    definitions.append(definition)
        
        if definitions:
            return " ; ".join(definitions)
        else:
            # Fallback to brief translation
            brief = trans_brief(src, dst, text)
            return brief if brief else ""
        
    except Exception:
        return trans_brief(src, dst, text)

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

def swedish_defs_with_examples(word):
    """Get Swedish definitions with examples from multiple sources"""
    
    # Try Wiktionary API first (most comprehensive)
    try:
        url = f"https://en.wiktionary.org/api/rest_v1/page/definition/{quote(word)}"
        data = fetch_json(url)
        
        defs = []
        if isinstance(data, dict):
            # Look for Swedish section
            for lang_key in ["Swedish", "sv"]:
                if lang_key in data:
                    for entry in data[lang_key][:2]:  # Limit to 2 entries
                        part = entry.get("partOfSpeech", "word")
                        for definition in entry.get("definitions", []):
                            def_text = definition.get("definition", "")
                            examples = definition.get("examples", [])
                            
                            if def_text:
                                # Clean HTML tags
                                import re
                                def_text = re.sub(r'<[^>]+>', '', def_text)
                                short = f"[{part}] {def_text}"
                                
                                if examples and examples[0]:
                                    example = re.sub(r'<[^>]+>', '', examples[0])
                                    short += f" (e.g. {example})"
                                
                                defs.append(short)
                                break  # One definition per part of speech
                    break
        
        if defs:
            return defs
    except Exception:
        pass
    
    # Try Folkets lexikon as backup
    try:
        data = fetch_folkets_lexikon(word, lang="sv")
        
        defs = []
        if data and isinstance(data, list):
            for entry in data[:2]:  # Limit to 2 entries
                word_class = entry.get("class", "word")
                translation = entry.get("translation", "")
                
                if translation:
                    short = f"[{word_class}] {translation}"
                    defs.append(short)
        
        if defs:
            return defs
    except Exception:
        pass
    
    # Enhanced fallback with common Swedish example patterns
    try:
        en_trans = trans_brief("sv", "en", word)
        if en_trans:
            # Common Swedish example patterns based on word type
            example_patterns = {
                # Nouns
                "detalj": "Varje detalj är viktig (Every detail is important)",
                "hus": "Ett stort hus (A big house)",
                "bil": "Min bil är röd (My car is red)",
                "bok": "Jag läser en bok (I'm reading a book)",
                
                # Conjunctions
                "eller": "Kaffe eller te? (Coffee or tea?)",
                "och": "Jag och du (You and I)",
                "men": "Jag vill, men jag kan inte (I want to, but I can't)",
                
                # Verbs
                "att": "Jag vill att du kommer (I want you to come)",
                "är": "Det är bra (It is good)",
                "har": "Jag har en katt (I have a cat)",
                
                # Adjectives
                "stor": "En stor hund (A big dog)",
                "liten": "Ett litet barn (A small child)",
                "bra": "Det är mycket bra (It's very good)"
            }
            
            example = example_patterns.get(word.lower())
            if example:
                return [f"[word] {en_trans} (e.g. {example})"]
            else:
                # Generic example
                return [f"[word] {en_trans} (e.g. Jag använder '{word}' i svenska (I use '{word}' in Swedish))"]
    except Exception:
        pass
    
    # Final fallback
    basic_trans = trans_brief("sv", "en", word)
    return [basic_trans] if basic_trans else ["(no translation found)"]

def english_to_swedish_with_examples(word):
    """Translate English to Swedish with examples and context"""
    
    # Try Folkets lexikon for English to Swedish
    try:
        data = fetch_folkets_lexikon(word, lang="en")
        
        translations = []
        if data and isinstance(data, list):
            for entry in data[:2]:  # Limit to 2 entries
                word_class = entry.get("class", "word")
                translation = entry.get("translation", "")
                examples = entry.get("examples", [])
                
                if translation:
                    # Use examples from API if available
                    if examples:
                        example_text = examples[0]
                        translations.append(f"[{word_class}] {translation} (e.g. {example_text})")
                    else:
                        translations.append(f"[{word_class}] {translation}")

        
        if translations:
            return translations
    except Exception:
        pass
    
    # Fallback: Use trans command with enhanced examples
    try:
        sv_trans = trans_brief("en", "sv", word)
        if sv_trans:
            # Common English to Swedish example patterns
            example_patterns = {
                "hello": f"{sv_trans} - {sv_trans}, hur mår du? (Hello, how are you?)",
                "thank": f"{sv_trans} - {sv_trans} så mycket (Thank you so much)",
                "please": f"{sv_trans} - Kan du hjälpa mig, {sv_trans}? (Can you help me, please?)",
                "yes": f"{sv_trans} - {sv_trans}, det stämmer (Yes, that's right)",
                "no": f"{sv_trans} - {sv_trans}, det gör jag inte (No, I don't)",
                "time": f"{sv_trans} - Vad är klockan? Vilken {sv_trans} är det? (What time is it?)",
                "day": f"{sv_trans} - Idag är en bra {sv_trans} (Today is a good day)",
                "night": f"{sv_trans} - God {sv_trans}! (Good night!)",
                "morning": f"{sv_trans} - God {sv_trans}! (Good morning!)",
                "work": f"{sv_trans} - Jag går till {sv_trans} (I'm going to work)"
            }
            
            example = example_patterns.get(word.lower())
            if example:
                return [f"[word] {example}"]
            else:
                # Generic Swedish example
                return [f"[word] {sv_trans} (e.g. Jag lär mig svenska ord som '{sv_trans}')"]
    except Exception:
        pass
    
    # Final fallback
    basic_trans = trans_brief("en", "sv", word)
    return [basic_trans] if basic_trans else ["(no translation found)"]

# -------------------- audio --------------------
AUDIO_CACHE_DIR = REPO_DIR / ".audio_cache"

def pick_player():
    for p in PREFERRED_PLAYERS:
        exe = which(p)
        if exe:
            return Path(exe).name
    return None

def speak_with_tts(word, lang_code):
    """Cross-platform TTS: iOS 'say' or Linux 'espeak-ng'"""
    # Try iOS 'say' command first
    if which("say"):
        voices = {
            "en": "Samantha",
            "sv": "Alva",
            "zh": "Ting-Ting"
        }
        voice = voices.get(lang_code, "Samantha")
        try:
            sh(f'say -v "{voice}" "{word}"', check=False, quiet=True)
            return
        except Exception:
            pass
    
    # Fallback to espeak-ng (Linux)
    voice = VOICE_MAP.get(lang_code, DEFAULT_VOICE)
    try:
        sh(f'espeak-ng -v {voice} "{word}"', check=False, quiet=True)
    except Exception:
        pass

def get_cached_audio(word, lang_code):
    """Check if audio file exists in cache"""
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = AUDIO_CACHE_DIR / f"{lang_code}_{word}.mp3"
    return cache_file if cache_file.exists() else None

def cache_audio(word, lang_code, audio_url):
    """Download and cache audio file"""
    try:
        AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = AUDIO_CACHE_DIR / f"{lang_code}_{word}.mp3"
        
        req = urllib.request.Request(audio_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            with cache_file.open("wb") as f:
                f.write(resp.read())
        return cache_file
    except Exception:
        return None

def play_audio(word, lang_code, audio_url=None, enable=True):
    if not enable:
        return
    
    # Check cache first
    cached_file = get_cached_audio(word, lang_code)
    if cached_file:
        audio_url = str(cached_file)
    elif audio_url:
        # Download and cache
        cached = cache_audio(word, lang_code, audio_url)
        if cached:
            audio_url = str(cached)
    
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
    speak_with_tts(word, lang_code)

# -------------------- file & git --------------------
def ensure_repo():
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if not (REPO_DIR / ".git").exists():
        sh(f'git -C "{REPO_DIR}" init', check=False)

def word_exists_in_tsv(tsv_path: Path, word: str) -> bool:
    """Check if word already exists as first column in TSV file"""
    if not tsv_path.exists():
        return False
    
    try:
        with tsv_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    first_column = line.split("\t")[0].strip()
                    if first_column.lower() == word.lower():
                        return True
    except Exception:
        pass
    return False

def append_tsv(tsv_path: Path, word: str, en_text: str, zh_text: str):
    ensure_repo()
    tsv_path.touch(exist_ok=True)
    
    # Check if word already exists
    if word_exists_in_tsv(tsv_path, word):
        return f"{word}\t{en_text}\t{zh_text}\n", True
    
    line = f"{word}\t{en_text}\t{zh_text}\n"
    with tsv_path.open("a", encoding="utf-8") as f:
        f.write(line)
    return line, False

def has_remote():
    try:
        out = sh(f'git -C "{REPO_DIR}" remote -v', check=False, capture=True, quiet=True)
        return bool(out.strip())
    except Exception:
        return False

def git_commit_push(message, enable_push=False):
    try:
        sh(f'git -C "{REPO_DIR}" add "{tsv_path.name}"', check=False, quiet=True)
        sh(f'git -C "{REPO_DIR}" commit -m "{message}"', check=False, quiet=True)
        if enable_push and has_remote():
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
                    help="Source language code (e.g., auto|en|sv|en2sv|zh|de|fr). Use 'en2sv' to translate English to Swedish. Default: auto")
    ap.add_argument("--no-audio", action="store_true", help="Disable audio playback")
    ap.add_argument("--push", action="store_true", help="Enable git push after adding word")
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
        # Try to get Swedish audio from Forvo API
        forvo_api_key = os.environ.get("FORVO_API_KEY")
        if forvo_api_key:
          try:
              forvo_url = f"https://apifree.forvo.com/action/word-pronunciations/format/json/word/{quote(term)}/language/sv/key/{forvo_api_key}"
              forvo_data = fetch_json(forvo_url)
              if forvo_data.get("items"):
                  audio_url = forvo_data["items"][0].get("pathmp3")
          except Exception:
              pass
          play_audio(term, "en", audio_url=audio_url, enable=not args.no_audio)
        else:
            play_audio(term, "en", audio_url=audio_url, enable=not args.no_audio)
    elif lang == "sv":
        sv_defs = swedish_defs_with_examples(term)
        en_text = " ; ".join(sv_defs) if sv_defs else ""
        zh_text = trans_brief("sv", "zh-CN", term) or ""
        # Try to get Swedish audio from Forvo API
        forvo_api_key = os.environ.get("FORVO_API_KEY")
        if forvo_api_key:
          try:
              forvo_url = f"https://apifree.forvo.com/action/word-pronunciations/format/json/word/{quote(term)}/language/sv/key/{forvo_api_key}"
              forvo_data = fetch_json(forvo_url)
              if forvo_data.get("items"):
                  audio_url = forvo_data["items"][0].get("pathmp3")
          except Exception:
              pass
          play_audio(term, "sv", audio_url=audio_url, enable=not args.no_audio)
        else:
            play_audio(term, "sv", audio_url=None, enable=not args.no_audio)
            
    elif lang == "en2sv":
        # Special mode: English to Swedish, save to vocab_sv.tsv with Swedish<tab>English<tab>Chinese
        sv_translations = english_to_swedish_with_examples(term)
        
        # Extract the Swedish word from the translation
        sv_word = ""
        if sv_translations:
            # Parse the translation to get the Swedish word
            first_trans = sv_translations[0]
            if "] " in first_trans:
                after_bracket = first_trans.split("] ", 1)[1]
                if " - " in after_bracket:
                    sv_word = after_bracket.split(" - ")[0].strip()
                elif " (" in after_bracket:
                    sv_word = after_bracket.split(" (")[0].strip()
                else:
                    sv_word = after_bracket.strip()
        
        if not sv_word:
            sv_word = trans_brief("en", "sv", term) or term
        
        # Use the full translation with examples as English explanation
        en_text = " ; ".join(sv_translations) if sv_translations else ""
        zh_text = trans_brief("en", "zh-CN", term) or ""
        
        # Override the term to be the Swedish word for TSV and force Swedish TSV
        term = sv_word
        tsv_path = tsv_path_for_lang("sv")
        
        # Play Swedish pronunciation
        forvo_api_key = os.environ.get("FORVO_API_KEY")
        if forvo_api_key:
          try:
              forvo_url = f"https://apifree.forvo.com/action/word-pronunciations/format/json/word/{quote(sv_word)}/language/sv/key/{forvo_api_key}"
              forvo_data = fetch_json(forvo_url)
              if forvo_data.get("items"):
                  audio_url = forvo_data["items"][0].get("pathmp3")
          except Exception:
              pass
          play_audio(sv_word, "sv", audio_url=audio_url, enable=not args.no_audio)
        else:
            play_audio(sv_word, "sv", audio_url=None, enable=not args.no_audio)
    else:
        # generic: translate to EN + ZH and speak in EN
        en_text = trans_brief(lang, "en", term) or ""
        zh_text = trans_brief(lang, "zh-CN", term) or ""
        play_audio(term, "en", audio_url=None, enable=not args.no_audio)

    line, already_exists = append_tsv(tsv_path, term, en_text, zh_text)
    
    # Only commit if word was actually added (not a duplicate)
    if not already_exists:
        git_commit_push(f"add {term}", enable_push=args.push)
        print(line, end="")
    else:
        print(line, end="")
        print("(Info: this word has already been added to tsv file.)")

    
    print(f"\nFile: {tsv_path}")
    if args.push and not has_remote() and not already_exists:
        print("\n[hint] No git remote set. Add one:\n"
              f'  git -C "{REPO_DIR}" remote add origin <YOUR_GITHUB_URL>\n'
              f'  git -C "{REPO_DIR}" branch -M main && git -C "{REPO_DIR}" push -u origin main')

if __name__ == "__main__":
    main()
