@echo off
cd /d C:\path\to\garmin-weight-sync
python src/main.py --config users.json --sync >> data\sync.log 2>&1
