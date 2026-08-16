# Repository Documentation Map

Recommended structure:

```text
adaptive-desktop/
├── README.md
├── docs/
│   ├── PRODUCT_OVERVIEW.md
│   ├── ULTIMATE_REQUIREMENTS.md
│   ├── TECHNICAL_REQUIREMENTS.md
│   ├── DESIGN_SYSTEM.md
│   ├── IMPLEMENTATION_GUIDE.md
│   └── BACKLOG.md
├── shell/
├── services/
├── scripts/
├── config/
├── backups/
└── logs/
```

## Reading order

1. `PRODUCT_OVERVIEW.md`
2. `ULTIMATE_REQUIREMENTS.md`
3. `TECHNICAL_REQUIREMENTS.md`
4. `DESIGN_SYSTEM.md`
5. `IMPLEMENTATION_GUIDE.md`
6. `BACKLOG.md`

## Purpose

- `PRODUCT_OVERVIEW.md` — why the product exists and what it contains.
- `ULTIMATE_REQUIREMENTS.md` — non-negotiable constraints.
- `TECHNICAL_REQUIREMENTS.md` — architecture and subsystem requirements.
- `DESIGN_SYSTEM.md` — colors, spacing, typography, icons, motion, consistency.
- `IMPLEMENTATION_GUIDE.md` — safe development workflow.
- `BACKLOG.md` — current implementation status and remaining work.

## Install into the repo

After downloading:

```bash
mkdir -p ~/adaptive-desktop/docs
cp *.md ~/adaptive-desktop/docs/
```

Then:

```bash
cd ~/adaptive-desktop
git add docs
git commit -m "docs: add product, technical, design and backlog documentation"
```
