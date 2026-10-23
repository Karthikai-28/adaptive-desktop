// What the ROS 2 panel's New package dialog decides, free of GJS imports so
// scripts/verify-ros-package-model.js can check it under node: name checks,
// which dependencies start selected, the dependency list for a search, and the
// files and command a review shows. The helper (`ros_info.py pkg-create`)
// checks everything again; these are for answering while one types.

/* exported STEPS, RECOMMENDED, validateName, validateIdentifier, validateEmail,
   initialSelection, availableDependencies, selectedDependencies, missingDependencies, filesFor, commandFor,
   specFor, hasField */
/* global module */

var STEPS = ['Template', 'Configure', 'Dependencies', 'Review'];

// Offered first under "Recommended", after the template's own suggestions.
var RECOMMENDED = ['std_msgs', 'geometry_msgs', 'sensor_msgs', 'nav_msgs', 'std_srvs', 'tf2_ros',
    'tf2_geometry_msgs', 'visualization_msgs', 'rclcpp_components', 'launch_ros', 'ament_index_cpp',
    'ament_index_python', 'cv_bridge', 'message_filters', 'diagnostic_updater'];

const PYTHON_KEYWORDS = new Set(['False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break',
    'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if',
    'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while',
    'with', 'yield']);
const SUPPORTED_LICENSE_FILES = new Set(['Apache-2.0', 'BSL-1.0', 'BSD-2.0', 'BSD-2-Clause', 'BSD-3-Clause',
    'GPL-3.0-only', 'LGPL-3.0-only', 'MIT', 'MIT-0']);

function hasField(template, field) {
    return !!template && (template.fields || []).includes(field);
}

// { ok, error, warning } for a package name typed into the form.
function validateName(name, catalog, template) {
    if (!name)
        return { ok: false, error: '' };
    if (!/^[a-z]/.test(name))
        return { ok: false, error: 'Start with a lowercase letter' };
    if (!/^[a-z][a-z0-9_]*$/.test(name))
        return { ok: false, error: 'Use lowercase letters, digits and _ only' };
    if (name.includes('__'))
        return { ok: false, error: 'No double underscores' };
    if (name.endsWith('_'))
        return { ok: false, error: 'Do not end with _' };
    if (name.length > 64)
        return { ok: false, error: 'At most 64 characters' };
    if (template && template.build_type === 'ament_python' && PYTHON_KEYWORDS.has(name))
        return { ok: false, error: `${name} is a Python keyword` };
    if (catalog && (catalog.taken || []).includes(name))
        return { ok: false, error: `~/ros2_ws already has a package named ${name}` };
    if (catalog && (catalog.shadowed || []).includes(name))
        return { ok: true, warning: `ROS 2 ${catalog.distro} already has ${name}; yours would hide it` };
    return { ok: true };
}

// A node or library name: a C and Python identifier.
function validateIdentifier(text) {
    return /^[A-Za-z_][A-Za-z0-9_]*$/.test(text);
}

function validateEmail(text) {
    return !text || /^[^@\s]+@[^@\s]+$/.test(text);
}

// What the template needs, then what it suggests (when it is offered at all).
function initialSelection(template, rows) {
    const known = new Set((rows || []).map(r => r.name));
    const picked = [...(template.required || [])];
    for (const name of template.suggested || []) {
        if (!picked.includes(name) && (!rows || known.has(name)))
            picked.push(name);
    }
    return picked;
}

function _recommendedNames(template) {
    const names = [...(template.suggested || [])];
    const python = template.build_type === 'ament_python';
    for (const name of RECOMMENDED) {
        // A Python package has no use for the C++-only ones.
        if (python && /(_cpp|_components)$/.test(name))
            continue;
        if (!names.includes(name))
            names.push(name);
    }
    return names;
}

