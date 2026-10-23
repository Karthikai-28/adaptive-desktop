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

# A live plot of /level, drawn in place. It sits below the setup and the
# launchers, so starting it from far down the list scrolls to it.
ros_text "ros._expanded.add('section:topics'); ros._renderNow(); await sleep(300);
    const adj = ros._scroll.vscroll.adjustment; adj.value = adj.upper - adj.page_size; await sleep(100);
    ros._startPlot('/level', 'data'); return true;" >/dev/null
seen="$(ros_text "for (let i = 0; i < 40; i++) { const p = ros._plot;
        if (p && p.values.length >= 4 && p.strip && p.strip.actor.get_stage() &&
            labels(ros._list).join('|').includes('Now 1.5')) return true; await sleep(250); }
    return labels(ros._list).join('|');")"
[ "$seen" = true ]; check $? "ros: a numeric field plots live$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "const b = ros._blocks.get('plot'); const adj = ros._scroll.vscroll.adjustment;
    for (let i = 0; i < 20 && b && Math.abs(adj.value - Math.max(0, Math.min(b.actor.get_y() - 12, adj.upper - adj.page_size))) > 1; i++) await sleep(100);
    const y = b ? b.actor.get_y() : -1;
    return (b && y >= adj.value && y < adj.value + adj.page_size) || 'plot at ' + y + ', view ' + adj.value + '..' + (adj.value + adj.page_size);")"
[ "$seen" = true ]; check $? "ros: starting a plot scrolls to it$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "const strip = ros._plot.strip; const keep = strip._values;
    const level = values => { strip.setValues(values); const [low, span] = strip._bounds();
        return values.map(v => (v - low) / span); };
    const hover = level([1.2, 1.2001, 1.2]), climb = level([0, 0.6, 1.2]);
    strip._values = keep;
    return (hover.every(y => Math.abs(y - 0.5) < 0.01) && Math.abs(climb[0]) < 1e-9 && Math.abs(climb[2] - 1) < 1e-9)
        || JSON.stringify({ hover, climb });")"
[ "$seen" = true ]; check $? "ros: noise plots level, a real change spans the strip$([ "$seen" = true ] || echo " ($seen)")"
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

# A service without request fields, called with real clicks like the drone's
# /drone/takeoff (std_srvs/Trigger). Started late so the node counts above hold.
cat > "$SANDBOX/trigger_fixture.py" <<'PY'
import rclpy
from rclpy.node import Node
from example_interfaces.srv import AddTwoInts
from std_msgs.msg import Float64
from std_srvs.srv import Trigger
class Fixture(Node):
    def __init__(self):
        super().__init__('trigger_fixture')
        self.calls = 0
        self.create_service(Trigger, '/trigger_test', self.on_call)
        self.create_service(Trigger, '/trigger_refuse', self.on_refuse)
        self.create_service(AddTwoInts, '/add_test', self.on_add)
        self.altitude = self.create_publisher(Float64, '/altitude', 10)
        self.create_timer(0.1, lambda: self.altitude.publish(Float64(data=1.2 + 0.0001 * (self.calls % 2))))
    def on_refuse(self, request, response):
        response.success, response.message = False, 'No /odom yet'
        return response
    def on_add(self, request, response):
        print('ADDED', flush=True)
        response.sum = request.a + request.b
        return response
    def on_call(self, request, response):
        self.calls += 1
        response.success, response.message = True, f'Taking off ({self.calls})'
        print(f'CALLED {self.calls}', flush=True)
        return response
rclpy.init(); rclpy.spin(Fixture())
PY
(
    set +u
    # shellcheck disable=SC1090
    . "$ros_setup"
    export ROS_DOMAIN_ID=$ROS_TEST_DOMAIN ROS_LOCALHOST_ONLY=1
    exec python3 "$SANDBOX/trigger_fixture.py" >>"$SANDBOX/trigger.log" 2>&1
) &
TRIGGER=$!
# Real pointer clicks, as a person makes them: the target is scrolled onto the
# screen, the pointer moves there and presses. Prints {found, before, after}:
# where the list was scrolled before the click and a moment after it.
PRESS='const { Clutter, GLib, St } = imports.gi;
globalThis.__rosPointer = globalThis.__rosPointer || Clutter.get_default_backend().get_default_seat()
    .create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
