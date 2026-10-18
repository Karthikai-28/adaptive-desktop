#!/usr/bin/env python3
"""A notification server for a sandbox's session bus, for the checks.

A bare dbus-run-session has nothing that owns org.freedesktop.Notifications,
so notify-send is refused before the call is ever sent, and nothing watching
the bus sees a notification. This takes the name and accepts every
notification, showing none. Runs until killed.
"""

from gi.repository import Gio, GLib

XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/>
    </method>
    <method name="CloseNotification"><arg type="u" direction="in"/></method>
    <method name="GetCapabilities"><arg type="as" direction="out"/></method>
    <method name="GetServerInformation">
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
    </method>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
  </interface>
</node>
"""

count = 0


def call(_connection, _sender, _path, _interface, method, _parameters, invocation):
    global count
    if method == "Notify":
        count += 1
        invocation.return_value(GLib.Variant("(u)", (count,)))
    elif method == "GetCapabilities":
        invocation.return_value(GLib.Variant("(as)", (["body", "actions"],)))
    elif method == "GetServerInformation":
        invocation.return_value(GLib.Variant("(ssss)", ("fake", "adaptive-desktop", "1", "1.2")))
    else:
        invocation.return_value(None)


def acquired(connection, _name):
    connection.register_object("/org/freedesktop/Notifications",
                               Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)


Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications",
                 Gio.BusNameOwnerFlags.NONE, acquired, None, None)
GLib.MainLoop().run()
