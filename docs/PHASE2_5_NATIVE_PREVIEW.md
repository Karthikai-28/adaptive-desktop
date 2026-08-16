# Adaptive Files Native Preview + Language Icons v1.4

This update makes the Inspector use Ubuntu/GNOME's own preview infrastructure
instead of maintaining a separate PDF preview implementation.

## Native preview stack

### Inline image/PDF previews

The Inspector uses `GnomeDesktopThumbnailFactory`.

That is the GNOME thumbnail dispatch/caching layer used to select installed
system thumbnailers.

On Ubuntu 22.04:

- PDF/document thumbnails are provided by the Evince thumbnailer;
- image previews use the normal thumbnailer pipeline with GdkPixbuf fallback;
- cached previews use the normal GNOME thumbnail cache.

The old direct PDF rendering path is removed.

### Full native quick preview

`gnome-sushi` is installed with this milestone so the underlying Nautilus
quick-preview behavior remains available as well.

## Source-code preview

Source/text previews now use GtkSourceView 4 when available.

This provides:

- filename/MIME language detection;
- syntax highlighting;
- line numbers;
- bracket-aware source buffer;
- read-only preview;
- horizontal and vertical scrolling.

The Inspector now displays an identity strip before the preview.

Examples:

- `main.py` -> Python source + PY icon;
- `driver.cpp` -> C++ source + C++ icon;
- `index.js` -> JavaScript source + JS icon;
- `main.ts` -> TypeScript source + TS icon;
- `lib.rs` -> Rust source + RS icon;
- `server.go` -> Go source + GO icon;
- `build.sh` -> Shell script + SH icon.

JSON, YAML, TOML, XML, HTML, CSS, SCSS, Markdown, SQL, CMake, Lua, Ruby, PHP,
Swift, Java and Kotlin also have dedicated SVG identities.

## Install

```bash
cd ~/adaptive-desktop

unzip -o ~/Downloads/adaptive-files-native-preview-v1.4.zip -d .

./scripts/phase2.5-install-native-preview.sh

/usr/bin/nautilus -q || true
pkill -x nautilus || true
sleep 2

./scripts/phase2.5-run-native-preview.sh
```

## Verify

```bash
cd ~/adaptive-desktop
./scripts/phase2.5-verify-native-preview.sh
```

For PDFs/images you should see native-thumbnail activity.

For code you should see output such as:

```text
GtkSourceView language: main.py -> Python (...)
```
