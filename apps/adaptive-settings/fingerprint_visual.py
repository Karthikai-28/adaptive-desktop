"""Enrollment illustration driven only by accepted fprintd samples.

This is a generic ridge illustration, never an image of a user's fingerprint.
"""
import math
import sys
import time
from pathlib import Path

from gi.repository import Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import adaptive_tokens


class FingerprintVisual(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        tokens = adaptive_tokens.load()
        self.colors = {role: tuple(c / 255 for c in adaptive_tokens.rgb(tokens.hex(role)))
                       for role in ("accent", "ok", "warn", "text.disabled", "surface.card")}
        self.duration = tokens.raw["motion"]["state.ms"] / 1000
        self.cycle = tokens.raw["motion"]["genie.ms"] / 1000
        self.fraction = self.target = self.start_fraction = 0.
        self.phase = "idle"
        self.stages = 6
        self.accepted = 0
        self.started = time.monotonic()
        self.tick = 0
        self.set_content_width(240)
        self.set_content_height(200)
        self.set_halign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        self.connect("unmap", self._unmap)
        self.connect("map", lambda *_: self._animate())

    def update(self, phase, accepted=None, stages=None):
        self.phase = phase
        self.start_fraction = self.fraction
        if stages is not None:
            self.stages = max(1, stages)
        if accepted is not None:
            self.accepted = max(0, min(accepted, self.stages))
            self.target = self.accepted / self.stages
        self.started = time.monotonic()
        self._animate()
        self.queue_draw()

    def _animations(self):
        settings = self.get_settings()
        return settings is not None and settings.get_property("gtk-enable-animations")

    def _animate(self):
        if not self._animations():
            self.fraction = self.target
            return
        if not self.tick and self.get_mapped():
            self.tick = self.add_tick_callback(self._frame)

    def _frame(self, _widget, _clock):
        elapsed = time.monotonic() - self.started
        t = min(1., elapsed / self.duration)
        self.fraction = self.start_fraction + (self.target - self.start_fraction) * (1 - (1 - t) ** 3)
        self.queue_draw()
        active = self._animations() and (self.phase in ("scanning", "accepted", "retry") or t < 1)
        if not active:
            self.fraction = self.target
            self.tick = 0
        return active

    def _unmap(self, *_):
        if self.tick:
            self.remove_tick_callback(self.tick)
            self.tick = 0

    def _color(self, cr, role, alpha=1.):
        cr.set_source_rgba(*self.colors[role], alpha)

    @staticmethod
    def _ridges(cr):
        for index in range(9):
            rx, ry = 9 + index * 5.1, 14 + index * 6.2
            cr.move_to(120 - rx, 102 + ry * .32)
            cr.curve_to(120 - rx - 5, 88 - ry, 120 + rx + 5, 88 - ry, 120 + rx, 102 + ry * .32)
            cr.curve_to(120 + rx * .95, 125 + ry * .20, 120 + rx * .65, 130 + ry * .32, 120 + rx * .5, 133 + ry * .40)
            cr.stroke()
        cr.move_to(120, 93)
        cr.curve_to(112, 108, 121, 131, 103, 150)
        cr.stroke()

    def _draw(self, _area, cr, width, height):
        cr.save()
        cr.translate((width - 240) / 2, (height - 200) / 2)
        cr.set_line_width(3)
        cr.set_line_cap(1)
        elapsed = time.monotonic() - self.started
        moving = self._animations() and self.phase in ("scanning", "accepted", "retry")
        if self.phase == "retry" and moving and elapsed < self.duration:
            cr.translate(3 * math.sin(elapsed / self.duration * 4 * math.pi) * (1 - elapsed / self.duration), 0)
        self._color(cr, "text.disabled", .55)
        self._ridges(cr)
        cr.save()
        cr.rectangle(55, 175 - self.fraction * 150, 130, self.fraction * 150)
        cr.clip()
        self._color(cr, "ok" if self.phase == "verified" else "accent")
        self._ridges(cr)
        cr.restore()
        if self.phase in ("scanning", "accepted", "retry"):
            y = 100 + 60 * math.sin(elapsed / self.cycle * math.pi) if moving else 100
            self._color(cr, "warn" if self.phase == "retry" else "accent", .75)
            cr.set_line_width(2)
            cr.move_to(60, y)
            cr.line_to(180, y)
            cr.stroke()
        for i in range(self.stages):
            x = 120 + (i - (self.stages - 1) / 2) * min(14, 180 / self.stages)
            self._color(cr, "accent" if i < self.accepted else "text.disabled")
            cr.arc(x, 190, 3, 0, 2 * math.pi)
            cr.fill()
        if self.phase in ("verified", "failed"):
            self._color(cr, "surface.card")
            cr.arc(172, 150, 17, 0, 2 * math.pi)
            cr.fill()
            self._color(cr, "ok" if self.phase == "verified" else "warn")
            cr.set_line_width(3)
            if self.phase == "verified":
                cr.move_to(164, 150); cr.line_to(170, 156); cr.line_to(181, 143)
            else:
                cr.move_to(167, 145); cr.line_to(177, 155)
                cr.move_to(177, 145); cr.line_to(167, 155)
            cr.stroke()
        cr.restore()
