#!/usr/bin/env python3
"""Exercise real controller service types on an isolated domain, with a fixture manager.
Run in a sourced ROS environment; an extracted controller_manager_msgs prefix also works.
No hardware controllers or system package changes are involved.
"""
import importlib.util
import os
from pathlib import Path

os.environ.update(ROS_DOMAIN_ID='89', ROS_LOCALHOST_ONLY='1')
import rclpy
from rclpy.node import Node
from controller_manager_msgs.srv import (ConfigureController, LoadController, UnloadController, SwitchController)

spec = importlib.util.spec_from_file_location('ros_info', Path(__file__).resolve().parents[1] /
    'shell/adaptive-shell@local/tools/ros_info.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
rclpy.init()
server = Node('fixture_controller_manager')
states = {}

def operation(op):
    def invoke(req, reply):
        if op == 'load':
            reply.ok = req.name not in states
            if reply.ok: states[req.name] = 'unconfigured'
        elif op == 'configure':
            reply.ok = states.get(req.name) == 'unconfigured'
            if reply.ok: states[req.name] = 'inactive'
        else:
            reply.ok = states.get(req.name) in ('inactive', 'unconfigured')
            if reply.ok: del states[req.name]
        return reply
    return invoke

def switch(req, reply):
    on = getattr(req, 'activate_controllers', getattr(req, 'start_controllers', []))
    off = getattr(req, 'deactivate_controllers', getattr(req, 'stop_controllers', []))
    reply.ok = req.strictness == SwitchController.Request.STRICT and all(n in states for n in [*on, *off])
    if reply.ok:
        for n in on: states[n] = 'active'
        for n in off: states[n] = 'inactive'
    return reply

for op, kind in [('load', LoadController), ('configure', ConfigureController), ('unload', UnloadController)]:
    server.create_service(kind, f'/controller_manager/{op}_controller', operation(op))
server.create_service(SwitchController, '/controller_manager/switch_controller', switch)
from rclpy.executors import SingleThreadedExecutor
executor = SingleThreadedExecutor()
executor.add_node(server)
watch = helper.Watcher.__new__(helper.Watcher)
watch.node = Node('_controller_test_client')
executor.add_node(watch.node)
watch.jobs = []
replies = []
helper.emit = replies.append
try:
    import time
    for op, expected in [('load', 'unconfigured'), ('configure', 'inactive'), ('activate', 'active'),
                         ('deactivate', 'inactive'), ('unload', None)]:
        replies.clear()
        watch.controller(1, '/controller_manager', 'test_controller', op)
        deadline = time.monotonic() + 8
        while not replies and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)
            watch.jobs = [job for job in watch.jobs if not job.step()]
        assert replies and replies[-1].get('ok'), (op, replies)
        assert states.get('test_controller') == expected, states
        print(f'OK {op}: {expected}')
    watch.controller(2, '/controller_manager', 'missing', 'activate')
    deadline = time.monotonic() + 8
    while len(replies) < 2 and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.05)
        watch.jobs = [job for job in watch.jobs if not job.step()]
    assert replies[-1].get('error'), replies
    print('OK rejected switch is reported')
finally:
    rclpy.shutdown()
    executor.shutdown()
    watch.node.destroy_node()
    server.destroy_node()
