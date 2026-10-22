# Adaptive Link: Full-Screen Trackpad and Ink Studio

Status: specification with an initial Android implementation. The first build provides
the full-screen multi-touch trackpad, blank pressure-aware tablet, mirrored tablet
handoff, durable local ink, undo/redo, stroke erasing, width control, and PNG/SVG
export. Selection/transforms, pan/zoom, calibrated pressure curves, protocol-v2
negotiation, recognition providers, and the extended validation matrix remain staged
work; requirements below continue to define their intended behavior.

## 1. Purpose and scope

Turn the phone's application-usable display into a desktop trackpad, a graphics
tablet, and an editable handwriting/formula surface. Support fingers and compatible
active styluses, blank and mirrored tablet views, and local recognition with optional
explicitly enabled cloud recognition. These are complementary choices, not separate
products or pairing systems.

This specification targets the existing Android app and Ubuntu 22.04, GNOME 42,
X11 desktop. Wayland, new operating-system ports, native equation-editor integrations,
and guaranteed professional-tablet hardware fidelity are outside this version.
Full-screen does not override Android system gestures, cutouts, or accessibility.
True pressure, hover, tilt, eraser, and buttons depend on the device and stylus.

Normative requirements below include both delivered and future behavior; the status
paragraph above is the implementation boundary for the initial APK.
Numeric defaults are initial implementation values to validate on physical devices;
changes require updating this specification and the corresponding test fixtures.

## 2. Existing foundations and intended changes

| Foundation | Current source | Intended use |
| --- | --- | --- |
| Trackpad screen | `apps/adaptive-link-android/app/src/main/java/com/karthi/adaptivelink/RemoteScreens.kt`, `TrackpadPage` | Replace padded touch area, separate scroll strip and always-visible controls with a full-screen surface; keyboard currently starts visible |
| Input transport | Android `Link.kt`, `InputSocket`, existing `/v1/input` | Extend existing authenticated input transport; keep optional workspace targeting |
| Input messages | Android `Protocol.kt` | Extend current relative, button, keyboard and pen messages through negotiated versioning |
| Drawing entry | Android `MobileDesktop.kt`, `native:drawing` | Currently opens the screen page; expose explicit Tablet and Ink modes |
| Desktop translator | `services/adaptive-link/inputs.py` | Reuse coordinate mapping, pointer translation and held-input accounting |
| Virtual pen | `services/adaptive-link/pen.py` | Reuse uinput position, pressure, eraser and side-button delivery; tilt is not currently implemented |
| Pen installation | `scripts/install-link-pen.sh` | Existing one-time privileged setup; no automatic elevation from the phone |

Paths abbreviated as Android filenames are in the package directory shown in the
first row. Existing screen viewing and legacy input must remain usable. This work
does not introduce another pairing, discovery, remote-control or authentication service.

## 3. Modes and full-screen experience

| Mode | Surface behavior | Primary purpose | Desktop connection |
| --- | --- | --- | --- |
| Trackpad | Relative pointer movement | Navigation, clicks, scrolling and gestures | Required for input |
| Tablet | Absolute mapping to a selected display or region | Drawing directly into desktop applications | Required for input |
| Ink | Editable local document coordinates | Writing, diagrams, formulas and recognition | Not required for drawing or saving |

On entry, show mode, connection state, selected desktop target and pressure output
status before enabling remote input. An absent or removed target must not silently
redirect input to another display. Ink remains usable offline.

Use the full application surface with the keyboard hidden and no permanent toolbar
or scroll strip. A small movable palette handle opens mode, target, brush, view,
undo/redo, keyboard and exit controls. The handle has a minimum 48 dp accessible
touch target; it consumes its own touches and cannot also draw or click. Provide
labelled accessibility actions and an explicit Exit action; Android Back exits the
surface after safely releasing input. Do not depend on a hidden gesture to escape.
Support handedness presets, movable controls, portrait and landscape, dark surfaces
and the existing system-blue accent. Save preferences independently for each mode.

Opening a palette or keyboard terminates the current contact sequence. Layout,
rotation, mode and target changes apply only after cancellation and release; a
finger still touching must lift before it can begin another sequence. Touches in
system-reserved areas are left to Android. Accessibility touch exploration must not
be interpreted as desktop input; offer explicit button controls when needed.

### Tablet views and mapping

