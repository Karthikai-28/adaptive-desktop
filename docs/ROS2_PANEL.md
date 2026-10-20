# ROS 2 panel

A top-bar dropdown, just left of the Network button, for the ROS 2 graph this
computer can see and the tools used with it. The command palette's `ros` mode
does the panel's actions from the keyboard.

## What it shows

- **Header**: distro, domain, node count, "recording" while a bag records.
  The top-bar icon turns red while the panel records a bag, orange while
  `/diagnostics` reports an error.
- **Search** (under the header): narrows every section to what matches a
  node, topic, service, action, type or namespace; the section headings say
  "3 of 40". Escape clears it.
- **Setup**: domain ID (click to change), discovery range (localhost only or
  the LAN), middleware, and the workspace overlay (click to choose). By default
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
  - **Setups**: the current domain, discovery, middleware and workspace saved
    under a name (a robot, a bench); a chip applies one, the one in use is
    lit.
  - When Project Context's active project is, holds (`proj/.build/<distro>`)
    or sits in a colcon workspace the panel does not use, the card offers
    **Use it** or **Always follow** (the workspace then follows the active
    project, "from the active project").
- **Launch**: RViz2 (and recent `.rviz` configs), Gazebo (and the worlds in
  your workspaces), rqt, rqt_graph, a terminal with the same ROS setup.
  Terminal uses the KTERM modern Zsh profile, sources the user's `.zshrc`,
  then applies the selected distro and workspace `setup.zsh` files and panel
  domain/middleware settings. A running app shows Show (its window), and when
  the panel started it Log and Stop. **Rescan files** walks the folders again
  (the search is kept five minutes).
  - **Launch files**: saved launches start at a click; a launch file from a
    workspace's `src` first asks for its arguments (`name:=value …`, nothing
    else is taken) and can be saved with them.
  - A run the panel started that exited by itself with an error stays listed
    for a day with its exit code, **Log** and **Restart**.
  - **Rosbag**: Record records the topics the graph shows (narrowed by the
    search) into `~/.local/share/adaptive-desktop/rosbags`, after a confirming
    click; while it runs the row shows its size and length. Recent bags are
    listed with length, messages, topics and size, with Play and Folder. One
    bag runs at a time.
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
- **Nodes**: every visible node with what it has. Expanding a node shows its
  topics (type, the nodes on the other end, QoS, Hz, Preview), services and
  clients, actions, its enclave, and:
  - its parameters: a click on a value edits it in its own type (`2` for a
    double is 2.0; lists as `[1, 2]`); Enter arms the change, a second Enter
    sends it. Arrays longer than 64 items are shown cut and not editable;
  - its lifecycle state, with the transitions it can take (Configure,
    Activate, Cleanup, Deactivate), each confirmed.
  Clicking any type shows its definition (`.msg`, `.srv`, `.action`).
- **Topics**, **Services**, **Actions**: the whole graph by name, folded by
  default, forty rows at a time (Show more), each row expandable the same
  way. A topic's Preview shows the next message (an image as a thumbnail, and
  its age from the header stamp); **Publish one message…**, **Call it…** and
  **Send a goal…** open the fields of an empty message of the type, as YAML,
  and send them after a confirming click, showing the response, the goal's
  result or how many subscribers got the message. A goal without a result in
  30 s is cancelled.
- **TF tree**: read on demand (1.5 s of `/tf` and `/tf_static`): each frame
  under its parent, static ones marked, moving ones with rate and age; more
  than one root, a frame with two parents and a frame older than a second are
  reported in Health.
- **Controllers**: ros2_control controllers and their state when a
  controller_manager runs, with Configure, Activate or Deactivate (confirmed).

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
topic, Play a bag, Stop what the panel started, Use a saved setup. Words after
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

`shell/adaptive-shell@local/rosPanel.js` is the dropdown: it starts and stops
the watcher, keeps what is unfolded and typed, and renders. The list is built
in blocks (setup, launch, and each graph section); a block whose inputs did
not change keeps its actors, so a graph update rebuilds only the sections it
touched. Graph updates are coalesced into one render and wait while you type
in an entry of the list.

## Checks

```sh
python3 scripts/verify-ros-panel.py        # helper against real nodes, ~40 s
scripts/verify-shell-nested.sh --extra scripts/verify-ros-nested.sh
python3 scripts/verify-feature-logic.py    # the palette's ros mode
```

The first two skip when ROS 2 is not installed. They use a private domain with
localhost-only discovery, so they never see or disturb a real robot. The
helper check runs a fixture node of its own (diagnostics, an image with a QoS
mismatch, a moving TF frame, a typed parameter) next to the demos, a service,
an action server and a static transform, and covers every request and write;
the nested check drives the panel in a real GNOME Shell, writes included.

## Gotchas

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
- `controller_manager_msgs` is not installed here, so listing and switching
  ros2_control controllers is written but untested.
