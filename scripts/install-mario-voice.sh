#!/usr/bin/env bash
# Install Mario's ears on this laptop: speech recognition, and what "Hey Mario" needs to hear the
# phrase in your voice. No key or cloud speech service is used; everything here is a public model
# that runs on the laptop.
#
#   .local/mario-voice/venv            faster-whisper (the words) and sherpa-onnx (speech detector, voiceprint)
#   .local/mario-voice/model           Whisper base.en
#   .local/mario-voice/wake            silero_vad.onnx (is somebody speaking), speaker.onnx (whose voice)
#
# "Hey Mario" stays off until you teach Mario your voice: Super+J, then Hey Mario under the orb.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
voice_dir="$ADAPTIVE_REPO/.local/mario-voice"
command -v parec >/dev/null || { echo 'Install pulseaudio-utils first (parec is needed).'; exit 1; }
python3 -m venv "$voice_dir/venv"
"$voice_dir/venv/bin/pip" install --disable-pip-version-check --no-cache-dir 'faster-whisper==1.2.1' 'sherpa-onnx==1.12.40'
# Explicit anonymous public model download; never read an account token or its cache.
HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HOME="$voice_dir/cache" "$voice_dir/venv/bin/python" - "$voice_dir/model" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download('Systran/faster-whisper-base.en', local_dir=sys.argv[1], token=False,
                  allow_patterns=['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*'])
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device='cpu', compute_type='int8', local_files_only=True)
PY

# "Hey Mario": two small models from the sherpa-onnx project's releases, checked against the sums
# they had when this was written.
releases='https://github.com/k2-fsa/sherpa-onnx/releases/download'
fetch() {  # fetch <file in wake/> <url> <sha256>
    local file="$voice_dir/wake/$1"
    if [ -f "$file" ] && echo "$3  $file" | sha256sum --check --status; then return; fi
    curl --fail --location --silent --show-error --max-time 600 --output "$file.part" "$2"
    echo "$3  $file.part" | sha256sum --check --status || { rm -f "$file.part"; echo "$1: the download is not the file expected."; exit 1; }
    mv "$file.part" "$file"
}
mkdir -p "$voice_dir/wake"
fetch silero_vad.onnx "$releases/asr-models/silero_vad.onnx" 9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6
# ("recongition" is how the release is spelled upstream)
fetch speaker.onnx "$releases/speaker-recongition-models/nemo_en_titanet_small.onnx" ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e
"$voice_dir/venv/bin/python" - "$voice_dir/wake" <<'PY'
import sys
import sherpa_onnx
config = sherpa_onnx.VadModelConfig()
config.silero_vad.model = sys.argv[1] + '/silero_vad.onnx'
config.sample_rate = 16000
sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=5)
sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=sys.argv[1] + '/speaker.onnx'))
PY
systemctl --user try-restart adaptive-mario-hub.service 2>/dev/null || true
echo 'Mario voice ready. Press Super+J and speak, or Talk to Mario on Home.'
echo 'For "Hey Mario": Super+J, then Hey Mario under the orb, and say the phrase four times.'
