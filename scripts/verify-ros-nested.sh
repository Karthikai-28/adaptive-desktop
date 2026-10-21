#!/usr/bin/env bash
# Sourced by verify-shell-nested.sh --extra; runs only in its isolated desktop.
# The ROS 2 panel against real demo nodes: a talker, two lifecycle talkers, an
# action server, a static transform and a number on /level, on a private domain
# with localhost-only discovery, so it never sees or disturbs a real robot.
# Skips without ROS 2 under /opt/ros.
#
# ADAPTIVE_ROS_SHOT=<file.png> also saves a picture of the open dropdown. The
# nodes' output is in $SANDBOX/ros-nodes.log (kept with --keep).

ros_setup="$(ls /opt/ros/*/setup.bash 2>/dev/null | tail -1)"
if [ -z "$ros_setup" ]; then
    echo "SKIP ros panel: ROS 2 is not installed"
    return 0 2>/dev/null || exit 0
fi

ROS_TEST_DOMAIN=87
mkdir -p "$HOME/.config/adaptive-desktop"
printf '{"domain": %d, "localhost": true}\n' "$ROS_TEST_DOMAIN" > "$HOME/.config/adaptive-desktop/ros2.json"
ros_lib="$(dirname "$ros_setup")/lib"
(
    # setup.bash reads unset variables; the sandbox runs with set -u.
    set +u
    # shellcheck disable=SC1090
    . "$ros_setup"
    export ROS_DOMAIN_ID=$ROS_TEST_DOMAIN ROS_LOCALHOST_ONLY=1
    "$ros_lib/demo_nodes_cpp/talker" >>"$SANDBOX/ros-nodes.log" 2>&1 &
    "$ros_lib/lifecycle/lifecycle_talker" >>"$SANDBOX/ros-nodes.log" 2>&1 &
    "$ros_lib/lifecycle/lifecycle_talker" --ros-args -r __node:=lc_talker2 >>"$SANDBOX/ros-nodes.log" 2>&1 &
    python3 "$ros_lib/action_tutorials_py/fibonacci_action_server" >>"$SANDBOX/ros-nodes.log" 2>&1 &
    "$ros_lib/tf2_ros/static_transform_publisher" --z 0.5 --frame-id world --child-frame-id base_link \
        >>"$SANDBOX/ros-nodes.log" 2>&1 &
    # ros2 topic pub's own node is hidden, so the panel still counts five.
    ros2 topic pub -r 5 /level std_msgs/msg/Float64 "{data: 1.5}" >>"$SANDBOX/ros-nodes.log" 2>&1 &
    wait
) &
ROS_NODES=$!
ros_stop_nodes() { pkill -P "$ROS_NODES" 2>/dev/null; kill "$ROS_NODES" 2>/dev/null; }

ROS='const ros = adaptive.extension._shell._rosPanel;'
ros_text() { probe "$SLEEP $LABELS $ROS return (async () => { $1 })();"; }
# Waits until the dropdown shows every word given, up to ~10 s; prints what it shows.
ros_wait_for() {
    local want="$1"
    ros_text "for (let i = 0; i < 40; i++) { const t = labels(ros._list).join('|');
        if ([$want].every(w => t.includes(w))) return true; await sleep(250); }
        return labels(ros._list).join('|');"
}

[ "$(probe "return !!Main.panel.statusArea['adaptive-ros']")" = true ]; check $? "ros: the top bar has the ROS 2 button"
[ "$(probe "const box = Main.panel._rightBox.get_children();
    return box.indexOf(Main.panel.statusArea['adaptive-ros'].container) + 1 ===
        box.indexOf(Main.panel.statusArea['adaptive-network'].container);")" = true ]
check $? "ros: it sits just left of Network"

