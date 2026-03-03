#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# setup.sh — Install dependencies for Coin Smith (PSBT transaction builder)
#
# Add your install commands below (e.g., npm install, pip install, cargo build).
# This script is run once before grading to set up the environment.
###############################################################################

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "Setup complete"
