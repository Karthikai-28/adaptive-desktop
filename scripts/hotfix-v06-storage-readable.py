#!/usr/bin/env python3
from pathlib import Path
import shutil

path = Path.home() / "adaptive-desktop/apps/adaptive-files/style.css"

if not path.exists():
    raise SystemExit(f"Not found: {path}")

src = path.read_text()
backup = path.with_name("style.css.before-v07-storage-hotfix")

if not backup.exists():
    shutil.copy2(path, backup)

append = r"""

/* =========================================================
   Temporary v0.7 readability bridge
   Production styling moves into the Nautilus-based fork.
   ========================================================= */

.preview-panel {
    min-width: 304px;
}

.preview-header {
    min-height: 52px;
    padding: 7px 12px;
}

.preview-title {
    font-size: 14px;
}

.preview-subtitle {
    font-size: 10px;
}

.preview-section-label {
    font-size: 10px;
    margin-top: 8px;
}

.preview-meta-key {
    font-size: 11px;
}

.preview-meta-value {
    font-size: 11px;
}

.preview-large-caption {
    font-size: 11px;
}

.storage-percent {
    font-size: 25px;
}

.storage-percent-label {
    font-size: 10px;
}

.storage-feature-value {
    font-size: 19px;
}

.storage-feature-value-small {
    font-size: 14px;
}

.storage-feature-label {
    font-size: 10px;
}

.storage-capacity-label {
    font-size: 10px;
}

.storage-overview-card,
.storage-capacity-card,
.storage-detail-card {
    padding: 12px;
}
"""

if "Temporary v0.7 readability bridge" not in src:
    path.write_text(src.rstrip() + append + "\n")

print(f"Patched: {path}")
print(f"Backup:  {backup}")