const dev = globalThis.__rosPointer, now = () => GLib.get_monotonic_time();
const adj = ros._scroll.vscroll.adjustment;
const textOf = a => (a.get_text ? a.get_text() : null) || (a instanceof St.Button ? a.label || a.accessible_name : null) || "";
const find = (text, exact, root = null) => { let hit = null; const walk = a => { if (hit) return; const t = textOf(a);
    if (t && (exact ? t === text : t.startsWith(text)) && a.is_mapped()) { hit = a; return; }
    a.get_children().forEach(walk); }; (root ? [root] : [ros._list, ros._footer]).forEach(walk); return hit; };
/* within: the title of the row to look in (its whole row button) */
const rowOf = title => { let a = find(title, true); while (a && !(a instanceof St.Button && a.style_class && a.style_class.includes("adaptive-cc-row"))) a = a.get_parent(); return a; };
const press = async (text, exact, within = "") => {
    /* a render just made puts the scroll back on the next frames: let it, as a person waits to see the list */
    for (let i = 0; i < 40 && ros._scrollId; i++) await sleep(50);
    let a = null; for (let i = 0; i < 40; i++) { const root = within ? rowOf(within) : ros._list;
        if (root && (a = find(text, exact, root))) break; await sleep(250); }
    if (!a) return { found: false };
    for (let i = 0; i < 4 && ros._list.contains(a); i++) {   /* onto the screen, inside the list */
        const [, sy] = ros._scroll.get_transformed_position(); const [, sh] = ros._scroll.get_transformed_size();
        const top = Math.max(sy, 0) + 30, bottom = Math.min(sy + sh, global.stage.height) - 30;
        const [, ay] = a.get_transformed_position(); const mid = ay + Math.min(a.get_height(), 30) / 2;
        if (mid >= top && mid <= bottom) break;
        adj.value = Math.max(0, Math.min(adj.value + mid - (top + bottom) / 2, adj.upper - adj.page_size)); await sleep(300);
    }
    const [x, y] = a.get_transformed_position(); const before = Math.round(adj.value);
    dev.notify_absolute_motion(now(), x + Math.min(a.get_width() / 2, 40), y + Math.min(a.get_height(), 30) / 2); await sleep(120);
    dev.notify_button(now(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED); await sleep(80);
    dev.notify_button(now(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED); await sleep(1500);
    return { found: true, before, after: Math.round(adj.value), open: ros._button.menu.isOpen };
};'
ros_press() {  # ros_press <label> [exact] [row title]: true when found, clicked and the list stayed where it was
    local r
    r="$(probe "$SLEEP $ROS $PRESS return (async () => { const r = await press('$1', ${2:-false}, '${3:-}');
        return r.found && r.open && Math.abs(r.after - r.before) <= 2 ? true : JSON.stringify(r); })();")"
    echo "$r"
}
# Every wrapped text in the list gets the height it asks for (a squeezed one drew over its neighbours).
ros_full_height() {
    ros_text "await sleep(300); const short = []; (function walk(a) {
        if (a instanceof imports.gi.St.Label && a.clutter_text.line_wrap && a.is_mapped()) {
            const [, want] = a.get_preferred_height(a.get_width());
            if (a.get_height() + a.margin_top + a.margin_bottom < want - 1) short.push([a.text.slice(0, 30), a.get_height(), want]); }
        a.get_children().forEach(walk); })(ros._list);
        return short.length ? JSON.stringify(short) : true;"
}
seen="$(ros_text "for (let i = 0; i < 60; i++) { if (ros._graph.services.some(s => s.name === '/trigger_test' && s.servers.length) &&
    ros._graph.topics.some(t => t.name === '/altitude')) return true; await sleep(250); } return false;")"