Blank view is a low-distraction absolute tablet. Mirrored view shows the selected
desktop region behind the same input surface. Switching views must not change the
selected desktop target. Clearly distinguish the desktop cursor from local preview.

Default mapping fits the target aspect ratio inside the usable surface. The
letterboxed margins do not inject input. For target size `W × H` and surface size
`w × h`, use scale `min(w/W, h/H)` and center the active rectangle. Normalize
coordinates inside that rectangle, then translate them into the selected desktop
region. An explicit Stretch option maps the whole surface and warns about distorted
geometry. Account for desktop offsets, including negative monitor coordinates.

Freeze target identity, geometry revision, orientation and viewport transform on
stroke down. A geometry change cancels the stroke instead of remapping it midway.
Points leaving the active rectangle are clipped to its boundary; no new stroke may
start in a margin. Display removal releases input and requires target reselection.

Two-finger navigation defaults to the local mirrored viewport, not the desktop
application canvas. Blank view exposes this as a mapped-region preview. An explicit
Desktop canvas navigation toggle uses a named application action profile, only when
available. These paths are mutually exclusive and visibly labelled. In Ink, two
fingers navigate only the local document. Pan/zoom never modifies stored points.

### Ink editing

Provide immediate local ink, brush width and colour, undo/redo, stroke eraser,
selection, move/resize, pan/zoom, and named saved drafts. Stroke erasing is the first
version's baseline; partial/vector erasing is a later extension unless independently
specified and tested. Selection transforms are reversible operations, not destructive
rewrites of original samples. One completed stroke or edit is one undo unit; a new
edit after undo clears the redo branch. Palette actions have equivalent accessible
controls. Tablet undo/redo affects the desktop application only through an explicit
profile; it must not claim to own the desktop application's history.

## 4. Gesture contract

| Gesture | Trackpad | Tablet / Ink |
| --- | --- | --- |
| One-finger movement | Relative pointer | Draw when finger drawing is enabled |
| One-finger tap | Left click | Point or short stroke |
| Double tap | Double click | Two independent marks; no special action |
| Double tap, hold second touch, drag | Left-button drag | No special action |
| Two-finger tap | Right click | Undo; Tablet requires application profile |
| Two-finger movement | Horizontal/vertical scroll | Pan local canvas/view by default |
| Two-finger pinch | Zoom through explicit application profile | Zoom local canvas/view by default |
| Three-finger tap | Middle click | Redo; Tablet requires application profile |
| Three-finger horizontal swipe | Switch workspace | Disabled while drawing |
| Three-finger upward swipe | Open overview | Disabled while drawing |
| Stylus contact | Optional precise pointer operation | Draw with available pen capabilities |

Unsupported actions are visibly unavailable. Do not guess application shortcuts,
send shell commands from gesture payloads, or assume every application supports
Ctrl-based zoom. Workspace/overview actions require a negotiated desktop adapter
compatible with GNOME 42. Air pointer and touch pointer must not simultaneously
own remote injection; switching to any existing air mode ends touch ownership.

### Initial thresholds and precedence

All distances below use density-independent screen coordinates before desktop
scaling. Use the greater of 8 dp and Android's configured touch slop. Respect a
larger accessibility-configured timeout rather than forcing faster gestures.

| Rule | Initial value and behavior |
| --- | --- |
| Tap | All participating contacts lift within 220 ms; each stays within touch slop |
| Multi-finger chord | Additional contacts join within 80 ms of first down; maximum three fingers |
| Double tap | Second down within 300 ms of first up and within 24 dp of first down |
| Drag latch | Eligible second tap remains down for 180 ms or moves beyond slop; emit one button-down, release on lift/cancel |
| Scroll | Two-finger centroid exceeds slop; initial conversion 36 dp per wheel step, preserving fractional remainder |
| Pinch | Span changes by at least 8% and 8 dp; evaluate before scroll when both thresholds cross in the same sample |
| Workspace/overview swipe | Three-finger centroid travels 64 dp within 600 ms; dominant axis at least 1.5 times the other; one action per sequence |
| Ambiguous three-finger motion | No action until a qualifying swipe, otherwise cancel without a click |

Use one recognizer/state machine per surface, not independent tap, drag, drawing
and navigation handlers. States include idle, pending chord, pending tap, pointer,
drag, scroll, pinch, swipe, stroke, viewport navigation and cancelled. Once an
action claims a sequence, another action cannot claim it before all contacts lift.

