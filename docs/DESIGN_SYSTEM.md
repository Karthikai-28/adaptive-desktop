# Design System

## Design direction

Karthi's OS should feel:

- calm;
- spatial;
- precise;
- modern;
- premium without copying another operating system;
- dark by default;
- information-rich only when context requires it.

Depth indicates hierarchy. Motion explains state.

## Core palette

### Foundation

| Token | Hex | Purpose |
|---|---:|---|
| `bg.canvas` | `#08111B` | Primary background |
| `bg.deep` | `#07101A` | Deep canvas |
| `surface.1` | `#111A28` | Cards and controls |
| `surface.2` | `#162233` | Elevated/selected surfaces |
| `divider` | `#30425C` | Borders/separators |
| `text.primary` | `#F2F6EF` | Main text |
| `text.muted` | `#96A4B8` | Secondary text |

### Accent

| Token | Hex | Purpose |
|---|---:|---|
| `accent.primary` | `#78A9FF` | Main active/selected/action color |
| `accent.cyan` | `#66E0FF` | Secondary informational accent |
| `accent.violet` | `#9A8BFF` | Tertiary/context accent |

### State

| Token | Hex | Purpose |
|---|---:|---|
| `state.warning` | `#F3C96B` | Warning |
| `state.danger` | `#FF7A90` | Destructive/error |
| `state.success` | `#65D9B5` | Success/healthy |

## Color rules

### Primary blue

Use `#78A9FF` for:

- current navigation item;
- selected controls;
- focused input borders;
- primary actions;
- active project indicators;
- important interaction highlights.

Do not use it as a large default background.

### Cyan

Use for supporting information such as metrics, metadata, and secondary active states.

### Violet

Use sparingly for alternate context or data categories.

### Danger

Reserve for destructive actions and true errors.

## Surface hierarchy

```text
Canvas          #08111B
Shell chrome    rgba(8,17,27,~0.97)
Panel/card      #111A28
Elevated        #162233
Divider         #30425C
```

Avoid introducing arbitrary dark grays.

## Transparency

Use transparency for temporary overlays and shell chrome.

Prefer more opaque surfaces for settings, file lists, and content-heavy panels.

## Radius system

| Size | Value | Usage |
|---|---:|---|
| Small | 8 px | chips/small controls |
| Medium | 12–14 px | buttons/cards |
| Large | 18–22 px | floating overlays |
| XL | 28 px | very large presentation surfaces |

### Dock rule

The dock/rail must not look like a floating rounded phone widget.

When docked:

- flush to screen edge;
- square/structural outer shell;
- right divider visible;
- rounded states only on individual buttons.

## Spacing system

Use an 8 px rhythm where practical:

```text
4
8
12
16
20
24
32
40
48
```

Shell targets:

- rail width: ~72 px;
- rail icon: 18–22 px;
- rail item: 44–48 px;
- overlay offset from rail: 16–24 px.

## Typography

### Display / section title
22–34 px, bold.

### UI title
13–16 px, bold/semibold.

### Body
11–14 px, regular.

### Metadata
10–12 px, muted.

Uppercase is acceptable for compact shell identity/context, but not for all application UI.

## Icon system

Goal: clean, thin, recognizable, consistent.

Current implementation may use GNOME symbolic icons.

Future custom icons should:

- use one visual family;
- avoid mixing filled and outline sets;
- remain readable at 16–22 px;
- avoid proprietary Apple/macOS assets;
- keep stable meanings for Home, Projects, Workspaces, Search/Command, System Center.

## Motion

Motion must explain origin, destination, activation, or state change.

Recommended durations:

```text
Fast feedback:      100–140 ms
Panel/overlay:      160–220 ms
Workspace movement: 180–260 ms
Large state change: 220–320 ms
```

Avoid decorative continuous animation.

Reduced-motion mode must simplify spatial transitions.

## Consistency

Shell, Projects, Workspaces, Command, Files, Settings, System Center, Notifications, and Lock/Session must share:

- color tokens;
- spacing rhythm;
- radii;
- icon philosophy;
- typography;
- focus/hover/active states;
- terminology.

## Accessibility

Required:

- visible focus states;
- keyboard navigation;
- sufficient contrast;
- no meaning by color alone;
- reduced motion;
- high contrast;
- scalable text;
- adequate pointer targets;
- explicit destructive confirmation.

## Anti-patterns

Do not:

- overuse neon;
- create sci-fi HUD decoration;
- use random gradients;
- make every surface translucent;
- crowd the idle desktop with telemetry;
- hardcode personal projects into generic UI;
- use Iron Man/Jarvis/Stark branding;
- copy macOS assets or branding;
- replace functionality with fake visual controls.
