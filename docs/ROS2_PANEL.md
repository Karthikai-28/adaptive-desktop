# ROS 2 panel

A top-bar dropdown, just left of the Network button, for the ROS 2 graph this
computer can see and the tools used with it.

## What it shows

- **Header**: distro, domain, node count.
- **Setup**: domain ID (click to change), discovery range (localhost only or
  the LAN), middleware, and the workspace overlay (click to choose). By default
  these follow `~/.bashrc` (`export ROS_DOMAIN_ID=…`, `ROS_LOCALHOST_ONLY`,
  `RMW_IMPLEMENTATION`), so the panel sees the same graph as your terminals.
  A change made in the panel is saved in
  `~/.config/adaptive-desktop/ros2.json` and wins over `~/.bashrc`.
- **Launch**: RViz2 (and recent `.rviz` configs), Gazebo (and the worlds in
  your workspaces), rqt, rqt_graph, and a terminal with the same ROS setup.
  Terminal uses the KTERM modern Zsh profile, sources the user's `.zshrc`,
  then applies the selected distro and workspace `setup.zsh` files and panel
  domain/middleware settings. These selections override shell startup defaults.
  A running app shows Show (switch to its window) and Stop. If Gazebo is not
  installed, the row says so and Install opens a terminal on the apt command.
- **Nodes**: every visible node with what it has: publishers, subscribers,
  services, actions. Expanding a node (the chevron) shows:
  - each topic it publishes and subscribes to, with message type, the nodes on
    the other end, QoS (reliability, durability, depth), and a Hz button that
    measures the topic's rate for two seconds;
  - its service servers and clients, with types (the standard parameter
    services are folded into one line);
  - its action servers and clients, with types;
  - its parameters and their values;
  - its lifecycle state, when it is a lifecycle node;
  - its enclave.
  Clicking any type shows its definition (`.msg`, `.srv`, `.action`).
- **Topics**, **Services**, **Actions**: the whole graph by name, folded by
  default, each row expandable the same way.
- **Controllers**: ros2_control controllers and their state, when a
  controller_manager is running.

Hidden names (a leading `_`) are left out, as `ros2 node list` does. The
panel's own node is hidden that way.

## How it works

`shell/adaptive-shell@local/tools/ros_info.py` does all the ROS work; the
shell never loads ROS itself.

- **Environment**: it finds the distro under `/opt/ros`, sources its
  `setup.bash` (and the chosen workspace's `install/setup.bash`) in bash, and
  re-runs itself in that environment with the domain, discovery range and
  middleware applied.
- **One-shot commands** (`status`, `launch`, `stop`, `set`, `terminal`) print
  one JSON object and exit. `status` needs no ROS: installed tools, which are
  running (found in `/proc`), RViz configs, Gazebo worlds, workspaces.
- **`watch`** runs while the dropdown is open, plus a minute after it closes so
  reopening is instant. One rclpy node does discovery once, prints the graph as
  a JSON line whenever it changes, and answers requests on stdin
  (`node`, `topic`, `interface`, `hz`) with JSON lines carrying the request
  id. It exits when its stdin closes, so it cannot outlive the shell.

`shell/adaptive-shell@local/rosPanel.js` is the dropdown: it starts and stops
the watcher, keeps which rows are expanded, and renders.

## Plan (done)

1. Helper, environment and status: distro, `~/.bashrc` settings, config,
   workspaces, installed and running tools, RViz configs, Gazebo worlds.
2. Helper, launching: launch and stop RViz2, Gazebo (Classic, Fortress or
   newer, through their ROS launch files when present), rqt, rqt_graph, the
   demo talker and listener; a ROS terminal; install hint for Gazebo.
3. Helper, watch: live graph, node and topic details, parameters, lifecycle
   state, interface definitions, topic rate, ros2_control controllers.
4. Shell panel: indicator next to Network, header, setup, launch rows.
5. Shell panel: live sections, expandable nodes, topics, services, actions,
   type definitions, Hz.
6. Checks: `scripts/verify-ros-panel.py` runs the helper against real demo
   nodes on a private domain; `scripts/verify-ros-nested.sh` opens the
   dropdown in the nested shell sandbox; both from `verify-all.sh`.
7. Docs, backlog and the repository map.

## Checks

```sh
python3 scripts/verify-ros-panel.py        # helper against real nodes, ~20 s
scripts/verify-shell-nested.sh --extra scripts/verify-ros-nested.sh
```

Both skip when ROS 2 is not installed. They use a private domain with
localhost-only discovery, so they never see or disturb a real robot.

## Gotchas

- The watcher outlives a closed dropdown by a minute. A setup change made
  elsewhere (`~/.bashrc`, `ros2.json`) restarts it the next time the panel
  opens; otherwise it would keep watching the old domain.
- Every node has `/rosout` and `/parameter_events`, the panel's own too; with
  only hidden nodes on them they are left out.
- Discovery carries reliability and durability but not depth or history, so
  QoS shows only those two.
- ROS's `setup.bash` reads unset variables: source it after `set +u` in any
  script that runs with `set -u` (the nested sandbox does).
- The sandbox has its own HOME, so no `~/.bashrc`: the nested check writes
  `ros2.json` for its private domain.