Delay a single Trackpad tap until the double-tap window expires; two qualifying
taps emit exactly one double-click action, not a single click plus a double click.
Relative pointer motion may start after slop and must not also produce a click.
Offer explicit click buttons for users who prefer immediate clicking.

For finger drawing, preview immediately but buffer the first 80 ms before desktop
delivery or durable stroke commit. A qualifying chord discards that provisional
stroke and claims navigation/undo. Movement beyond slop commits drawing early;
subsequent fingers cannot reinterpret that stroke as undo or navigation. Unexpected
extra fingers cancel an active finger gesture, release remote contact, retain any
already committed partial stroke, and wait for all fingers to lift. Cancellation
cannot undo marks already delivered to a desktop application.

Stylus contact has priority over pending finger gestures. It cancels them and starts
a pen sequence; fingers are ignored during pen contact/hover, rather than used for
simultaneous navigation. Loss of hover or contact is followed by a 150 ms finger
suppression interval. Without hover support, rejection starts only once the stylus
is detected. A stylus-only option prevents finger drawing altogether. Palm rejection
is best effort and must not be advertised as hardware-independent.

## 5. Pressure and stroke fidelity

Detect pressure, hover, eraser, side buttons and tilt separately for each input
device/tool. Capability reporting alone is insufficient to label pressure genuine:
run a light-to-firm calibration preview. Initially require at least eight distinct
stable readings spanning 10% of the reported range across repeated passes; this is
a usability heuristic, not a force measurement. Constant/noisy devices use fallback.
Let the user override calibration or recalibrate after changing the stylus.

Expose three clearly named policies: Hardware pressure, Constant width, and
Simulated pressure from speed. Fingers default to constant width unless calibrated
hardware proves useful; contact area is never labelled measured force. Speed-based
simulation uses document-space speed so viewport zoom does not change the width.
Manual brush width is always available. Unsupported pressure output displays
Mouse fallback — no desktop pressure, even when local ink shows varying width.

For hardware pressure, retain raw values and calibration metadata. Normalize the
calibrated interval to `[0,1]`; provide linear, soft and firm curves using exponent
values 1, 0.6 and 1.6, with a preview. Initial activation threshold is 0.02 and release
threshold 0.01 to reduce chatter; physical lift/cancel always releases regardless of
pressure. Curves and thresholds are adjustable and snapshotted per stroke. A zero
pressure contact must not become a permanently held pen.

Reuse the uinput backend after `scripts/install-link-pen.sh` has been explicitly
installed by the operator. Failure to create/write the device releases its state,
reports the failure, and offers mouse fallback for the next stroke; never switch
backends midway through a stroke. Eraser and button transitions must be released
alongside contact. Advertise tilt only after Android capture, protocol, backend and
application validation all support it; omit unsupported axes instead of inventing
zero readings. Pressure-sensitive brush configuration remains the desktop app's job.

Store raw observed points, timestamps, pressure and tool metadata. Apply configurable
smoothing as a reversible render/delivery policy. Preserve endpoints and sharp
corners in fidelity tests. Predicted points exist only in the transient local preview;
never save, recognize, export or transmit them as observed samples. Local preview
does not imply that the desktop has rendered the same stroke.

## 6. Recognition and output

Recognize selected strokes or the current page only after a Text or Formula action.
Keep the editable ink and show an editable result preview, with a rendered formula
alongside LaTeX source. Copy, Insert and Export are separate explicit actions.
Recognition never automatically replaces strokes or types into the focused window.

Text recognition covers ordinary and multiline writing. The formula acceptance
corpus includes fractions, roots, sub/superscripts, Greek symbols, integrals and
matrices, including combinations and ambiguous symbols. Incorrect output must be
correctable before insertion. Plain text and LaTeX are insertion formats; native
equation objects require a separately documented application integration.

Export the selected content or full page as PNG or SVG with chosen bounds, background
and resolution. SVG represents variable-width ink with outlines where required to
preserve appearance. Exports exclude selection handles and predictions. They are
flattened deliverables; the native draft remains the editable source. Explicit
desktop insertion checks the target/focus and permissions, shows the payload, and
does not replay after reconnect. Respect existing text-size limits; oversized output
offers copy/export rather than silently truncating or issuing partial insertion.

### Providers and feasibility gate

Use a common provider contract: capabilities, language/task support, locality,
model/version, availability, input limits, submit, cancel and result. Local means
on the phone or paired desktop, never an internet endpoint; show which is used.
Phone-offline recognition is available only if a suitable phone model is installed.
Drawing, saving, editing and export remain available without any recognition engine.

