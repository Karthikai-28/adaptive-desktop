"""Adaptive Link Presenter Engine: slide notes extraction and live synchronization."""
import asyncio
import os
import re
import time
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import machine
except ImportError:
    machine = None


def _clean_text(text):
    if not text:
        return ""
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_keypoints(notes_text, slide_title=""):
    """Break notes and slide text into punchy, scannable key talking points."""
    keypoints = []
    lines = [line.strip() for line in notes_text.split("\n") if line.strip()]
    for line in lines:
        # Check if line looks like a source citation, slide number, or metadata
        if line.lower().startswith("[source") or line.lower().startswith("source:"):
            continue
        if re.match(r"^(slide\s*\d+|page\s*\d+)$", line, re.IGNORECASE):
            continue
        # Split bullets if present
        clean_line = re.sub(r"^[-*•–—\d\.\)]+\s*", "", line).strip()
        if clean_line and len(clean_line) > 3:
            # If line has multiple sentences, split if long
            if len(clean_line) > 140:
                sentences = re.split(r"(?<=[.!?])\s+", clean_line)
                for s in sentences:
                    s = s.strip()
                    if s and len(s) > 4:
                        keypoints.append(s)
            else:
                keypoints.append(clean_line)
    if not keypoints and slide_title:
        keypoints.append(slide_title)
    return keypoints[:8]


def extract_pptx(path):
    """Extract slide titles, keypoints and speaker notes from PowerPoint (.pptx)."""
    slides = []
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return []
    try:
        with zipfile.ZipFile(path) as z:
            namelist = z.namelist()
            slide_files = sorted(
                [n for n in namelist if re.match(r"^ppt/slides/slide\d+\.xml$", n)],
                key=lambda x: int(re.search(r"\d+", x).group())
            )
            for idx, sfile in enumerate(slide_files, start=1):
                s_tree = ET.fromstring(z.read(sfile))
                title = ""
                # Try finding title shape
                for sp in s_tree.iter():
                    if sp.tag.endswith("sp"):
                        is_title = False
                        for nv in sp.iter():
                            if nv.tag.endswith("nvSpPr"):
                                for ph in nv.iter():
                                    if ph.tag.endswith("ph") and ph.attrib.get("type") in ("title", "ctrTitle"):
                                        is_title = True
                        if is_title:
                            title = "".join(sp.itertext()).strip()
                            break
                if not title:
                    non_empty = [t.strip() for t in s_tree.itertext() if t.strip()]
                    title = non_empty[0] if non_empty else f"Slide {idx}"

                # Find speaker notes
                s_basename = Path(sfile).name
                rel_file = f"ppt/slides/_rels/{s_basename}.rels"
                notes_file = None
                if rel_file in namelist:
                    try:
                        rel_tree = ET.fromstring(z.read(rel_file))
                        for rel in rel_tree.iter():
                            if "notesSlide" in rel.attrib.get("Type", ""):
                                target = rel.attrib.get("Target", "")
                                target_clean = target.replace("../", "ppt/")
                                if target_clean in namelist:
                                    notes_file = target_clean
                                    break
                    except Exception:
                        pass
                if not notes_file and f"ppt/notesSlides/notesSlide{idx}.xml" in namelist:
                    notes_file = f"ppt/notesSlides/notesSlide{idx}.xml"

                notes_paragraphs = []
                if notes_file:
                    try:
                        n_tree = ET.fromstring(z.read(notes_file))
                        for sp in n_tree.iter():
                            if sp.tag.endswith("sp"):
                                p_text = "".join(sp.itertext()).strip()
                                # Ignore pure slide number placeholders
                                if p_text and not p_text.isdigit():
                                    notes_paragraphs.append(p_text)
                    except Exception:
                        pass

                notes_text = _clean_text("\n\n".join(notes_paragraphs))
                keypoints = _extract_keypoints(notes_text, title)

                slides.append({
                    "slide_number": idx,
                    "title": title[:100],
                    "notes": notes_text,
                    "keypoints": keypoints
                })
    except Exception as e:
        return []
    return slides