[ "$seen" = true ]; check $? "ros: a Trigger service is listed with its server"
ros_text "ros._expanded.add('section:services'); ros._render(); return true;" >/dev/null
# A request without fields (std_srvs/Trigger: take off, land) is called with one
# tap on its row; the row says how it went and does not unfold.
seen="$(ros_wait_for "'/trigger_test', 'Call'")"
[ "$seen" = true ]; check $? "ros: a service without request fields has Call on its row$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_press 'Call' true '/trigger_test')"; [ "$seen" = true ]; check $? "ros: one tap on Call, in place ($seen)"
seen="$(ros_wait_for "'✓ Taking off (1)'")"
[ "$seen" = true ]; check $? "ros: the row shows the reply's message$([ "$seen" = true ] || echo " ($seen)")"
sleep 1; grep -q "CALLED 1" "$SANDBOX/trigger.log" && ! grep -q "CALLED 2" "$SANDBOX/trigger.log"
check $? "ros: one tap made exactly one call"
[ "$(ros_text "return !ros._expanded.has('service:/trigger_test');")" = true ]
check $? "ros: tapping Call does not unfold the row"
seen="$(ros_text "for (let i = 0; i < 40; i++) { const b = ros._graph.services.find(x => x.name === '/trigger_refuse');
        if (b) { ros._quickCall(b); break; } await sleep(250); }
    for (let i = 0; i < 40; i++) { const t = labels(ros._list).join('|'); if (t.includes('✗ No /odom yet')) return true; await sleep(250); }
    return labels(ros._list).filter(t => t.includes('trigger_refuse') || t.includes('✓') || t.includes('✗')).join('|');")"
[ "$seen" = true ]; check $? "ros: a refusal (success: false) shows its message as a problem$([ "$seen" = true ] || echo " ($seen)")"
# Unfolded, the request form's Call also goes on the first tap when there is nothing to fill in.
seen="$(ros_press '/trigger_test' true)"; [ "$seen" = true ]; check $? "ros: clicking the service opens it, in place ($seen)"
seen="$(ros_press 'Call it')"; [ "$seen" = true ]; check $? "ros: Call it… opens the request, in place ($seen)"
seen="$(ros_wait_for "'This request has no fields'")"
[ "$seen" = true ]; check $? "ros: a request without fields says so$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_text "const { St } = imports.gi; const box = ros._list; let hit = null;
    (function walk(a) { if (hit) return; if (a instanceof St.Label && a.text === 'This request has no fields') { hit = a.get_parent(); return; }
        a.get_children().forEach(walk); })(box);
    if (!hit) return 'no form'; let call = null; (function walk(a) { if (call) return; if (a instanceof St.Button && a.label === 'Call') { call = a; return; }
        a.get_children().forEach(walk); })(hit);
    if (!call) return 'no Call in the form'; call.emit('clicked', 1);
    for (let i = 0; i < 40; i++) { if (labels(box).join('|').includes('Taking off (2)')) return true; await sleep(250); }
    return labels(box).filter(t => t.includes('Confirm') || t.includes('Taking off')).join('|');")"
[ "$seen" = true ]; check $? "ros: the form's Call sends on the first tap too$([ "$seen" = true ] || echo " ($seen)")"
grep -q "CALLED 2" "$SANDBOX/trigger.log" && ! grep -q "CALLED 3" "$SANDBOX/trigger.log"
check $? "ros: and makes exactly one call"
seen="$(ros_full_height)"
[ "$seen" = true ]; check $? "ros: the reply is shown whole, not squeezed to a line$([ "$seen" = true ] || echo " ($seen)")"
# A request that carries values is still confirmed first, and has no one-tap Call.
seen="$(ros_text "const s = ros._graph.services.find(x => x.name === '/add_test');
    if (!s) return 'no /add_test'; if (s.no_request !== false || ros._quickCallAction(s)) return 'offered one tap: ' + JSON.stringify(s);
    ros._composers.clear(); ros._toggleComposer('call:/add_test', 'service', s.types[0]);
    for (let i = 0; i < 40 && !(ros._composers.get('call:/add_test') || {}).fields; i++) await sleep(100);
    ros._send('call:/add_test', 'call', '/add_test', s.types[0]); await sleep(300);
    const armed = ros._isArmed('send:call:/add_test'); const c = ros._composers.get('call:/add_test');
    ros._disarm(); ros._composers.clear(); ros._render();
    return armed && !c.busy && !c.reply ? true : JSON.stringify({ armed, busy: c.busy, reply: c.reply });")"
[ "$seen" = true ]; check $? "ros: a request with fields still asks for a confirming click$([ "$seen" = true ] || echo " ($seen)")"
! grep -q "ADDED" "$SANDBOX/trigger.log"; check $? "ros: and nothing was sent before it"
# Only /chatter open, so its Preview is the one clicked; what was open comes back after.
ros_text "ros._composers.clear(); ros._savedExpanded = new Set(ros._expanded); ros._expanded.clear();
    ros._expanded.add('section:topics'); ros._expanded.add('topic:/chatter'); ros._render(); return true;" >/dev/null