ros_text "Main.panel.statusArea['adaptive-ros'].menu.open(); return true;" >/dev/null
seen="$(ros_wait_for "'$ROS_TEST_DOMAIN', 'This computer only', 'RViz2', 'Gazebo', 'Terminal', '/talker', '/lc_talker', '/fibonacci_action_server'")"
[ "$seen" = true ]; check $? "ros: the dropdown shows the setup, the launchers and the live nodes$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "for (let i = 0; i < 40; i++) { if (ros._summary.text === 'Humble · domain $ROS_TEST_DOMAIN · 5 nodes') return true;
    await sleep(250); } return ros._summary.text;")"
[ "$seen" = true ]
check $? "ros: the header counts the nodes and hides its own"

ros_text "ros._toggle('node:/talker', () => ros._fetch(ros._details, 'node:/talker', 'node', { name: '/talker' })); return true;" >/dev/null
seen="$(ros_wait_for "'Publishes', '/chatter', 'std_msgs/msg/String', 'no subscribers', 'reliable · volatile', 'Parameters', 'use_sim_time'")"
[ "$seen" = true ]; check $? "ros: an expanded node shows its topics, types, QoS and parameters$([ "$seen" = true ] || echo " ($seen)")"

ros_text "ros._toggleInterface('node:/talker', 'std_msgs/msg/String'); return true;" >/dev/null
seen="$(ros_wait_for "'string data'")"
[ "$seen" = true ]; check $? "ros: a type shows its definition"

ros_text "ros._measure('/chatter'); return true;" >/dev/null
seen="$(ros_wait_for "' Hz · '")"
[ "$seen" = true ]; check $? "ros: Hz measures the talker's rate"

ros_text "ros._toggle('node:/lc_talker', () => ros._fetch(ros._details, 'node:/lc_talker', 'node', { name: '/lc_talker' })); return true;" >/dev/null
seen="$(ros_wait_for "'Lifecycle', 'Unconfigured'")"
[ "$seen" = true ]; check $? "ros: a lifecycle node shows its state"

ros_text "ros._toggle('section:topics'); ros._toggle('section:actions'); return true;" >/dev/null
seen="$(ros_wait_for "'Topics · ', '1 publisher', '/fibonacci', 'action_tutorials_interfaces/action/Fibonacci', 'served by /fibonacci_action_server'")"
[ "$seen" = true ]; check $? "ros: the topic and action sections list the graph$([ "$seen" = true ] || echo " ($seen)")"

# A render with nothing changed keeps every block's actors.
[ "$(ros_text "const before = [...ros._blocks.values()].map(b => b.actor); ros._renderNow();
    const after = [...ros._blocks.values()].map(b => b.actor);
    return before.length > 3 && before.every((a, i) => a === after[i] && a.get_parent() === ros._list);")" = true ]
check $? "ros: a render with nothing new keeps the built rows"

ros_text "ros._search.set_text('fibonacci'); return true;" >/dev/null
seen="$(ros_wait_for "'Nodes · 1 of 5', '/fibonacci_action_server'")"
[ "$seen" = true ]; check $? "ros: the search narrows the graph$([ "$seen" = true ] || echo " ($seen)")"
# Names, types and namespaces match, not the names a node carries, and the
# sections holding matches open by themselves.
ros_text "ros._search.set_text('chatter'); return true;" >/dev/null
seen="$(ros_wait_for "'Nodes · 0 of 5', 'Topics · 1 of', '/chatter', 'std_msgs/msg/String · 1 publisher'")"
[ "$seen" = true ]; check $? "ros: a search opens the sections it matches in, by name$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._search.set_text('act'); return true;" >/dev/null
seen="$(ros_wait_for "'Nodes · 1 of 5', 'Topics · 0 of', 'served by /fibonacci_action_server'")"
[ "$seen" = true ]; check $? "ros: a search does not match every node through its fields$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._search.set_text(''); return true;" >/dev/null

ros_text "ros._toggle('section:health', () => ros._fetchHealth()); return true;" >/dev/null
seen="$(ros_wait_for "'Health · OK', 'Nothing looks wrong'")"
[ "$seen" = true ]; check $? "ros: Health finds nothing wrong with the demo graph$([ "$seen" = true ] || echo " ($seen)")"

