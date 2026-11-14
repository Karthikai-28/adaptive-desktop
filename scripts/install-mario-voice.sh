#!/usr/bin/env bash
# Install local speech recognition for Mario. No key or cloud speech service is used.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
voice_dir="$ADAPTIVE_REPO/.local/mario-voice"
command -v parec >/dev/null || { echo 'Install pulseaudio-utils first (parec is needed).'; exit 1; }
python3 -m venv "$voice_dir/venv"
"$voice_dir/venv/bin/pip" install --disable-pip-version-check --no-cache-dir 'faster-whisper==1.2.1'
# Explicit anonymous public model download; never read an account token or its cache.
HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HOME="$voice_dir/cache" "$voice_dir/venv/bin/python" - "$voice_dir/model" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download('Systran/faster-whisper-base.en', local_dir=sys.argv[1], token=False,
                  allow_patterns=['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*'])
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device='cpu', compute_type='int8', local_files_only=True)
print('Mario voice ready. Press Talk to Mario on Home or in the Super+J panel.')
PY
