"""Wi-Fi Direct through NetworkManager: find TVs, join one, leave.

NetworkManager owns wpa_supplicant, so a P2P group is just another
connection on the p2p-dev-* device. The connection is volatile: it is not
saved and disappears when deactivated, so nothing is left in Settings.
"""

import uuid

import gi

gi.require_version("NM", "1.0")
from gi.repository import GLib, NM  # noqa: E402

import wfd  # noqa: E402

FIND_SECONDS = 30


class Display:
    """A Wi-Fi Direct peer that says it can show a Miracast stream."""

    def __init__(self, peer):
        self.peer = peer
        ies = peer.get_wfd_ies()
        self.ies = wfd.parse_ies(ies.get_data() if ies else b"")

    @property
    def name(self):
        return self.peer.get_name() or self.peer.get_hw_address()

    @property
    def address(self):
        return self.peer.get_hw_address()

    @property
    def strength(self):
        return self.peer.get_strength()

    @property
    def available(self):
        return self.ies.get("session_available", False)


class WifiDirect:
    """Finds displays and runs one connection at a time.

    on_displays(list[Display]) fires whenever the list changes.
    on_link(state, text) fires with connecting / connected / disconnected / failed.
    """

    def __init__(self, on_displays, on_link, log=print):
        self.on_displays = on_displays
        self.on_link = on_link
        self.log = log
        self.client = NM.Client.new(None)
        self.device = next((d for d in self.client.get_devices()
                            if isinstance(d, NM.DeviceWifiP2P)), None)
        self.active = None
        self.find_timer = 0
        if self.device:
            self.device.connect("peer-added", lambda *_: self._changed())
            self.device.connect("peer-removed", lambda *_: self._changed())

    @property
    def ready(self):
        return self.device is not None

    def displays(self):
        if not self.device:
            return []
        found = [Display(peer) for peer in self.device.get_peers()]
        return sorted((d for d in found if wfd.is_sink(d.ies)), key=lambda d: -d.strength)

    def _changed(self):
        self.on_displays(self.displays())

    # --- discovery -------------------------------------------------------

    def start_find(self):
        """Search, and keep searching while the window is open.

        wpa_supplicant ends a find after its timeout, so it is restarted
        just before it lapses.
        """
        if not self.device or self.find_timer:
            return
        self._find()
        self.find_timer = GLib.timeout_add_seconds(FIND_SECONDS - 2, self._find)

    def stop_find(self):
        if self.find_timer:
            GLib.source_remove(self.find_timer)
            self.find_timer = 0
        if self.device:
            self.device.stop_find(None, None, None)

    def _find(self):
        options = GLib.Variant("a{sv}", {"timeout": GLib.Variant("i", FIND_SECONDS)})
        self.device.start_find(options, None, self._found, None)
        return GLib.SOURCE_CONTINUE

    def _found(self, device, result, _data):
        try:
            device.start_find_finish(result)
        except GLib.Error as error:
            self.log(f"cast: find failed: {error.message}")
        self._changed()

    # --- connection ------------------------------------------------------

    def connect_to(self, display):
        """Join the display's group, advertising this laptop as a WFD source."""
        if not self.device:
            self.on_link("failed", "This laptop has no Wi-Fi Direct device")
            return
        self.stop_find()
        conn = NM.SimpleConnection.new()
        base = NM.SettingConnection.new()
        base.set_property(NM.SETTING_CONNECTION_ID, f"Cast to {display.name}")
        base.set_property(NM.SETTING_CONNECTION_UUID, str(uuid.uuid4()))
        base.set_property(NM.SETTING_CONNECTION_TYPE, NM.SETTING_WIFI_P2P_SETTING_NAME)
        base.set_property(NM.SETTING_CONNECTION_AUTOCONNECT, False)
        conn.add_setting(base)
        p2p = NM.SettingWifiP2P.new()
        p2p.set_property(NM.SETTING_WIFI_P2P_PEER, display.address)
        p2p.set_property(NM.SETTING_WIFI_P2P_WFD_IES, GLib.Bytes.new(wfd.source_ies()))
        conn.add_setting(p2p)
        ip4 = NM.SettingIP4Config.new()
        ip4.set_property(NM.SETTING_IP_CONFIG_METHOD, NM.SETTING_IP4_CONFIG_METHOD_AUTO)
        conn.add_setting(ip4)
        ip6 = NM.SettingIP6Config.new()
        ip6.set_property(NM.SETTING_IP_CONFIG_METHOD, NM.SETTING_IP6_CONFIG_METHOD_DISABLED)
        conn.add_setting(ip6)

        options = GLib.Variant("a{sv}", {"persist": GLib.Variant("s", "volatile")})
        self.on_link("connecting", f"Joining {display.name}. Accept on the TV if it asks.")
        self.client.add_and_activate_connection2(
            conn, self.device, display.peer.get_path(), options, None, self._activated, None)

    def _activated(self, client, result, _data):
        try:
            active, _ = client.add_and_activate_connection2_finish(result)
        except GLib.Error as error:
            self.on_link("failed", f"Could not join the TV: {error.message}")
            return
        self.active = active
        active.connect("state-changed", self._on_state)
        self._on_state(active, active.get_state(), 0)

    def _on_state(self, active, state, _reason):
        state = NM.ActiveConnectionState(int(state)) if not isinstance(
            state, NM.ActiveConnectionState) else state
        if state == NM.ActiveConnectionState.ACTIVATED:
            ip4 = active.get_ip4_config()
            addresses = [a.get_address() for a in ip4.get_addresses()] if ip4 else []
            self.on_link("connected", f"Linked over Wi-Fi Direct ({', '.join(addresses) or 'no address'})")
        elif state == NM.ActiveConnectionState.DEACTIVATED:
            if self.active is active:
                self.active = None
            self.on_link("disconnected", "Wi-Fi Direct link closed")

    def disconnect(self):
        if self.active:
            active, self.active = self.active, None
            self.client.deactivate_connection_async(active, None, None, None)