def extract_odp(path):
    """Extract slide titles, keypoints and speaker notes from LibreOffice Impress (.odp)."""
    slides = []
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return []
    try:
        with zipfile.ZipFile(path) as z:
            if "content.xml" not in z.namelist():
                return []
            tree = ET.fromstring(z.read("content.xml"))
            idx = 1
            for elem in tree.iter():
                if elem.tag.endswith("page"):
                    title = elem.attrib.get("{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}name", f"Slide {idx}")
                    notes_parts = []
                    for child in elem.iter():
                        if child.tag.endswith("notes"):
                            text = "".join(child.itertext()).strip()
                            if text.startswith("<number>"):
                                text = text[8:].strip()
                            if text:
                                notes_parts.append(text)
                    notes_text = _clean_text("\n\n".join(notes_parts))
                    keypoints = _extract_keypoints(notes_text, title)
                    slides.append({
                        "slide_number": idx,
                        "title": title[:100],
                        "notes": notes_text,
                        "keypoints": keypoints
                    })
                    idx += 1
    except Exception:
        return []
    return slides


def extract_markdown(path):
    """Extract slides from Markdown / plain text notes (.md, .txt, .notes)."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []

    # Split by horizontal rule slides separator: --- or ===
    sections = re.split(r"\n(?:---|===)\n", content)
    if len(sections) == 1:
        # Try splitting by header "# Slide"
        split_headers = re.split(r"\n(?=#{1,2}\s+)", content)
        if len(split_headers) > 1:
            sections = split_headers

    slides = []
    for idx, sec in enumerate(sections, start=1):
        lines = [l.rstrip() for l in sec.strip().split("\n") if l.strip()]
        if not lines:
            continue
        title = f"Slide {idx}"
        first_line = lines[0]
        if first_line.startswith("#"):
            title = first_line.lstrip("#").strip()
            lines = lines[1:]

        notes_lines = []
        body_lines = []
        in_notes = False
        for line in lines:
            if re.match(r"^(?:notes?|speaker\s*notes?):", line, re.IGNORECASE):
                in_notes = True
                continue
            if in_notes:
                notes_lines.append(line)
            else:
                body_lines.append(line)

        notes_text = _clean_text("\n".join(notes_lines if notes_lines else body_lines))
        keypoints = _extract_keypoints(notes_text, title)
        slides.append({
            "slide_number": idx,
            "title": title[:100],
            "notes": notes_text,
            "keypoints": keypoints
        })
    return slides


def extract_presentation(path):
    path = Path(path).expanduser().resolve()
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        return extract_pptx(path)
    elif suffix == ".odp":
        return extract_odp(path)
    elif suffix in (".md", ".txt", ".notes"):
        return extract_markdown(path)
    return []


def find_active_presentation():
    """Detect open presentation file from desktop windows or active processes."""
    if machine is None:
        return None
    try:
        wins = machine.windows()
    except Exception:
        return None

    # Check open file descriptors, window titles, and process cmdlines
    for win in wins:
        title = win.get("title", "")
        pid = win.get("pid", 0)
        app = win.get("app", "")
        candidates = []

        # 1. Direct FD inspection (most reliable for LibreOffice / Impress / PDF viewers)
        if pid > 0:
            fd_dir = Path(f"/proc/{pid}/fd")
            if fd_dir.is_dir():
                try:
                    for fd_entry in fd_dir.iterdir():
                        try:
                            target = fd_entry.resolve()
                            if target.is_file() and target.suffix.lower() in (".pptx", ".odp", ".pdf", ".md", ".notes"):
                                candidates.append(target)
                        except (OSError, PermissionError):
                            pass
                except (OSError, PermissionError):
                    pass

        # 2. Process command line
        cmdline = ""
        if pid > 0:
            try:
                cmd_path = Path(f"/proc/{pid}/cmdline")
                if cmd_path.exists():
                    cmdline = cmd_path.read_bytes().decode("utf-8", "ignore").replace("\0", " ")
            except Exception:
                pass

        if cmdline:
            for part in cmdline.split():
                if part.startswith("file://"):
                    part = urllib.parse.unquote(part[7:])
                if any(part.lower().endswith(ext) for ext in (".pptx", ".odp", ".pdf", ".md", ".notes")):
                    p = Path(part).expanduser().resolve()
                    if p.is_file():
                        candidates.append(p)

        # 3. Check window title for filename
        for ext in [".pptx", ".odp", ".pdf", ".md"]:
            if ext in title.lower():
                for word in title.split():
                    if ext in word.lower():
                        clean_word = word.strip("— -:\"'[]()")
                        for base_dir in [
                            Path.home() / "mke",
                            Path.home() / "mke" / "mkeICC" / "presentations",
                            Path.home() / "presentation",
                            Path.home() / "Documents",
                            Path.home() / "Downloads" / "Presentations",
                            Path.home() / "Downloads",
                        ]:
                            match = base_dir / clean_word
                            if match.is_file():
                                candidates.append(match)

        for c in candidates:
            # Check for sidecar notes if PDF
            if c.suffix.lower() == ".pdf":
                sidecar_pptx = c.with_suffix(".pptx")
                if sidecar_pptx.is_file():
                    return str(sidecar_pptx)
                sidecar_notes = c.with_suffix(".notes")
                if sidecar_notes.is_file():
                    return str(sidecar_notes)
            return str(c)

    return None


def list_available_decks():
    """Discover presentation files in user's home directories."""
    decks = []
    seen = set()
    search_dirs = [
        Path.home() / "mke" / "mkeICC" / "presentations",
        Path.home() / "mke",
        Path.home() / "presentation",
        Path.home() / "Downloads" / "Presentations",
        Path.home() / "Documents",
        Path.home() / "Downloads" / "Documents",
        Path.home() / "Downloads",
    ]
    for d in search_dirs:
        if not d.is_dir():
            continue
        try:
            for item in d.rglob("*"):
                if item.is_file() and not item.name.startswith("."):
                    ext = item.suffix.lower()
                    if ext in (".pptx", ".odp"):
                        resolved = str(item.resolve())
                        if resolved not in seen:
                            seen.add(resolved)
                            decks.append({
                                "name": item.name,
                                "path": resolved,
                                "type": ext[1:].upper(),
                                "modified": int(item.stat().st_mtime)
                            })
                    elif ext in (".md", ".notes"):
                        try:
                            head = item.read_text(encoding="utf-8", errors="ignore")[:2000]
                            if "\n---\n" in head or "\n# Slide" in head or "slides:" in head:
                                resolved = str(item.resolve())
                                if resolved not in seen:
                                    seen.add(resolved)
                                    decks.append({
                                        "name": item.name,
                                        "path": resolved,
                                        "type": "MD",
                                        "modified": int(item.stat().st_mtime)
                                    })
                        except Exception:
                            pass
        except Exception:
            pass

    def sort_key(d):
        is_pres_folder = 1 if "presentation" in d["path"] else 0
        return (is_pres_folder, d["modified"])
    decks.sort(key=sort_key, reverse=True)
    return decks[:30]


