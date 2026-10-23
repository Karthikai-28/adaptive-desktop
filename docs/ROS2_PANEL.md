# ROS 2 panel

A top-bar dropdown, just left of the Network button, for the ROS 2 graph this
computer can see and the tools used with it. The command palette's `ros` mode
does the panel's actions from the keyboard.

## What it shows

- **Header**: distro, domain, node count, "recording" while a bag records.
  A persistent Dynamic Island activity remains until recording stops, including
  when the panel is closed. It opens a recording card linking back to ROS 2.
  The top-bar icon turns red while the panel records a bag, orange while
  `/diagnostics` reports an error.
- **Search** (under the header): narrows every section to the items whose
  name, namespace or type matches (not the names an item carries, or every
  node would match `/rosout`); the section headings say "3 of 40", and
  Nodes, Topics, Services and Actions open by themselves while a search is
  typed (folding one keeps it folded for that search). Escape clears it.
- **Setup**: domain ID (click to change), discovery range (localhost only or
  the LAN), middleware, and the workspace overlay (searchable dropdown with None, discovered workspaces,
  and Choose path for a custom built colcon workspace). By default
  these follow the login shell's startup files (`~/.zshenv`, `~/.zprofile`,
  `~/.zshrc` for Zsh; `~/.profile`, `~/.bash_profile`, `~/.bashrc` for bash):
  `export ROS_DOMAIN_ID=…`, `ROS_LOCALHOST_ONLY`, `RMW_IMPLEMENTATION`, and
  the workspace whose `install/(local_)setup.*` they source, also through a
  variable (`x="$HOME/…/local_setup.zsh"; [[ -r "$x" ]] && source "$x"`). So
  the panel sees the same graph as your terminals. A change made in the panel
  is saved in `~/.config/adaptive-desktop/ros2.json` and wins over them.
  - If ROS processes started outside the panel run on another domain,
    discovery range or middleware, the card says so and **Watch them**
    switches to it.
  - The workspace list holds built workspaces (`install/setup.bash`), ones
    not built yet (packages under `src/`, so they can be chosen and built),
    and projects inside a workspace that build into their own tree
    (`src/<project>/.build/<distro>`, named after the project).
  - **Packages**: with a workspace chosen, every package from its source
    manifests is a row: built or "not built yet", how many executables, and
    its own **Build** (`--packages-select`; with **With dependencies** ticked,
    `--packages-up-to`). A click on a package narrows the launch files and
    executable nodes below to it (Show all undoes it); the running graph
    stays complete because DDS does not expose package identity. Without a
    workspace the panel says to choose one.
    Launch, config, world and executable choices use bounded, searchable dropdowns.
    Workspace launch discovery includes every matching file, rather than twelve recent files.
  - **colcon build**: **Build all** builds every package, run the way the
    workspace was built last: a build tree like `proj/.build/humble` keeps
    its sources elsewhere, and its last command line in
    `log/latest_build/logger_all.log` gives the base paths, build and install
    base, `--symlink-install` and `--cmake-args`. While it runs the row
    shows "3 of 5 packages done", failed packages and the last output line,
    with Log and Stop. The distro's environment is used, not the overlay
    being built.
  - **Environment checks** under the workspace say what would make a build or
    a launch fail before it does: a middleware not installed for the distro,
    no source folder, no colcon, packages not built yet, packages the last
    build failed (colcon's `events.log`), and a package changed since then.
  - **Setups**: the current domain, discovery, middleware and workspace saved
    under a name (a robot, a bench); a dropdown applies one, the one in use is
    lit.
  - **Robot profile**: a setup plus the package, the favourites and the saved
    launches, saved under a name (**Save…**). Use profile applies one, then
    puts its favourites back and adds its saved launches (one of the same name
    is replaced). The profile matching the setup now is named on the row as
    in use, with **Forget**.
  - When Project Context's active project is, holds (`proj/.build/<distro>`)
    or sits in a colcon workspace the panel does not use, the card offers
    **Use it** or **Always follow** (the workspace then follows the active
    project, "from the active project").
- **New package** (top of Launch, **Create…**; also **＋ New** on the
  Packages heading and `ros new` in the palette): `ros2 pkg create` as a
  four-step dialog, the way an IDE starts a project. Packages are only ever
  made under `~/ros2_ws/src` (or a folder there that already holds packages,
  like `src/<project>/packages`); the helper refuses anything else, a symlink
  out included.
  1. **Template**: C++ node, Python node, C++ component (composable, also runs
     alone), C++ library, Interfaces (starter `msg/Status.msg`,
     `srv/Command.srv`, `action/Task.action`), Launch & config (`launch/`,
     `config/params.yaml`, installed), empty CMake or Python package. A second
     click on the chosen card moves on.
  2. **Configure**: name (checked as it is typed: lowercase, digits and single
     underscores; taken in `~/ros2_ws`; a Python keyword; a name ROS already
     has only warns), node or library name (follows the package name until
     edited), location, description, maintainer and licence. The last
     maintainer, licence, location and template are remembered in
     `~/.config/adaptive-desktop/ros-new-package.json`; the git identity is
     never read (its global config can be a work account).
  3. **Dependencies**: two columns. Left, everything that can be added:
     Recommended for the template, the curated areas (Core, Messages, TF &
     robot model, Perception, Navigation, Control, Manipulation, Simulation,
     Visualization, Logging & tools, Testing; packages not installed are
     listed and marked), This workspace, and every other installed package; a
     search spans them all and Enter adds the first match; a name not listed
     can be added as typed. Right, what the package will depend on; the
     template's own are fixed.
  4. **Review**: the facts, the files it will hold, the `ros2 pkg create`
     line, and what happens after: **Build it now** (colcon, this package
     only, in `~/ros2_ws`, shown in the run manager), **Use ~/ros2_ws in the
     ROS 2 panel**, **Open the folder**.
  Then a result page, with **Install with rosdep** when a dependency is not
  installed (a terminal on `rosdep install --from-paths <pkg> --ignore-src`).
  For CMake templates a dependency without a CMake config (`launch_ros`) is
  an `<exec_depend>` and stays out of `find_package`, so the build does not
  fail on it; a C++ or Python node publishes `~/status` when `std_msgs` is
  chosen.
- **Launch**: RViz2 (and recent `.rviz` configs), Gazebo (and the worlds in
  your workspaces), rqt, rqt_graph, a terminal with the same ROS setup.
  Terminal uses the KTERM modern Zsh profile, sources the user's `.zshrc`,
  then applies the selected distro and workspace `setup.zsh` files and panel
  domain/middleware settings. A running app shows Show (its window), and when
  the panel started it Log and Stop. **Rescan files** walks the folders again
  (the search is kept five minutes).
  - **Launch files**: saved launches start at a click; a launch file from a
    workspace's `src` first shows a form of the arguments it declares
    (`ros2 launch … --show-args`): each with its description and default,
    a dropdown when it declares choices, and "required" when it has no default
    (Launch holds back until it is given). Only values that differ from a
    default are passed and saved. A file whose arguments cannot be read falls
    back to a `name:=value …` entry.
  - **Running from here** (the run manager): everything the panel started, in
    one list, with how long it has run, **Log**, **Pause**/**Resume** (builds,
    launches and nodes, by SIGSTOP/SIGCONT), **Restart** and **Stop**. Log
    opens the run's last 60 lines in the panel, filtered by text and by
    severity (warnings, errors), following the run while it is open.
  - A run the panel started that exited by itself with an error stays listed
    for a day with its exit code, **Log** and **Restart**.
  - **Rosbag**: Record records the topics the graph shows (narrowed by the
    search) into `~/.local/share/adaptive-desktop/rosbags`, after a confirming
    click, or the topics ticked under **Topics**; while it runs the row shows
    its size and length. Recent bags are listed with length, messages, topics
    and size, with Play… (speed 0.1 to 10, loop, publish `/clock` for
    simulated time) and Folder. Playback pauses and resumes through rosbag2's
    own `/rosbag2_player/pause` service; recording pauses only from Iron on
    (Humble's recorder has no pause service, so the button is not offered).
    One bag runs at a time.
  - **Bags from anywhere**: **Open…** on the Rosbag row takes a path (a bag
    folder, its `metadata.yaml`, one of its `.db3`/`.mcap` files, or a lone
    `.db3`/`.mcap`) or **Choose a file…** (a zenity file chooser; the
    dropdown closes for it and comes back). A file inside a bag folder plays
    the whole folder (a split bag has several files); a lone file plays with
    its storage named (`-s sqlite3`/`-s mcap`). Bags under `~/Downloads`
    (four levels) and the home folder (two) are listed by themselves ("in
    ~/Downloads/…"); opened ones stay listed ("opened from …", with
    **Forget**; kept in `~/.config/adaptive-desktop/ros-bags.json`).
  - **The play form** first says what the bag holds and which topics will
    not play: a topic whose message package is not installed (in the distro
    or the panel's workspace) is skipped by `ros2 bag play` with a warning,
    so the form names those packages and how many topics they cover ("97 of
    206 topics will not play: as2_msgs, kb_msgs … are not installed").
    Then speed, **Start at** (seconds into the bag, `--start-offset`), Loop
    and Publish clock. The row shows how it plays ("1× · from 10 s"). The
    palette's `ros play <path>` plays any bag too.
- **Health**: what looks wrong, worst first: duplicate node names, topics
  someone listens to that nobody publishes, services and actions with clients
  but no server, QoS mismatches (a best-effort publisher with a reliable
  subscriber, volatile with transient local; checked while the section is
  open), TF problems found by the TF section, and every `/diagnostics` status
  (merged from all publishers; one silent for 15 s turns stale, after two
  minutes it is dropped). Find narrows the graph to the item.
- **Favourites**: starred nodes, topics, services and actions (the star on
  each row), as a compact dashboard: counts, the last measured rate, and
  "not in the graph now" for one that left.
- **Graph view**: **Show in the graph view** on a node or a topic focuses the
  graph on it: a node with the topics coming in (and who publishes them) and
  going out (and who subscribes), a topic with its publishers and
  subscribers. A click on a neighbour moves the focus there; Back returns.
- **Plot**: Plot on a topic opens **PlotJuggler** subscribed to that topic
  alone. To plot several together, tap the **+** on their rows (it turns into
  a tick; the Topics section says so in a line at its top). The picked topics
  show below the list, where they stay in view however far it is scrolled:
  **PlotJuggler · N topics** with **Open in PlotJuggler** (all of them in one
  PlotJuggler) and **Clear**. The list is sized to the screen, so that bar is
  never pushed off it. PlotJuggler runs like the other tools (Stop, its
  log, Run again). Without PlotJuggler installed, Plot is the panel's own:
  it lists the message's numeric fields, and choosing one draws it live in the
  panel (the last 120 values, with now, low, high and the message count);
  **Open in rqt_plot** opens a larger plot. One such plot at a time; it stops
  after ten minutes, when the panel closes, or on Stop.
- **Nodes**: every visible node with what it has. Expanding a node shows its
  topics (type, the nodes on the other end, QoS, Hz, Preview), services and
  clients, actions, its enclave, and:
  - its parameters: names first, forty rows per page; Read value fetches just
    that parameter. A click on the value edits it in its own type (`2` for a
    double is 2.0; lists as `[1, 2]`); Enter arms the change, a second Enter
    sends it. Arrays longer than 64 items are shown cut and not editable;
  - its lifecycle state, with the transitions it can take (Configure,
    Activate, Cleanup, Deactivate), each confirmed;
  - parameter profiles: **Save parameter profile** keeps the node's
    parameters (`ros2 param dump`) under a name; choosing a saved one first
    compares it with the running node ("would change 2 parameters", each
    `now → saved`), then **Restore** loads it after a confirming click.
- **Lifecycle group** (with two or more lifecycle nodes): tick nodes, then
  Configure, Activate, Deactivate or Cleanup them together after a confirming
  click; each node shows whether it took the transition.
  Clicking any type shows its definition (`.msg`, `.srv`, `.action`).
- **Topics**, **Services**, **Actions**: the whole graph by name, folded by
  default, forty rows at a time (Show more), each row expandable the same
  way. Folding a topic, node or parent section cancels in-flight Hz/Preview
  subscriptions and discards their pending replies. A topic's Preview shows the next message (an image as a thumbnail, and
  its age from the header stamp); **Publish one message…**, **Call it…** and
  **Send a goal…** open a form generated from the request type (nested scalar fields, boolean
  dropdowns, and JSON array inputs),
  and send them after a confirming click, showing the response, the goal's
  result or how many subscribers got the message. A service whose request has
  no fields (`std_srvs/Trigger` or `Empty`: take off, land, reset) has **Call**
  on its row and in Favourites: one tap calls it, and the row then shows the
  reply's message (`✓ Taking off to 1.20 m`, or `✗` and the reason when it says
  `success: false`). Its form's Call needs no confirming click either. A goal shows its feedback
  as it arrives and can be cancelled (**Cancel goal**); one without a result
  in 30 s is cancelled.
- **TF tree**: read on demand (1.5 s of `/tf` and `/tf_static`): each frame
  under its parent, static ones marked, moving ones with rate and age; more
  than one root, a frame with two parents and a frame older than a second are
  reported in Health. Under the tree, pick a frame and the frame to see it
  from: frames in separate trees are said to be unconnected at once;
  otherwise Look up gives the position, roll/pitch/yaw, quaternion and the
  transform's age (or "Static").
- **Controllers**: ros2_control controllers and their state when a
  controller_manager runs, with Configure, Activate or Deactivate (confirmed).
  Load accepts a configured controller name; inactive or unconfigured controllers
  also offer Unload. All operations require confirmation.

Hidden names (a leading `_` in any part) are left out, as `ros2 node list`
does, and so is a topic only hidden nodes use. The panel's own node is hidden
that way.

### Alerts

Through the Dynamic Island (with its screen-sharing privacy: only "ROS 2
needs attention" shows while the screen is shared), or a notification without
it:

- a run the panel started crashed (sticky until dismissed);
- `/diagnostics` reports a new error or stale status (sticky);
- a starred node left the graph;
- a recording started, and was saved (with its size).

Crashes and recordings are noticed with the panel closed: `runs` is polled
every five seconds while anything the panel started runs, also after a shell
restart. Diagnostics and lost nodes need the watcher, so they are noticed
while the panel is open and for a minute after it closes.

### Command palette

`ros` lists the panel's actions: the ROS terminal, Open RViz2 (with each
config), Gazebo, rqt, Launch (saved launches and launch files), Record every
topic, Play a bag, Stop what the panel started, Use a saved setup or robot
profile, Build the workspace or one package. Words after
`ros` filter them; `ros record /a /b` records those topics and `ros domain 7`
switches the domain. Each runs the helper's `say`, so the notification is a
sentence.

## How it works

`shell/adaptive-shell@local/tools/ros_info.py` does all the ROS work; the
shell never loads ROS itself.

- **Environment**: it finds the distro under `/opt/ros`, sources its
  `setup.bash` (and the chosen workspace's `install/setup.bash`) in bash, and
  re-runs itself in that environment with the domain, discovery range and
  middleware applied.
- **One-shot commands** print one JSON object and exit, non-zero when it says
  `"ok": false` (see the top of the file for the list). `status` needs no ROS:
  installed tools, which are running (found in `/proc`) and which of them the
  panel started, files, saved setups and launches, the active project, recent
  runs and bags.
- **Supervised runs**: whatever the panel starts runs under `ros_info.py run`
  in a new process group led by it. It writes how the run ended to
  `~/.cache/adaptive-desktop/ros/run-history.json`: the exit code, and
  whether a signal (the panel's Stop) ended it, so a crash is told from a
  stop. Stop signals only process groups recorded in `owned-runs.json`, never
  a tool started elsewhere. Output goes to `~/.cache/adaptive-desktop/ros/
  <tool>.log` (rotated at 2 MB).
- **`watch`** runs while the dropdown is open, plus a minute after it closes
  (scanning every 10 s instead of every second then). One rclpy node keeps
  the graph and prints it as a JSON line whenever it changes; between full
  scans (every 5 s, or when a name comes or goes) only the name lists are
  compared. It answers requests on stdin with JSON lines carrying the request
  id. It exits when its stdin closes, so it cannot outlive the shell.
- **Writes** (a parameter, a lifecycle transition, a call, a goal, a message,
  a controller switch) wait until the service or action server is there, then
  send once; every client, publisher and action client is destroyed when its
  reply is out.
- **Streams**: a goal's feedback and a plot's values come as `progress` lines
  carrying the request id before (or instead of) its reply. A plot sends at
  most four a second; the panel redraws its strip in place rather than
  rebuilding the list.

`shell/adaptive-shell@local/rosPanel.js` is the dropdown: it starts and stops
the watcher, keeps what is unfolded and typed, and renders. The list is built
in blocks (setup, launch, and each graph section); a block whose inputs did
not change keeps its actors, so a graph update rebuilds only the sections it
touched. Graph updates are coalesced into one render and wait while you type
in an entry of the list.

## Checks

```sh
python3 scripts/verify-ros-panel.py        # helper against real nodes, ~70 s
python3 scripts/verify-ros-package-create.py   # every New package template created, built and run, ~2 min
node scripts/verify-ros-package-model.js   # the dialog's name checks, dependency lists, review
python3 scripts/verify-ros-controllers.py  # sourced ROS + controller_manager_msgs required
scripts/verify-shell-nested.sh --extra scripts/verify-ros-nested.sh
python3 scripts/verify-feature-logic.py    # the palette's ros mode
```

The first two skip when ROS 2 is not installed. They use a private domain with
localhost-only discovery, so they never see or disturb a real robot. The
helper check runs a fixture node of its own (diagnostics, an image with a QoS
mismatch, a moving TF frame, a typed parameter) next to the demos, a service,
an action server and a static transform, and covers every request and write,
and builds a one-package workspace with colcon; the nested check drives the
panel in a real GNOME Shell, writes included, with a second lifecycle node, a
static transform and a number on `/level` for the group, TF lookup and plot.

## Gotchas

- GNOME 42's dialog presses its default button on the Return key's
  *release*, also while an entry has focus, so Return in a form moves on by
  itself. On Dependencies Next is not the default: Return there adds the
  search's first match.
- `ModalDialog` keeps its own `this._state`; the New package dialog keeps its
  form in `_form`, or opening it breaks.
- `Clutter.FlowLayout` gives every child the widest one's cell and collapses
  to nothing inside a scroll view, so the dialog's chips wrap in plain rows
  (`chipRows`).
- A test that stops `ros2 run` by timing out kills bash, not the node: run it
  in its own session and signal the group, or a node outlives the test and
  the next check on that domain counts one node too many.

- The watcher outlives a closed dropdown by a minute. A setup change made
  elsewhere (`~/.zshrc`, `~/.bashrc`, `ros2.json`) restarts it the next time the panel
  opens; otherwise it would keep watching the old domain.
- Every node has `/rosout` and `/parameter_events`, the panel's own too, and
  the panel subscribes to `/diagnostics`; a topic only hidden nodes use is not
  listed, or it would always show.
- Discovery carries reliability and durability but not depth or history, so
  QoS shows only those two.
- `DiagnosticStatus.level` is a `byte`: rclpy gives it as `bytes`, not an int.
- A supervisor must catch signals with a handler, not `SIG_IGN`: an ignored
  signal stays ignored in the child after exec, and Stop could not end it.
- ROS's `setup.bash` reads unset variables: source it after `set +u` in any
  script that runs with `set -u` (the nested sandbox does).
- The sandbox has its own HOME, so no `~/.bashrc`: the nested check writes
  `ros2.json` for its private domain.
- Which files are read depends on `$SHELL` (else the passwd entry). When the
  terminal moved to Zsh the panel kept reading `~/.bashrc` (domain 42,
  localhost only) while nodes ran on domain 0 from `~/.zshrc`, and showed an
  empty graph. A workspace inside a dot-folder (`proj/.build/humble`) is not
  in the two-level scan; the one in use is added to the list, named `proj`.
- `controller_manager_msgs` is not installed system-wide here. Controller load,
  configure, activate, deactivate, unload and rejection handling pass using the
  genuine Humble service types from an extracted package prefix and a local
  fixture manager on private domain 89. This verifies the wire protocol, not
  hardware plugins. The selected runtime workspace must supply that package
  to use controller operations live; the UI reports its absence.
- A custom workspace must have `install/setup.bash`; unbuilt source trees cannot
  supply ROS interfaces or executable nodes. None disables the workspace overlay.
- `ros2 launch <file> --show-args` indents every argument (`    'name':`), its
  description and `(default: 'x')`; a description may run over several lines,
  the later ones not indented. "Valid choices are: [...]" ends a description.
- `ros2 param dump` prints to stdout from Humble on (`--output-dir` is
  deprecated). `ros2 param load` exits 0 when some parameters fail; it says so
  per line. Every rclcpp node has read-only `qos_overrides.*`, which can never
  be loaded back, so profiles leave them out and a read-only refusal counts
  as skipped, not failed.
- A stopped (SIGSTOP) process group holds SIGINT until it is continued: Stop
  sends SIGCONT first, or a paused launch would wait out the grace time.
- `ros2 bag play` on Humble plays a bag whose types are partly missing: it
  logs "Ignoring a topic …, reason: package '…' not found" per topic and
  plays the rest. Nothing in its exit says so, which is why the play form
  counts them first (`bag-info`).
- Bag playback is not paused by signal: rosbag2's player keeps time with a
  steady clock and would send everything that fell due at once on resume.
- `ros2 service call` waits for ever for a service that is not there, so the
  bag's pause service is looked for in `ros2 service list` first.
- rqt_plot is in the distro's `lib/rqt_plot/`, not on PATH.
- PlotJuggler's ROS 2 subscriber always asks which topics to take and has no
  option to skip that. The helper sets the two settings PlotJuggler itself
  saves after a choice (`MainWindow.previousStreamingPlugin` and
  `[DataStreamROS2] default_topics` in `~/.config/PlotJuggler/
  io.plotjuggler.PlotJuggler.ini`, every other line kept), starts it with
  `--start_streamer` (a switch: it starts the streamer last chosen), and
  presses Return on that dialog. It does so only when the dialog belongs to the
  PlotJuggler it started and has the keyboard (X11, xdotool); otherwise the
  dialog stays, with the topics already ticked. A layout naming the streamer
  asks "Start the previously used streaming plugin?", and a layout with curves
  warns that they cannot be found before data arrives, so no layout is used.
- `ros2 topic pub`'s own node is hidden (`_ros2cli_…`), so a topic only it
  publishes is not listed; the plot still subscribes to it by name.
- A scrolled St list lays its children out at their *minimum* heights once it
  is taller than the dropdown. Anything that can shrink was squeezed: a wrapped
  (and, by default, ellipsized) label to one line, so a call's reply showed only
  `{`; a dropdown's choices to nothing, so a plot field could not be picked.
  Each block is a `Block`, which asks for its full height as its minimum;
  wrapped labels also get `ellipsize = NONE` (`wrapped()`).
- A click often renders twice in a row (now, and when its reply comes: Call
  it…, Preview, Hz, Plot). The second render came before the first had put the
  scroll back, read the reset position and jumped the list to the top, so
  whatever was just opened was out of sight. `_renderNow` keeps the position
  while a restore is pending.
- Putting the scroll back on the idle after a render is not always late
  enough: a block rebuilt then (Launch, on every status reload, which node
  names coming and going trigger) can still be unmeasured, the list's height
  short of the old position, and the clamp threw the list to the top. The
  Rosbag play form sits at the bottom of Launch, so on a live graph it jumped
  away before Start playback could be pressed. The restore now waits a few
  frames for the height. Bags found in ~/Downloads are not part of the
  five-minute file cache either, so one just downloaded is listed at once.
- The plot and the graph view are drawn below the setup and the launchers, so
  opening one scrolls to its block once the list is laid out, not to the top.
- The nested check clicks with a real (virtual) pointer and checks the list
  stays where it was; emitting `clicked` on a button skips what a person's
  click goes through, and calling `_startPlot` skipped the field list.
- The plot strip spans at least 2% of the values' size (or 0.001), so a steady
  value with noise (a drone hovering at 1.2000-1.2001 m) draws a level line.
- Previews and replies print a list of plain values on one line, so an
  Odometry is about 40 lines rather than 115.
- Parameter services (`get_parameters`, `set_parameters`, …) are counted in the
  footer but not listed; each node shows its parameters instead. The panel's own
  node and the `ros2` CLI daemon are hidden too.
- `verify-ros-panel.py` runs on the real machine: a robot's own `ros2 launch`
  can be running, listed as outside the panel, so checks look at `owned_pids`.