Before selecting engines, evaluate candidates on a fixed, versioned sample corpus
with a separate tuning set. Record model and dependency licenses, redistribution
rights, download/installed sizes, language coverage, CPU/GPU/RAM requirements, cold
start and warm p50/p95 latency, text character/word error rates, formula exact-match
and structural accuracy, and user correction time. Include device and OS versions.
Benchmark at least 100 text and 100 formula samples spanning the categories above
and multiple writers. Set release accuracy/latency thresholds from that evaluation
and record them before implementing the provider; no engine or accuracy promise is
made here. Recognition delivery is gated on license and measured-quality approval.

Local processing is the default. Optional cloud use requires explicit enablement
and a per-job confirmation showing provider, selected content and disclosed retention
policy. Upload only the selected strokes or a crop derived from them, never unrelated
page data or a desktop screenshot. No silent cloud fallback. Credentials are configured
separately by the operator, not embedded in drafts. Cancellation stops future work
where possible but cannot retract an upload already sent; explain that in the UI.

Each job captures request ID, document ID, revision, selection snapshot and provider
version. Editing the draft makes its old result stale: retain it as a labelled preview
if useful but prohibit automatic application. Cancelled or superseded jobs cannot
update the current preview. Provider errors return to an editable draft with retry
and export, without blocking the input or rendering threads. Formula rendering must
disable external resources and command execution and enforce complexity limits.

## 7. Input architecture and compatibility

### Negotiation and messages

Negotiate an additive input protocol version over the existing paired transport.
The handshake returns supported gesture actions, pen axes, pressure backend status,
display/region geometry and revision, recognition providers and limits, and ownership
status. The client sends its tool capabilities separately from desktop output
capabilities. Effective capability is their intersection, not a device marketing name.

Legacy clients retain their existing message format and behavior. New clients facing
an old server explicitly select legacy Trackpad behavior and disable unsupported
features; they must not send new envelopes and hope they work. Legacy remote input
still participates in server-side ownership and cleanup for safety.

Proposed version-2 envelope fields:

| Field | Contract |
| --- | --- |
| `v`, `session_id`, `seq` | Negotiated version, server-issued session identity, strictly increasing sequence number |
| `time_us` | Client monotonic capture time, useful for intervals; not assumed synchronized with server time |
| `mode`, `type` | Validated mode and allowlisted event kind, not an executable shortcut or command |
| `target_id`, `geometry_revision` | Server-validated target mapping, frozen for each stroke |
| `stroke_id`, `phase` | Unique within session; begin/update/end/cancel for contacts |
| `samples` | Ordered observed points with sample time, normalized x/y, pressure if supported, tool and negotiated axes |
| `dx`, `dy`, `buttons` | Event-specific relative movement or explicit transition fields; never ambiguous with absolute points |

Local Ink stores document coordinates, not display-normalized coordinates. Only
desktop-bound Tablet points use normalized target coordinates. Validate finite
numbers, bounds, enums, message sizes and permissions before injection. Reject
updates without a begin, duplicate begins, stale geometry, unknown sessions and
out-of-order messages. End/cancel is idempotent. A sequence gap cancels the active
gesture and requests a fresh sequence rather than inventing missing transitions.
Acknowledgements distinguish accepted input from desktop rendering; they are not
proof of visible application response.

### Delivery, buffering and ownership

Use an ordered reliable input channel independent of video and recognition. Initial
limits: 64 KiB per message, 128 samples per ink batch, and a client queue of 256
messages or 250 ms of captured input, whichever is reached first. Flush ink at most
every 8 ms while active; flush begin/end/cancel immediately. Tune with measurements.

Combine only adjacent relative-motion events with identical session/target/settings;
preserve total displacement and fractional remainder, splitting large deltas to fit
the current translator's bounds. Never coalesce across button/contact transitions.
Batch ink without dropping observed samples, changing their order, or losing endpoints.
If bounded capacity is exceeded, cancel and release the remote gesture, discard its
remaining queued updates and show congestion; preserve the local draft. Never build
an unbounded backlog or replay an old stroke later. Reserve control capacity for
release/cancel; server expiry is the fallback when delivery is impossible.