# A write takes two clicks: the first arms it and says so.
ros_text "const n = ros._graph.nodes.find(x => x.name === '/lc_talker'); ros._lifecycle(n, 'configure'); return true;" >/dev/null
seen="$(ros_wait_for "'Confirm configure'")"
[ "$seen" = true ]; check $? "ros: a lifecycle transition asks for a confirming click"
ros_text "const n = ros._graph.nodes.find(x => x.name === '/lc_talker'); ros._lifecycle(n, 'configure'); return true;" >/dev/null
seen="$(ros_wait_for "'Inactive', 'Activate'")"
[ "$seen" = true ]; check $? "ros: the confirmed transition configures the node$([ "$seen" = true ] || echo " ($seen)")"

ros_text "ros._toggle('section:lifecycle'); return true;" >/dev/null
seen="$(ros_wait_for "'Lifecycle group · 2 nodes', '○ /lc_talker', '○ /lc_talker2', 'Tick the nodes'")"
[ "$seen" = true ]; check $? "ros: the lifecycle group lists the lifecycle nodes$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._lifecycleSelection.add('/lc_talker'); ros._lifecycleSelection.add('/lc_talker2');
    ros._lifecycleGroup('configure', ['/lc_talker', '/lc_talker2']); return true;" >/dev/null
seen="$(ros_wait_for "'Confirm configure 2'")"
[ "$seen" = true ]; check $? "ros: a group transition asks for a confirming click"
ros_text "ros._lifecycleGroup('configure', ['/lc_talker', '/lc_talker2']); return true;" >/dev/null
seen="$(ros_wait_for "'/lc_talker · turned configure down', '/lc_talker2 · configure done'")"
[ "$seen" = true ]; check $? "ros: each node's outcome is shown (the configured one refuses)$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._toggle('section:lifecycle'); return true;" >/dev/null

# The focused graph view, moved from a node to one of its topics.
ros_text "ros._focusOn('node', '/talker'); return true;" >/dev/null
seen="$(ros_wait_for "'Graph view · /talker', 'In ↓  topics it subscribes to', '/parameter_events', 'Out ↓  topics it publishes', '/chatter', 'no subscribers'")"
[ "$seen" = true ]; check $? "ros: the graph view shows a node's topics$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._focusOn('topic', '/chatter'); return true;" >/dev/null
seen="$(ros_wait_for "'Graph view · /chatter', 'In ↓  publishers', 'Nobody subscribes', 'Back'")"
[ "$seen" = true ]; check $? "ros: a click moves the graph view to the topic$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._focus = null; ros._render(); return true;" >/dev/null

# A live plot of /level, drawn in place.
ros_text "ros._startPlot('/level', 'data'); return true;" >/dev/null
seen="$(ros_text "for (let i = 0; i < 40; i++) { const p = ros._plot;
        if (p && p.values.length >= 4 && p.strip && p.strip.actor.get_stage() &&
            labels(ros._list).join('|').includes('Now 1.5')) return true; await sleep(250); }
    return labels(ros._list).join('|');")"
[ "$seen" = true ]; check $? "ros: a numeric field plots live$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "const id = ros._plot.id; ros._stopPlot(); ros._render(); await sleep(300);
    return !ros._plot && !ros._pending.has(id) && !labels(ros._list).join('|').includes('Plot · ');")"
[ "$seen" = true ]; check $? "ros: Stop ends the plot and forgets its request"

# TF: one transform between two picked frames.
ros_text "ros._toggle('section:tf', () => ros._fetchTf()); return true;" >/dev/null
seen="$(ros_wait_for "'base_link', 'Where one frame is in another'")"
[ "$seen" = true ]; check $? "ros: the TF tree offers a transform lookup$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._tfLookup = { source: 'base_link', target: 'world' }; ros._lookupTf(); return true;" >/dev/null
seen="$(ros_wait_for "'Position  0.000  0.000  0.500 m', 'Static'")"
[ "$seen" = true ]; check $? "ros: the transform between them is shown$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._toggle('section:tf'); return true;" >/dev/null