class PresenterEngine:
    def __init__(self, input_sender=None, events_notifier=None):
        self.input_sender = input_sender
        self.events_notifier = events_notifier
        self.deck_path = ""
        self.title = ""
        self.slides = []
        self.current_slide = 1
        self.elapsed = 0
        self.running = False
        self._last_tick = 0

    @property
    def total_slides(self):
        return len(self.slides)

    def load_deck(self, path):
        path = str(Path(path).expanduser().resolve())
        slides = extract_presentation(path)
        if not slides:
            return False
        self.deck_path = path
        self.title = Path(path).stem.replace("-", " ").replace("_", " ").title()
        self.slides = slides
        self.current_slide = 1
        self._notify_change()
        return True

    def auto_detect_or_default(self):
        """Auto-detect active presentation, or load the most recent presentation deck."""
        active = find_active_presentation()
        if active:
            if active != self.deck_path:
                return self.load_deck(active)
            return True
        if not self.slides:
            decks = list_available_decks()
            if decks and self.load_deck(decks[0]["path"]):
                return True
        return bool(self.slides)

    def activate_presentation_window(self):
        """Ensure the presentation viewer window is brought to front and focused."""
        if not machine:
            return False
        try:
            wins = machine.windows()
            deck_stem = Path(self.deck_path).stem.lower() if self.deck_path else ""
            for w in wins:
                app = w.get("app", "").lower()
                title = w.get("title", "").lower()
                is_pres = (
                    any(k in app for k in ("impress", "soffice", "powerpoint", "presentation", "evince", "okular")) or
                    any(k in title for k in ("impress", "presentation", "slide show", ".pptx", ".odp")) or
                    (deck_stem and deck_stem in title)
                )
                if is_pres:
                    machine.window_action("show", w["id"])
                    return True
        except Exception:
            pass
        return False

    def current_slide_data(self):
        if not self.slides:
            return None
        idx = max(0, min(self.current_slide - 1, len(self.slides) - 1))
        return self.slides[idx]

    def next_slide_data(self):
        if not self.slides or self.current_slide >= len(self.slides):
            return None
        idx = self.current_slide
        return self.slides[idx]

    def status(self):
        self._update_timer()
        curr = self.current_slide_data()
        nxt = self.next_slide_data()
        return {
            "active": bool(self.slides),
            "deck_path": self.deck_path,
            "title": self.title or "Presentation",
            "current_slide": self.current_slide if self.slides else 0,
            "total_slides": len(self.slides),
            "slide": curr,
            "next_slide": nxt,
            "elapsed": self.elapsed,
            "running": self.running,
            "available_decks": list_available_decks()[:15]
        }

    def _update_timer(self):
        now = time.time()
        if self.running and self._last_tick > 0:
            self.elapsed += int(now - self._last_tick)
        self._last_tick = now

    def set_timer(self, running=None, reset=False):
        self._update_timer()
        if reset:
            self.elapsed = 0
            self.running = False
        elif running is not None:
            self.running = bool(running)
            self._last_tick = time.time()
        self._notify_change()

    async def next(self):
        self._update_timer()
        self.running = True
        self.activate_presentation_window()
        if self.slides and self.current_slide < len(self.slides):
            self.current_slide += 1
        if self.input_sender:
            await self.input_sender({"t": "key", "k": "Right"})
        self._notify_change()
        return self.status()

    async def prev(self):
        self._update_timer()
        self.activate_presentation_window()
        if self.slides and self.current_slide > 1:
            self.current_slide -= 1
        if self.input_sender:
            await self.input_sender({"t": "key", "k": "Left"})
        self._notify_change()
        return self.status()

    async def goto(self, slide_num):
        self._update_timer()
        self.activate_presentation_window()
        if self.slides and 1 <= slide_num <= len(self.slides):
            diff = slide_num - self.current_slide
            self.current_slide = slide_num
            if self.input_sender:
                # In Impress & PowerPoint: slide number + Return jumps directly
                for digit in str(slide_num):
                    await self.input_sender({"t": "key", "k": digit})
                    await asyncio.sleep(0.01)
                await self.input_sender({"t": "key", "k": "Return"})
        self._notify_change()
        return self.status()

    async def start(self):
        self.activate_presentation_window()
        if self.input_sender:
            await self.input_sender({"t": "key", "k": "F5"})
        self.running = True
        self._notify_change()
        return self.status()

    async def blank(self):
        self.activate_presentation_window()
        if self.input_sender:
            await self.input_sender({"t": "key", "k": "b"})
        return self.status()

    async def exit(self):
        self.activate_presentation_window()
        if self.input_sender:
            await self.input_sender({"t": "key", "k": "Escape"})
        self.running = False
        self._notify_change()
        return self.status()

    def update_notes(self, slide_num, notes):
        if self.slides and 1 <= slide_num <= len(self.slides):
            slide = self.slides[slide_num - 1]
            slide["notes"] = _clean_text(notes)
            slide["keypoints"] = _extract_keypoints(slide["notes"], slide["title"])
            self._notify_change()
            return True
        return False

    def _notify_change(self):
        if self.events_notifier:
            try:
                curr = self.current_slide_data()
                nxt = self.next_slide_data()
                self.events_notifier("presenter", self.title, keep=False, data={
                    "current_slide": self.current_slide,
                    "total_slides": len(self.slides),
                    "slide": curr,
                    "next_slide": nxt,
                    "elapsed": self.elapsed,
                    "running": self.running
                })
            except Exception:
                pass
