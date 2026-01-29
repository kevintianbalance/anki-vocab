#!/bin/bash
# English word lookup wrapper
python3 "$(dirname "$0")/lookup_to_anki_multi_lang.py" --lang en "$@"
