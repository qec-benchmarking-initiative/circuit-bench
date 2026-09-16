#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

python scripts/write-build-metadata.py
python -m pip install --disable-pip-version-check -r requirements.txt
python manage.py collectstatic --noinput
