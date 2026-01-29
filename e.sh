#!/bin/sh
# English word lookup wrapper
cd ~/anki-vocab
python3 lookup_to_anki_multi_lang.py --lang en "$@"