# The launch form: a choice, a required argument that has to be given.
seen="$(ros_text "const { St } = imports.gi;
    const loadStatus = ros._loadStatus; ros._loadStatus = () => {};
    const saved = ros._status;
    ros._status = { ...saved, launch_files: [{ name: 'robot.launch.py', path: '/fixture/robot.launch.py' }] };
    ros._launchDraft = { file: '/fixture/robot.launch.py', text: '', loading: false, arguments: [
        { name: 'mode', default: 'fast', description: 'Mode', required: false, choices: ['fast', 'safe'], value: 'fast' },
        { name: 'robot', default: '', description: 'Robot name', required: true, choices: [], value: '' }] };
    ros._renderNow();
    const find = actor => actor instanceof St.Button && actor.label === 'Launch' ? actor
        : actor.get_children().map(find).find(Boolean);
    const button = find(ros._list);
    if (button)
        button.emit('clicked', 1);
    await sleep(200);
    const text = labels(ros._list).join('|');
    ros._status = saved; ros._loadStatus = loadStatus;
    return ['robot · required · Robot name', 'Argument mode · fast', 'robot has no default; give it a value']
        .every(w => text.includes(w)) || text;")"
[ "$seen" = true ]; check $? "ros: the launch form shows choices and holds back a missing required argument$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._launchDraft = null; ros._render(); return true;" >/dev/null

ros_text "ros._toggle('action:/fibonacci');
    ros._toggleComposer('goal:/fibonacci', 'action', 'action_tutorials_interfaces/action/Fibonacci'); return true;" >/dev/null
seen="$(ros_wait_for "'order', 'Send goal'")"
[ "$seen" = true ]; check $? "ros: a goal starts from an empty one of its type$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._composers.get('goal:/fibonacci').text = '{order: 2}';
    const send = () => ros._send('goal:/fibonacci', 'goal', '/fibonacci', 'action_tutorials_interfaces/action/Fibonacci');
    send(); send(); return true;" >/dev/null
seen="$(ros_wait_for "'Succeeded', 'sequence'")"
[ "$seen" = true ]; check $? "ros: the confirmed goal runs to its result$([ "$seen" = true ] || echo " ($seen)")"

seen="$(ros_text "const n = ros._graph.nodes.find(x => x.name === '/talker');
    const p = await new Promise(resolve => ros._request('parameter', {node: '/talker', name: 'use_sim_time'}, resolve));
    ros._setParameter(n, p, 'true'); ros._setParameter(n, p, 'true');
    for (let i = 0; i < 40; i++) { const d = ros._details.get('node:/talker');
        const now = await new Promise(resolve => ros._request('parameter', {node: '/talker', name: 'use_sim_time'}, resolve));
        if (now && now.value === true) return true; await sleep(250); }
    return JSON.stringify(ros._notes);")"
[ "$seen" = true ]; check $? "ros: a parameter is set in its own type$([ "$seen" = true ] || echo " ($seen)")"

seen="$(ros_text "const saved = await new Promise(resolve => ros._helper(['parameter-profile', 'save', '/talker', 'Bench'], resolve));
    if (!saved.ok) return JSON.stringify(saved);
    ros._status.parameter_profiles = saved.parameter_profiles;
    await new Promise(resolve => ros._request('set_parameter', {node: '/talker', name: 'use_sim_time', value: 'false', ptype: 1}, resolve));
    ros._compareParameterProfile('/talker', 'Bench');
    for (let i = 0; i < 60; i++) { const t = labels(ros._list).join('|');
        if (t.includes('Bench would change 1 parameter') && t.includes('use_sim_time: false → true')) return true;
        await sleep(250); }
    return JSON.stringify(ros._paramDiff);")"
