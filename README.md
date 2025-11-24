sudo apt install translate-shell
sudo apt-get install -y mpg123
sudo apt-get update && sudo apt-get install -y ffmpeg

python3 -m venv .venv; source .venv/bin/activate 
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
