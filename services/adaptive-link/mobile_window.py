"""Place a private-display window through its window manager (EWMH)."""
import ctypes as C
import sys


class ClientMessage(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int), ("display", C.c_void_p),
                ("window", C.c_ulong), ("message_type", C.c_ulong), ("format", C.c_int), ("data", C.c_long * 5)]


class Event(C.Union):
    _fields_ = [("client", ClientMessage), ("pad", C.c_long * 24)]


def place(wid, x, y, width, height):
    x11 = C.CDLL("libX11.so.6")
    x11.XOpenDisplay.argtypes = [C.c_char_p]
    x11.XOpenDisplay.restype = C.c_void_p
    x11.XDefaultRootWindow.argtypes = [C.c_void_p]
    x11.XDefaultRootWindow.restype = C.c_ulong
    x11.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
    x11.XInternAtom.restype = C.c_ulong
    x11.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(Event)]
    x11.XSync.argtypes = [C.c_void_p, C.c_int]
    x11.XCloseDisplay.argtypes = [C.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        raise ValueError("private display unavailable")
    try:
        atom = lambda name: x11.XInternAtom(display, name.encode(), False)
        root = x11.XDefaultRootWindow(display)
        for message, values in (("_NET_WM_STATE", (0, atom("_NET_WM_STATE_MAXIMIZED_VERT"), atom("_NET_WM_STATE_MAXIMIZED_HORZ"), 1, 0)),
                                ("_NET_MOVERESIZE_WINDOW", (0x1F00, x, y, width, height))):
            event = Event()
            event.client = ClientMessage(33, 0, True, display, wid, atom(message), 32, (C.c_long * 5)(*values))
            x11.XSendEvent(display, root, False, (1 << 20) | (1 << 19), C.byref(event))
        x11.XSync(display, False)
    finally:
        x11.XCloseDisplay(display)


if __name__ == "__main__":
    place(*(int(v) for v in sys.argv[1:]))