seen="$(ros_press 'Preview' true)"; [ "$seen" = true ]; check $? "ros: Preview opens in place ($seen)"
seen="$(ros_wait_for "'std_msgs/msg/String', 'Hello World'")"
[ "$seen" = true ]; check $? "ros: Preview shows the next message$([ "$seen" = true ] || echo " ($seen)")"
seen="$(ros_full_height)"
[ "$seen" = true ]; check $? "ros: the preview is shown whole, not squeezed to a line$([ "$seen" = true ] || echo " ($seen)")"
# Without PlotJuggler, Plot is the panel's own: Plot, the field list, a field.
ros_text "ros._hasPlotJuggler = () => false;
    ros._samples.clear(); ros._expanded.delete('topic:/chatter'); ros._expanded.add('topic:/altitude'); ros._render(); return true;" >/dev/null
seen="$(ros_press 'Plot' true)"; [ "$seen" = true ]; check $? "ros: Plot offers the fields, in place ($seen)"
seen="$(ros_press 'Plot field /altitude')"; [ "$seen" = true ]; check $? "ros: the field list opens, in place ($seen)"
seen="$(ros_text "const { St } = imports.gi; let hit = null; (function walk(a) { if (hit) return;
        if (a instanceof St.Button && a.label === 'data' && a.is_mapped()) { hit = a; return; } a.get_children().forEach(walk); })(ros._list);
    return hit && hit.get_height() >= 10 ? true : 'choice ' + (hit ? 'squeezed to ' + hit.get_height() + ' px' : 'missing');")"
[ "$seen" = true ]; check $? "ros: the field list shows its choices$([ "$seen" = true ] || echo " ($seen)")"
probe "$SLEEP $ROS $PRESS return (async () => JSON.stringify(await press('data', true)))();" >/dev/null
seen="$(ros_text "for (let i = 0; i < 40; i++) { const b = ros._blocks.get('plot'); const adj = ros._scroll.vscroll.adjustment;
        if (ros._plot && ros._plot.field === 'data' && ros._plot.values.length >= 3 && b &&
            b.actor.get_y() >= adj.value && b.actor.get_y() < adj.value + adj.page_size) return true; await sleep(250); }
    return JSON.stringify({ plot: ros._plot && ros._plot.field, values: ros._plot && ros._plot.values.length });")"
[ "$seen" = true ]; check $? "ros: choosing a field plots it, scrolled into view$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._stopPlot(); delete ros._hasPlotJuggler; ros._render(); return true;" >/dev/null
# With PlotJuggler: Plot opens it on that one topic; topics picked on their rows open together.
# The helper's answer is stood in for, so no PlotJuggler window opens in the sandbox.
ros_text "ros._helperReal = ros._helper; ros._plotJuggler = [];
    ros._helper = (args, done) => { if (args[0] !== 'plotjuggler') return ros._helperReal(args, done);
        ros._plotJuggler.push(args.slice(1)); done({ ok: true, pids: [], topics: args.slice(1) }); };
    ros._status.tools.plotjuggler = { installed: true, pids: [], owned_pids: [], external_pids: [] };
    ros._expanded.delete('topic:/altitude'); ros._expanded.add('topic:/chatter'); ros._render(); return true;" >/dev/null
ros_reopen() { ros_text "Main.panel.statusArea['adaptive-ros'].menu.open(); await sleep(600); return true;" >/dev/null; }
seen="$(ros_press 'Plot' true)"
seen="$(ros_text "const last = ros._plotJuggler[ros._plotJuggler.length - 1];
    return JSON.stringify(last) === JSON.stringify(['/chatter']) && !ros._button.menu.isOpen || JSON.stringify({ calls: ros._plotJuggler, open: ros._button.menu.isOpen });")"
