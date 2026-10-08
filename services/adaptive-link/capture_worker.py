"""GStreamer source helper with a private process environment.

Only its parent consumes this length-prefixed binary pipe. It is not a server.
"""
import struct
import sys
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)
pipeline = Gst.parse_launch(sys.argv[1])
sink = pipeline.get_by_name("sink")
pipeline.set_state(Gst.State.PLAYING)
try:
    while True:
        sample = sink.emit("try-pull-sample", 2 * Gst.SECOND)
        if sample is None:
            bus = pipeline.get_bus()
            if bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS):
                break
            continue
        buffer = sample.get_buffer()
        data = buffer.extract_dup(0, buffer.get_size())
        sys.stdout.buffer.write(struct.pack("!I", len(data)))
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
except BrokenPipeError:
    pass
finally:
    pipeline.set_state(Gst.State.NULL)
