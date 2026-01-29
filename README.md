

# Optional
# python3 -m venv .venv; source .venv/bin/activate 
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Install on iOS

Yes, here are the easiest ways to deploy this Python script to iPad:

1. a-Shell (Recommended - Easiest)
Free app that provides a Unix shell on iOS:

Install a-Shell from App Store

Install Python packages: pip install langdetect

[SKIP] Install translate-shell: pkg install translate-shell

Clone your repo: git clone <your-repo-url>
# Simply use HTTPS URL
git clone https://github.com/username/anki-vocab.git
cd anki-vocab

Run: python3 lookup_to_anki_multi_lang.py --lang sv word

# Use on iOS
export FORVO_API_KEY=c989ec43fa012d74fa8580de97408903
export PATH="$HOME/anki-vocab.git:$PATH"

e.sh phonetic
s.sh detalj
v.sh machine