[ "$seen" = true ]; check $? "ros: Plot opens PlotJuggler on exactly that topic$([ "$seen" = true ] || echo " ($seen)")"
ros_reopen
ros_text "ros._expanded.delete('topic:/chatter'); ros._render(); return true;" >/dev/null
seen="$(ros_press 'Add /chatter to the PlotJuggler set' true)"; [ "$seen" = true ]; check $? "ros: a topic is picked for PlotJuggler on its row, in place ($seen)"
# The second one far down the list: the set and Open stay in view below the list.
ros_text "const adj = ros._scroll.vscroll.adjustment; adj.value = adj.upper - adj.page_size; await sleep(300); return true;" >/dev/null
seen="$(ros_press 'Add /lifecycle_chatter to the PlotJuggler set' true)"; [ "$seen" = true ]; check $? "ros: a second topic is picked, in place ($seen)"
seen="$(ros_text "for (let i = 0; i < 20; i++) { const t = labels(ros._footer).join('|');
        const [, y] = ros._footer.get_transformed_position();
        if (ros._footer.visible && ros._footer.is_mapped() && y > 0 && y + ros._footer.height <= global.stage.height &&
            ['PlotJuggler · 2 topics', '/chatter and /lifecycle_chatter', 'Open in PlotJuggler', 'Clear'].every(w => t.includes(w))) return true;
        await sleep(250); } return labels(ros._footer).join('|') + ' visible ' + ros._footer.visible;")"
[ "$seen" = true ]; check $? "ros: the picked set and Open stay in view below the list$([ "$seen" = true ] || echo " ($seen)")"
probe "$SLEEP $ROS $PRESS return (async () => JSON.stringify(await press('Open in PlotJuggler', true, 'PlotJuggler · 2 topics')))();" >/dev/null
seen="$(ros_text "await sleep(300); const last = ros._plotJuggler[ros._plotJuggler.length - 1];
    return JSON.stringify(last) === JSON.stringify(['/chatter', '/lifecycle_chatter']) || JSON.stringify(ros._plotJuggler);")"
[ "$seen" = true ]; check $? "ros: Open sends exactly the picked topics to PlotJuggler$([ "$seen" = true ] || echo " ($seen)")"
ros_reopen
probe "$SLEEP $ROS $PRESS return (async () => JSON.stringify(await press('Clear', true, 'PlotJuggler · 2 topics')))();" >/dev/null
seen="$(ros_text "await sleep(300); return !ros._plotTopics.size && !ros._footer.visible || JSON.stringify([...ros._plotTopics]);")"
[ "$seen" = true ]; check $? "ros: Clear empties the set and the bar goes$([ "$seen" = true ] || echo " ($seen)")"
ros_text "ros._helper = ros._helperReal; delete ros._helperReal; ros._expanded = ros._savedExpanded; delete ros._savedExpanded;
    ros._loadStatus(); ros._render(); return true;" >/dev/null
kill "$TRIGGER" 2>/dev/null

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

# New package: the dialog, step by step, makes a real package in the sandbox's ~/ros2_ws.
# ADAPTIVE_ROS_WIZARD_SHOTS=<dir> also saves a picture of each step.
WIZ='const wiz = () => ros._packageDialog; const find = (a, test) => { let hit = null; (function walk(x) { if (hit) return;
    if (test(x)) { hit = x; return; } x.get_children().forEach(walk); })(a); return hit; };
const button = text => find(wiz(), x => x instanceof imports.gi.St.Button && (x.label === text || x.accessible_name === text));
const shot = name => new Promise(resolve => { const dir = "'"${ADAPTIVE_ROS_WIZARD_SHOTS:-}"'"; if (!dir) { resolve(); return; }
    const { Gio, Shell } = imports.gi; const stream = Gio.File.new_for_path(dir + "/" + name + ".png").replace(null, false, Gio.FileCreateFlags.NONE, null);
    new Shell.Screenshot().screenshot(false, stream, (s, r) => { s.screenshot_finish(r); stream.close(null); resolve(); }); });
const until = async (words, tries = 40) => { for (let i = 0; i < tries; i++) { const t = wiz() ? labels(wiz()).join("|") : "";
    if (words.every(w => t.includes(w))) return true; await sleep(250); } return wiz() ? labels(wiz()).join("|").slice(0, 600) : "no dialog"; };'
wiz_text() { ros_text "$WIZ $1"; }
[ -n "${ADAPTIVE_ROS_WIZARD_SHOTS:-}" ] && mkdir -p "$ADAPTIVE_ROS_WIZARD_SHOTS"
seen="$(ros_wait_for "'New package', 'Create…'")"
[ "$seen" = true ]; check $? "ros: Launch offers New package$([ "$seen" = true ] || echo " ($seen)")"
seen="$(wiz_text "ros.newPackage(); const r = await until(['1  Template', 'C++ node', 'Python node', 'C++ component', 'Interfaces', 'Launch & config']);
    await sleep(400); await shot('1-template'); return r === true && !ros._button.menu.isOpen ? true : r;")"
