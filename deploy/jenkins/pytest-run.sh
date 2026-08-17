#!/usr/bin/env sh
set -eu

python -m pip install --disable-pip-version-check -r requirements.txt
python -m pip check
pytest --cov=backend --cov-report=xml:coverage.xml