Grant one remote injection owner at a time across phone input surfaces and clients.
This is exclusive remote ownership, not a lockout of the physical keyboard/mouse.
A second client receives a busy response; explicit takeover first releases the old
owner's state. Apply paired-device permissions to each operation, not just the initial
handshake. Input sessions start only while the phone is foreground and authenticated.

Track held keys, pointer buttons, pen contact, proximity, eraser and side buttons in
one ownership ledger. On disconnect, permission removal, unpairing, phone background,
screen lock, target loss, mode change or session expiry, release all owned state and
discard queued input. Use 500 ms heartbeats and a 2 s server lease as initial failure
bounds; immediate lifecycle notifications release sooner. Reconnect creates a new
session with no stale replay and requires all contacts up before new input. Daemon
shutdown releases input; recovery after a crash must clear any persisted injection
state before accepting ownership. Physical input must not be indiscriminately released.

## 8. Draft storage, privacy and recovery

Use private app storage with a versioned native document containing document ID,
revision, canvas units/bounds, strokes with immutable observed samples, tool and brush
metadata, nondestructive transforms, edit history/checkpoint and optional recognition
results labelled by revision/provider. Do not store credentials or mirror frames.
Unknown newer formats open read-only or fail safely without overwriting the file.

Journal completed edits, checkpoint at stroke completion and after at most one second
of idle editing, and atomically replace snapshots using a same-directory temporary
file and durable flush. Keep the last valid checkpoint for crash recovery. On partial
write or disk-full, retain the previous good version and show unsaved status; never
claim a successful save. In-progress stroke recovery may lose at most the uncheckpointed
tail and must not fabricate an end point. Drafts survive disconnection and app restart.

Bound document/sample and history sizes with explicit warnings and new-page/export
options, not silent point deletion. Initial safety ceiling is one million observed
samples per document; benchmark memory use before finalizing it. Native draft sharing
and backup are opt-in, separate from existing Android backup restrictions. Deletion
requires a deliberate user action and a recoverable trash period where practical.

Reuse paired-device permissions and encrypted local/USB/away transports. New recognition
and export operations require their own explicit user actions and least-privilege
authorization. No handwriting, recognized text, screenshots or credentials in routine
logs; log request IDs, sizes, timing and error codes. Validate document imports and
export paths; SVG export must not embed scripts or external references.

## 9. Delivery phases

| Phase | Entry and dependencies | Exit criteria |
| --- | --- | --- |
| 1. Full-screen Trackpad | Baseline input tests recorded; gesture and ownership contracts reviewed | Full-screen controls, recognizer, click/drag/scroll and supported desktop gestures work; interruption/lease tests pass; legacy behavior preserved |
| 2. Tablet and pressure | Phase 1 release/ownership safeguards; physical test phone and pressure stylus available | Blank/mirror views, aspect mapping, calibration, fallback and tool transitions validated; setup requirements visible; no mid-stroke remapping |
| 3. Editable Ink | Shared capture/recognizer stable; document schema reviewed | Offline drawing, editing, undo/redo, save/recovery and raw/predicted separation pass; disconnect cannot lose a saved draft |
| 4. Recognition and export | Phase 3; provider feasibility and licensing gate passed | Text/formula previews, explicit insertion, PNG/SVG export, local provider and optional consented cloud path validated; stale/cancel tests pass |
| 5. Performance and compatibility | Earlier functional gates complete | Physical-device matrix and p95 latency results recorded; congestion, long-session, mixed-display and old-client tests pass; unresolved limitations documented |

Do not mark recognition complete merely because a provider API exists. If no local
engine passes the feasibility gate, ship earlier phases with recognition clearly
unavailable and report the gap. Each phase requires focused automated tests plus
physical checks for the hardware-dependent claims. Existing repo verification scripts
are starting points, not substitutes for touch/stylus and desktop-app testing.

## 10. Requirements-to-test matrix

