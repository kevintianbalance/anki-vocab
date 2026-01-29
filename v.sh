#!/bin/bash
# English to Swedish translation wrapper
python3 "$(dirname "$0")/lookup_to_anki_multi_lang.py" --lang en2sv "$@"
