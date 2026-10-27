"""The laptop's keyring, reachable from a phone session's own bus.

A phone session has a session bus of its own (mobile_session.py), so an app
started there never finds its laptop copy and hands itself over to it. Apps
that share the laptop's profile still need the laptop's keyring, though:
Chrome, VS Code and its relatives keep the key to their saved logins in the
Secret Service (org.freedesktop.secrets). This owns that one name on the
phone's bus and passes every call to it, and every signal from it, to the
laptop's bus unchanged. Nothing else on the laptop's bus is reachable.

    secrets_bridge.py PHONE_BUS_ADDRESS   (the laptop's bus is the environment's)

Prints "ready" once it owns the name; ends when the phone's bus does.
"""
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

NAME = "org.freedesktop.secrets"
# A prompt (unlocking the keyring) answers at once and finishes by a signal,
# so no call waits on a person; this is only a ceiling.
TIMEOUT = 120_000


def bridge(laptop, phone):
    unique = phone.get_unique_name()

    def answer(message, reply):
        if reply.get_message_type() == Gio.DBusMessageType.ERROR:
            body = reply.get_body()
            text = body.get_child_value(0).get_string() if body is not None and body.n_children() and \
                body.get_child_value(0).is_of_type(GLib.VariantType("s")) else ""
            return Gio.DBusMessage.new_method_error_literal(message, reply.get_error_name() or "org.freedesktop.DBus.Error.Failed", text)
        out = Gio.DBusMessage.new_method_reply(message)
        if reply.get_body() is not None:
            out.set_body(reply.get_body())
        return out

    def forward(message):
        call = Gio.DBusMessage.new_method_call(NAME, message.get_path(), message.get_interface(), message.get_member())
        if message.get_body() is not None:
            call.set_body(message.get_body())
        if message.get_flags() & Gio.DBusMessageFlags.NO_REPLY_EXPECTED:
            call.set_flags(Gio.DBusMessageFlags.NO_REPLY_EXPECTED)
            laptop.send_message(call, Gio.DBusSendMessageFlags.NONE)
            return False

        def done(connection, result):
            try:
                out = answer(message, connection.send_message_with_reply_finish(result))
            except GLib.Error as error:
                out = Gio.DBusMessage.new_method_error_literal(message, "org.freedesktop.DBus.Error.Failed", error.message)
            phone.send_message(out, Gio.DBusSendMessageFlags.NONE)
        laptop.send_message_with_reply(call, Gio.DBusSendMessageFlags.NONE, TIMEOUT, None, done)
        return False

    def incoming(connection, message, is_incoming):
        if not is_incoming or message.get_message_type() != Gio.DBusMessageType.METHOD_CALL \
                or message.get_destination() not in (NAME, unique):
            return message
        # Filters run on GDBus's own thread; replies are handled on the main loop.
        GLib.idle_add(forward, message)
        return None

    phone.add_filter(incoming)

    def signal(connection, sender, path, interface, member, parameters):
        phone.emit_signal(None, path, interface, member, parameters)
    laptop.signal_subscribe(NAME, None, None, None, None, Gio.DBusSignalFlags.NONE, signal)


def main():
    laptop = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    phone = Gio.DBusConnection.new_for_address_sync(
        sys.argv[1], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    loop = GLib.MainLoop()
    phone.connect("closed", lambda *_: loop.quit())
    laptop.connect("closed", lambda *_: loop.quit())
    bridge(laptop, phone)
    # 4: do not queue. Anything already holding the name keeps it.
    owned = phone.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", (NAME, 4)), GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
    if owned.unpack()[0] != 1:
        sys.exit(1)
    print("ready", flush=True)
    loop.run()


if __name__ == "__main__":
    main()