// The left column: not yet selected, in the category, matching the search.
// Within a category the catalog's order is kept; a search puts names that start
// with it first. A search that names no listed package also offers to add it as typed.
function availableDependencies(rows, { query = '', category = 'Recommended', selected = [], template = null,
    limit = 150 } = {}) {
    const chosen = new Set(selected);
    const text = query.trim().toLowerCase();
    let pool = rows.filter(r => !chosen.has(r.name));
    if (!text) {
        if (category === 'Recommended' && template) {
            const order = _recommendedNames(template);
            pool = order.map(name => pool.find(r => r.name === name)).filter(Boolean);
        } else if (category !== 'All') {
            pool = pool.filter(r => r.category === category);
        }
    } else {
        pool = pool.filter(r => r.name.toLowerCase().includes(text) ||
            (r.description || '').toLowerCase().includes(text));
        const rank = r => (r.name.toLowerCase() === text ? 0 : r.name.toLowerCase().startsWith(text) ? 1
            : r.name.toLowerCase().includes(text) ? 2 : 3) + (r.installed ? 0 : 0.5);
        pool = pool.map((r, i) => [r, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(p => p[0]);
    }
    const typed = query.trim();
    const custom = typed && /^[A-Za-z][A-Za-z0-9_]*$/.test(typed) && !chosen.has(typed) &&
        !rows.some(r => r.name === typed)
        ? { name: typed, category: 'Typed', description: 'Not in the list: added as typed', installed: false,
            custom: true }
        : null;
    // Last, so Enter still adds the best listed match; first only when nothing is listed.
    const shown = pool.slice(0, limit).concat(custom ? [custom] : []);
    return { rows: shown, more: Math.max(0, pool.length - limit) };
}

// The right column, in the order picked, with why each one is there.
function selectedDependencies(rows, selected, template) {
    const required = new Set((template && template.required) || []);
    return selected.map(name => {
        const row = rows.find(r => r.name === name) || { name, installed: false, description: '' };
        return { ...row, required: required.has(name) };
    });
}

function missingDependencies(rows, selected) {
    return selectedDependencies(rows, selected, null).filter(r => !r.installed).map(r => r.name);
}

// The files the review lists, as `ros2 pkg create` and the template leave them.
function filesFor(spec, template) {
    const name = spec.name || 'my_package';
    const node = spec.node_name || `${name}_node`;
    const license = SUPPORTED_LICENSE_FILES.has(spec.license) ? ['LICENSE'] : [];
    const python = ['package.xml', 'setup.py', 'setup.cfg', `resource/${name}`, `${name}/__init__.py`,
        'test/test_copyright.py', 'test/test_flake8.py', 'test/test_pep257.py'];
    switch (template && template.id) {
    case 'cpp_node':
        return ['CMakeLists.txt', 'package.xml', ...license, `include/${name}/`, `src/${node}.cpp`];
    case 'python_node':
        return [...python.slice(0, 5), `${name}/${node}.py`, ...python.slice(5), ...license];
    case 'cpp_component':
        return ['CMakeLists.txt', 'package.xml', ...license, `include/${name}/`, `src/${node}.cpp`];
    case 'cpp_library': {
        const lib = spec.library_name || name;
        return ['CMakeLists.txt', 'package.xml', ...license, `include/${name}/${lib}.hpp`,
            `include/${name}/visibility_control.h`, `src/${lib}.cpp`];
    }
    case 'interfaces': {
        const starters = { msg: 'msg/Status.msg', srv: 'srv/Command.srv', action: 'action/Task.action' };
        const kinds = (spec.interfaces || ['msg']).filter(k => starters[k]);
        return ['CMakeLists.txt', 'package.xml', ...license, ...(kinds.length ? kinds : ['msg']).map(k => starters[k])];
    }
    case 'bringup':
        return ['CMakeLists.txt', 'package.xml', ...license, `config/params.yaml`, `launch/${name}.launch.py`];
    case 'empty_python':
        return [...python, ...license];
    default:
        return ['CMakeLists.txt', 'package.xml', ...license, `include/${name}/`, 'src/'];
    }
}

function _quote(text) {
    return /^[\w@%+=:,./-]+$/.test(text) ? text : `'${text.replace(/'/g, "'\\''")}'`;
}

// The `ros2 pkg create` line the review shows (the template then adds its files).
function commandFor(spec, template, locationPath) {
    const parts = ['ros2', 'pkg', 'create', spec.name || 'my_package', '--build-type', template.build_type,
        '--destination-directory', locationPath, '--license', spec.license || 'Apache-2.0'];
    if (template.id === 'cpp_node' || template.id === 'python_node')
        parts.push('--node-name', spec.node_name || `${spec.name}_node`);
    if (template.id === 'cpp_library')
        parts.push('--library-name', spec.library_name || spec.name);
    const deps = (spec.dependencies || []).filter(d => template.id !== 'interfaces' ||
        !(template.required || []).includes(d));
    if (deps.length && template.id !== 'interfaces')
        parts.push('--dependencies', ...deps);
    return parts.map(_quote).join(' ');
}

// The JSON `pkg-create` takes, from the dialog's state.
function specFor(state) {
    const template = state.template;
    const spec = {
        name: state.name, template: template.id, location: state.location,
        description: state.description, maintainer_name: state.maintainerName,
        maintainer_email: state.maintainerEmail, license: state.license,
        dependencies: state.selected.slice(), build: !!state.build, use_workspace: !!state.useWorkspace,
    };
    if (hasField(template, 'node_name'))
        spec.node_name = state.nodeName || `${state.name}_node`;
    if (hasField(template, 'library_name'))
        spec.library_name = state.libraryName || state.name;
    if (hasField(template, 'interfaces'))
        spec.interfaces = state.interfaces.slice();
    return spec;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { STEPS, RECOMMENDED, validateName, validateIdentifier, validateEmail, initialSelection,
        availableDependencies, selectedDependencies, missingDependencies, filesFor, commandFor, specFor, hasField };
}
