#!/bin/sh
# English to Swedish translation wrapper
cd ~/Documents/anki-vocab.git
python3 lookup_to_anki_multi_lang.py --lang en2sv "$@"