| ID | Requirement and test method | Acceptance evidence |
| --- | --- | --- |
| UX-01 | Instrument full-screen entry, palette, keyboard, handedness, rotation and accessible exit | Usable surface fills available region; controls remain reachable; palette/system touches never inject |
| G-01 | Deterministic event traces at every threshold boundary, double taps and drag latch | Exactly one recognizer winner; exact expected button/action sequence; no extra click |
| G-02 | Extra fingers before/after chord window, fourth finger, interrupted gestures, 100 repeated mode switches | No reinterpretation after commitment; cancellation waits for lift; no residual held state |
| G-03 | Physical palm contact, stylus hover/contact/lift, eraser flip, finger-to-pen transitions, stylus-only mode | No finger ink while stylus owns sequence; limitations recorded for non-hover hardware |
| MAP-01 | Grid/circles on portrait/landscape, aspect-fit/stretch, region offsets and mixed-resolution monitors | Default circles stay round; transformed test coordinates within one target pixel after rounding |
| MAP-02 | Rotate, resize, change/remove target or disconnect mirrored video during a stroke | Input releases on invalid mapping; no jump to another target; view-only failure visibly identified |
| SAFE-01 | Disconnect, kill app, lock phone/desktop, revoke permission, expire lease, kill/restart daemon | No stuck owned keys/buttons/contact/proximity; immediate cleanup when notified, otherwise within lease plus measured scheduling tolerance |
| SAFE-02 | Duplicate/reordered/gapped messages, malformed numbers, oversized batches, two competing clients | Invalid input never injected; one remote owner; cancellation and recovery deterministic |
| NET-01 | Congestion, delayed release, saturated video, queue overflow and reconnect | Bounded memory; preserved relative sums; no stale replay; local drafts retained |
| PEN-01 | Constant-pressure touch, calibrated stylus, simulated pressure, absent/failed uinput | Correct labels and curves; mouse fallback never claims pressure; no mid-stroke backend switch |
| PEN-02 | Pen button press/lift/cancel, eraser transitions and negotiated/unsupported tilt | All state releases; unsupported axes absent; application receives supported tool semantics |
| DRAW-01 | Circles, straight lines, fine lettering, diagrams and formulas in Ink and desktop apps | Endpoint/corner and width fidelity compared to raw capture; no predictions in saved/exported data |
| REC-01 | Fixed text/formula corpus including every category in section 6 | Versioned accuracy, latency and correction-time report meets thresholds approved at feasibility gate |
| REC-02 | Edit/cancel/supersede jobs, provider failure, offline use and cloud consent refusal | No stale application or automatic typing/upload; local draft remains editable; correct provider/locality shown |
| STORE-01 | Undo/redo branches, selection transforms, process kill during save, corrupt checkpoint and disk-full | Last good draft recovers; edits reversible; save failures visible; originals preserved |
| EXPORT-01 | PNG/SVG reopen and compare at multiple zooms; multiline text/LaTeX insert and oversized result | Bounds/background/width fidelity; explicit destination; no truncation, script execution or duplicate insertion |
| COMPAT-01 | Old client/new server and new client/old server; USB, LAN and away paths | Existing screen/input behavior retained; unsupported features disabled explicitly; permissions enforced |
| PERF-01 | Measure local preview and visible desktop response under idle and load | p95 targets below, with device/transport/method and failures recorded |

Use at least one ordinary finger phone, one verified pressure-capable stylus device,
and a no-uinput desktop configuration. Test drawing in configured versions of Krita,
GIMP and Xournal++ where installed; record brush settings and pressure support rather
than assuming parity. Missing physical devices/applications leave the corresponding
acceptance row unverified, not passed. Add deterministic recognizer/protocol/storage
tests to the appropriate Android and desktop suites, then run the existing quick
checks and Android build without changing the live desktop session.

### Latency measurement and release report

Provisional goals are under 50 ms p95 from touch capture to visible local Ink feedback,
and under 80 ms p95 from touch capture to visible desktop response on a stable local
connection. Measure with high-frame-rate video showing the input and display together,
or instrumented capture/presentation timestamps with documented clock synchronization
and uncertainty. Socket send/ack time alone does not measure visible latency.

Record phone/stylus/display refresh rate, desktop hardware, OS/app versions, transport,
resolution, smoothing, sample rate, workload and measurement method. Collect at least
200 interactions per configuration after warm-up; report p50, p95, worst case and
sample count. Report cold start separately and test sustained drawing for 30 minutes
for thermal, memory and battery effects. USB and LAN results are separate; away-network
performance has its own network conditions and is not represented as a LAN guarantee.

## 11. Decisions still gated before application implementation

The user-facing scope and gesture defaults above are fixed starting requirements.
Provider/model choice, final recognition accuracy thresholds, target-device pressure
calibration tuning, supported application action profiles, and final resource limits
require the stated feasibility and physical-device checks. Record approved values in
this document before claiming their delivery phase complete. No application code,
service installation, privileged setup or live input injection is authorized by this
initial implementation alone.