[ "$seen" = true ]; check $? "ros: a parameter profile is compared with the node before restoring$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "const restore = () => ros._confirmed('param-profile:/talker:Bench', () => ros._parameterProfile('apply', '/talker', 'Bench'));
    restore(); restore();
    for (let i = 0; i < 60; i++) {
        const now = await new Promise(resolve => ros._request('parameter', {node: '/talker', name: 'use_sim_time'}, resolve));
        if (now && now.value === true && labels(ros._list).join('|').includes('Restored')) return true; await sleep(250); }
    return JSON.stringify(ros._notes['op:/talker']);")"
[ "$seen" = true ]; check $? "ros: the confirmed restore sets the saved values$([ "$seen" = true ] || echo " ($seen)")"

# Recording lights the top-bar icon until it is stopped and listed.
seen="$(ros_text "ros._recordTopics(); ros._recordTopics();
    for (let i = 0; i < 40; i++) { if (ros._runs && ros._runs.recording &&
        ros._icon.has_style_class_name('adaptive-ros-recording') &&
        Main._dynamicIsland.backend.getMultiActivitySlots().primary?.type === 'ros') return true; await sleep(250); }
    return JSON.stringify(ros._notes.bag);")"
[ "$seen" = true ]; check $? "ros: Record starts a bag and the icon shows it$([ "$seen" = true ] || echo " ($seen)")"
sleep 2
seen="$(ros_text "ros._stop('bag');
    for (let i = 0; i < 40; i++) { if (!(ros._runs && ros._runs.recording) && ros._status.bags.length === 1 &&
        !ros._icon.has_style_class_name('adaptive-ros-recording') &&
        Main._dynamicIsland.backend.getMultiActivitySlots().primary?.type !== 'ros') return true; await sleep(250); }
    return JSON.stringify(ros._status.bags);")"
[ "$seen" = true ]; check $? "ros: Stop saves the bag, lists it and clears the icon$([ "$seen" = true ] || echo " ($seen)")"

ros_text "ros._openLogView('bag'); return true;" >/dev/null
seen="$(ros_wait_for "'Running from here · 0', 'Rosbag log', 'Follow in a terminal'")"
[ "$seen" = true ]; check $? "ros: a run's log opens in the run manager$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._logView = null; ros._toggle('section:run-manager'); ros._toggle('bag:topics'); return true;" >/dev/null
seen="$(ros_wait_for "'✓ /chatter', '✓ /tf_static', 'Records 6 chosen topics', 'What the list shows'")"
[ "$seen" = true ]; check $? "ros: topics to record are ticked one by one$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._bagTopics = null; ros._toggle('bag:topics'); return true;" >/dev/null

# Stress the selectors with multiple packages and enough files to scroll.
seen="$(ros_text "
    await sleep(1000);
    ros._layoutTestLoadStatus = ros._loadStatus; ros._loadStatus = () => {};
    const saved = ros._status;
    const root = '/fixture/ros2_ws/src';
    ros._status = {...saved, workspace: '/fixture/ros2_ws',
        workspaces: [{name: 'ros2_ws', path: '/fixture/ros2_ws'}],
        packages: ['alpha', 'beta'].map(name => ({name, path: root + '/' + name, executables: []})),
        launch_files: Array.from({length: 32}, (_, i) => ({name: 'demo_' + i + '.launch.py',
            path: root + (i % 2 ? '/alpha/' : '/beta/') + 'demo_' + i + '.launch.py'}))};
    ros._packagePath = root + '/alpha';
    ros._expanded.add('select:Files'); ros._renderNow(); await sleep(300);
    const text = labels(ros._list).join('|');
    const filtered = text.includes('demo_31.launch.py') && !text.includes('demo_30.launch.py');
    const children = ros._blocks.get('launch').actor.get_children();
    const noOverlap = children.every((a, i) => i === 0 || a.y >= children[i - 1].y + children[i - 1].height - 1);
    ros._layoutTestSaved = saved;
    return filtered && noOverlap ? true : JSON.stringify({filtered, noOverlap, text, rows: children.map(a => [a.y, a.height])});")"
