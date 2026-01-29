#!/bin/sh
# English word lookup wrapper
cd ~/Documents/anki-vocab.git
python3 lookup_to_anki_multi_lang.py --lang en "$@"