[ "$seen" = true ]; check $? "ros: New package opens the dialog on its templates, the panel closed$([ "$seen" = true ] || echo " ($seen)")"
seen="$(wiz_text "button('Python node').emit('clicked', 0); button('Next').emit('clicked', 0);
    const r = await until(['2  Configure', 'Package name', 'Node name', 'Location', '~/ros2_ws/src', 'Licence', 'Apache-2.0']);
    if (r !== true) return r; const next = button('Next'); if (next.reactive) return 'Next works without a name';
    find(wiz(), x => x instanceof imports.gi.St.Entry && x.hint_text === 'my_robot_driver').set_text('Bad-Name');
    await sleep(200); if (!labels(wiz()).includes('Start with a lowercase letter')) return labels(wiz()).join('|');
    find(wiz(), x => x instanceof imports.gi.St.Entry && x.hint_text === 'my_robot_driver').set_text('nested_pkg');
    await sleep(200); const t = labels(wiz()).join('|');
    if (!t.includes('~/ros2_ws/src/nested_pkg') || !button('Next').reactive) return t;
    if (find(wiz(), x => x instanceof imports.gi.St.Entry && x.hint_text === 'my_node').get_text() !== 'nested_pkg_node') return 'node name';
    await shot('2-configure'); return true;")"
[ "$seen" = true ]; check $? "ros: Configure checks the name as it is typed and names the node after it$([ "$seen" = true ] || echo " ($seen)")"
seen="$(wiz_text "button('Next').emit('clicked', 0);
    const r = await until(['3  Dependencies', 'The package depends on · 2', 'rclpy', 'std_msgs', 'Recommended', 'geometry_msgs']);
    if (r !== true) return r; await shot('3-dependencies');
    button('Add geometry_msgs').emit('clicked', 0);
    const r2 = await until(['The package depends on · 3']); if (r2 !== true) return r2;
    if (button('Remove rclpy')) return 'the template dependency can be removed';
    button('Remove std_msgs').emit('clicked', 0); return await until(['The package depends on · 2']);")"
[ "$seen" = true ]; check $? "ros: Dependencies moves packages between the two lists; the template's stay$([ "$seen" = true ] || echo " ($seen)")"
seen="$(wiz_text "button('Next').emit('clicked', 0);
    const r = await until(['4  Review', 'nested_pkg/', 'nested_pkg/nested_pkg_node.py', 'ros2 pkg create nested_pkg', 'geometry_msgs']);
    if (r !== true) return r; await shot('4-review');
    const build = find(wiz(), x => x instanceof imports.gi.St.Button && (x.label || '').includes('Build it now'));
    if (build && build.label.startsWith('✓')) build.emit('clicked', 0);
    await sleep(200);
    // The panel keeps its workspace, so the checks after this one see the same setup.
    const use = find(wiz(), x => x instanceof imports.gi.St.Button && (x.label || '').includes('Use ~/ros2_ws'));
    if (use && use.label.startsWith('✓')) use.emit('clicked', 0);
    await sleep(200); button('Create').emit('clicked', 0);
    const done = await until(['nested_pkg is ready'], 120); await shot('5-done'); return done;")"
[ "$seen" = true ]; check $? "ros: Create makes the package and says so$([ "$seen" = true ] || echo " ($seen)")"
grep -q '<depend>geometry_msgs</depend>' "$HOME/ros2_ws/src/nested_pkg/package.xml" 2>/dev/null &&
    ! grep -q '<depend>std_msgs</depend>' "$HOME/ros2_ws/src/nested_pkg/package.xml"
check $? "ros: the package is in ~/ros2_ws/src with exactly the chosen dependencies"
seen="$(wiz_text "button('Done').emit('clicked', 0); for (let i = 0; i < 20 && wiz(); i++) await sleep(200);
    Main.panel.statusArea['adaptive-ros'].menu.open(); await sleep(400);
    return !wiz() && labels(ros._list).join('|').includes('Created nested_pkg in ~/ros2_ws/src/nested_pkg') ? true
        : labels(ros._list).join('|').slice(0, 400);")"
[ "$seen" = true ]; check $? "ros: Done closes the dialog and the panel names the new package$([ "$seen" = true ] || echo " ($seen)")"

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