[ "$seen" = true ]; check $? "ros: package selection scopes long dropdowns and expanded lists do not overlap$([ "$seen" = true ] || echo " ($seen)")"

if [ -n "${ADAPTIVE_ROS_SHOT:-}" ]; then
    probe "const { Gio, Shell } = imports.gi; return new Promise(resolve => {
        const stream = Gio.File.new_for_path('$ADAPTIVE_ROS_SHOT').replace(null, false, Gio.FileCreateFlags.NONE, null);
        new Shell.Screenshot().screenshot(false, stream, (shot, result) => {
            shot.screenshot_finish(result); stream.close(null); resolve(true); }); });" >/dev/null
fi

# A workspace's packages, each with Build, and Build all.
seen="$(ros_text "ros._status = {...ros._status, workspace: '/fixture/ros2_ws', tools: {...ros._status.tools, build: {installed: true}},
        packages: [{name: 'alpha', path: '/fixture/ros2_ws/src/alpha', built: true, executables: [{name: 'go', path: '/x'}]},
                   {name: 'beta', path: '/fixture/ros2_ws/src/beta', built: false, executables: []}]};
    ros._packagePath = ''; ros._renderNow(); await sleep(200);
    const text = labels(ros._list).join('|');
    const builds = text.split('|').filter(t => t === 'Build').length;
    return ['colcon build', 'Build all', 'Packages · 2 · 1 not built', 'With dependencies', 'alpha', '1 executable',
        'beta', 'not built yet'].every(w => text.includes(w)) && builds === 2 || text;")"
[ "$seen" = true ]; check $? "ros: the workspace lists its packages, each with its own Build$([ "$seen" = true ] || echo " ($seen)")"

ros_text "ros._status = ros._layoutTestSaved; delete ros._layoutTestSaved;
    ros._loadStatus = ros._layoutTestLoadStatus; delete ros._layoutTestLoadStatus;
    ros._packagePath = ''; ros._expanded.delete('select:Files'); ros._renderNow(); return true;" >/dev/null

# A robot profile in use is named; Forget removes it.
seen="$(ros_text "ros._saveRobotProfile('Bench rig');
    for (let i = 0; i < 40; i++) { const t = labels(ros._list).join('|');
        if (t.includes('Robot profile · Bench rig') && t.includes('In use')) return true; await sleep(250); }
    return labels(ros._list).join('|');")"
[ "$seen" = true ]; check $? "ros: a saved robot profile shows as in use$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "ros._forgetRobotProfile('Bench rig');
    for (let i = 0; i < 40; i++) { const t = labels(ros._list).join('|');
        if (!t.includes('Bench rig') && t.includes('Keeps this setup')) return true; await sleep(250); }
    return labels(ros._list).join('|');")"
[ "$seen" = true ]; check $? "ros: Forget removes the robot profile$([ "$seen" = true ] || echo " ($seen)")"

# A node that leaves disappears from the dropdown by itself.
ros_stop_nodes
seen="$(ros_text "for (let i = 0; i < 60; i++) { if (ros._graph && ros._graph.nodes.length === 0) return true; await sleep(250); }
    return ros._summary.text;")"
[ "$seen" = true ]; check $? "ros: nodes that stop leave the list$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_wait_for "'No nodes on domain $ROS_TEST_DOMAIN', 'Start demo'")"
[ "$seen" = true ]; check $? "ros: the empty graph offers the demo$([ "$seen" = true ] || echo " ($seen)")"

# Closing keeps the watcher a while; stopping it ends the process.
watcher="$(ros_text "Main.panel.statusArea['adaptive-ros'].menu.close(); await sleep(300);
    const id = ros._watch && ros._watch.proc.get_identifier(); ros._stopWatch(); return id || 'none';")"
sleep 3
[ "$watcher" != none ] && [ ! -e "/proc/$watcher" ]; check $? "ros: the watcher exits when it is stopped"
