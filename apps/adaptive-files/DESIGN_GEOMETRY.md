# Adaptive Files Design Geometry

## Benchmark

High-end native desktop software: compact, restrained, predictable, low-noise.

The goal is to benchmark Apple-level refinement and geometry without copying Apple branding or proprietary assets.

## Geometry

| Element | Logical size |
|---|---:|
| Title bar | 38 px |
| Window controls | 28×28 px |
| Toolbar | 44 px |
| Toolbar buttons | 32×32 px |
| Sidebar expanded | 172 px |
| Sidebar compact | 56 px |
| Sidebar row | 34 px |
| Grid item | ~112×100 px |
| Folder vector | ~54 px |
| Status bar | 28 px |
| Inspector | 256 px, optional |

## Responsive behavior

- `< 980 logical px`: icon-only sidebar, search hidden, inspector hidden.
- `980–1179`: full sidebar, inspector hidden.
- `>= 1180`: full sidebar, optional inspector.

## HiDPI

All icons are SVG. GTK and GDK use logical coordinates and apply display scaling, so 4K/8K displays render the same geometry at the configured desktop scale without raster stretching.

## Visual rules

- no Ubuntu/Yaru folder assets;
- no heavy neon glow;
- no permanent card background around each file;
- blue only for focus/selection/interactive state;
- compact titlebar and controls;
- content area receives most of the available width.
