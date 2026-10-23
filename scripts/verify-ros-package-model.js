#!/usr/bin/env node
// The New package dialog's decisions (shell/.../rosPackageModel.js): name checks,
// the dependencies a template starts with, the two dependency columns, and the
// files and command the review shows.

const M = require('../shell/adaptive-shell@local/rosPackageModel.js');

let failed = 0;
function check(value, message) {
    if (value) {
        console.log(`OK   ros package model: ${message}`);
    } else {
        console.error(`FAIL ros package model: ${message}`);
        failed++;
    }
}

const cppNode = { id: 'cpp_node', build_type: 'ament_cmake', required: ['rclcpp'], suggested: ['std_msgs'],
    fields: ['node_name'] };
const pyNode = { id: 'python_node', build_type: 'ament_python', required: ['rclpy'], suggested: ['std_msgs'],
    fields: ['node_name'] };
const interfaces = { id: 'interfaces', build_type: 'ament_cmake', fields: ['interfaces'],
    required: ['rosidl_default_generators', 'rosidl_default_runtime'], suggested: [] };
const catalog = { distro: 'humble', taken: ['robot_lab_core'], shadowed: ['turtlesim'] };
const rows = [
    { name: 'rclcpp', category: 'Core', description: 'C++ client library', installed: true },
    { name: 'rclpy', category: 'Core', description: 'Python client library', installed: true },
    { name: 'std_msgs', category: 'Messages', description: 'Basic types', installed: true },
    { name: 'geometry_msgs', category: 'Messages', description: 'Poses and twists', installed: true },
    { name: 'nav2_msgs', category: 'Navigation', description: 'Navigation 2', installed: false },
    { name: 'rclcpp_components', category: 'Core', description: 'Composable nodes', installed: true },
    { name: 'tf2_ros', category: 'TF & robot model', description: 'TF listeners', installed: true },
    { name: 'turtlesim', category: 'Other installed', description: 'A turtle', installed: true },
];

check(M.validateName('my_robot', catalog, cppNode).ok, 'a plain name is fine');
for (const [bad, why] of [['MyRobot', 'upper case'], ['1robot', 'a leading digit'], ['my-robot', 'a dash'],
    ['my__robot', 'a double underscore'], ['robot_', 'a trailing underscore'], ['robot_lab_core', 'a taken name'],
    ['a'.repeat(65), 'a long name']])
    check(!M.validateName(bad, catalog, cppNode).ok && M.validateName(bad, catalog, cppNode).error, `refuses ${why}`);
check(!M.validateName('class', catalog, pyNode).ok && M.validateName('class', catalog, cppNode).ok,
    'a Python keyword is refused only for Python packages');
check(!M.validateName('', catalog, cppNode).ok && M.validateName('', catalog, cppNode).error === '',
    'an empty name blocks Next without shouting');
const shadow = M.validateName('turtlesim', catalog, cppNode);
check(shadow.ok && /hide/.test(shadow.warning), 'a name ROS already has warns but is allowed');
check(M.validateIdentifier('talker_2') && !M.validateIdentifier('2talker') && !M.validateIdentifier('my-node'),
    'node names are identifiers');
check(M.validateEmail('') && M.validateEmail('a@b.c') && !M.validateEmail('nobody'), 'email is optional but checked');

check(JSON.stringify(M.initialSelection(cppNode, rows)) === '["rclcpp","std_msgs"]',
    'a C++ node starts with rclcpp and std_msgs');
check(JSON.stringify(M.initialSelection(interfaces, rows)) === '["rosidl_default_generators","rosidl_default_runtime"]',
    'interfaces start with the rosidl packages');

let left = M.availableDependencies(rows, { selected: ['rclcpp', 'std_msgs'], template: cppNode });
check(left.rows[0].name === 'geometry_msgs' && !left.rows.some(r => r.name === 'std_msgs'),
    'Recommended leaves out what is selected, in the recommended order');
left = M.availableDependencies(rows, { selected: ['rclpy'], template: pyNode });
check(!left.rows.some(r => r.name === 'rclcpp_components'), 'a Python package is not offered C++-only packages');
left = M.availableDependencies(rows, { category: 'Navigation', selected: [], template: cppNode });
check(left.rows.length === 1 && left.rows[0].name === 'nav2_msgs', 'a category lists only its packages');
left = M.availableDependencies(rows, { query: 'msgs', selected: ['std_msgs'], template: cppNode });
check(left.rows.map(r => r.name).join() === 'geometry_msgs,nav2_msgs,msgs' && left.rows[2].custom,
    'a search spans every category, installed first, the typed text last');
left = M.availableDependencies(rows, { query: 'poses', selected: [], template: cppNode });
check(left.rows[0].name === 'geometry_msgs' && left.rows.filter(r => !r.custom).length === 1, 'a search matches descriptions too');
left = M.availableDependencies(rows, { query: 'my_custom_pkg', selected: [], template: cppNode });
check(left.rows[0].custom && left.rows[0].name === 'my_custom_pkg', 'a name not listed can be added as typed');
check(!M.availableDependencies(rows, { query: 'bad name!', selected: [] }).rows.some(r => r.custom),
    'only a valid package name is offered as typed');
check(M.availableDependencies(rows, { category: 'All', selected: [], limit: 3 }).more === rows.length - 3,
    'a long list says how many more there are');

const right = M.selectedDependencies(rows, ['rclcpp', 'nav2_msgs', 'mystery'], cppNode);
check(right[0].required && !right[1].required && right[2].installed === false, 'the template\'s own ones are fixed');
check(M.missingDependencies(rows, ['rclcpp', 'nav2_msgs', 'mystery']).join() === 'nav2_msgs,mystery',
    'not installed ones are named');

const state = { template: cppNode, name: 'driver', nodeName: '', location: 'src', description: 'A driver',
    maintainerName: 'Me', maintainerEmail: '', license: 'Apache-2.0', interfaces: ['msg'],
    selected: ['rclcpp', 'std_msgs'], build: true, useWorkspace: false };
const spec = M.specFor(state);
check(spec.node_name === 'driver_node' && spec.template === 'cpp_node' && !('interfaces' in spec),
    'the spec carries the node name the form implies');
check(M.filesFor(spec, cppNode).join() === 'CMakeLists.txt,package.xml,LICENSE,include/driver/,src/driver_node.cpp',
    'the review lists the C++ node\'s files');
check(!M.filesFor({ ...spec, license: 'Proprietary' }, cppNode).includes('LICENSE'),
    'no LICENSE file for a licence ros2 pkg create does not know');
check(M.filesFor({ name: 'ifaces', interfaces: ['srv', 'action'] }, interfaces).join().includes('srv/Command.srv,action/Task.action'),
    'interfaces list the starters picked');
check(M.filesFor({ name: 'py', node_name: 'n' }, pyNode).includes('py/n.py'), 'a Python node lists its module');
const command = M.commandFor(spec, cppNode, '/home/me/ros2_ws/src');
check(command === 'ros2 pkg create driver --build-type ament_cmake --destination-directory /home/me/ros2_ws/src ' +
    '--license Apache-2.0 --node-name driver_node --dependencies rclcpp std_msgs', 'the review shows the command');
check(!M.commandFor({ name: 'i', license: 'MIT', dependencies: ['rosidl_default_generators'] }, interfaces, '/w')
    .includes('--dependencies'), 'interfaces pass their dependencies through CMake, not the command');

if (failed) {
    console.error(`${failed} ros package model check(s) failed`);
    process.exit(1);
}
