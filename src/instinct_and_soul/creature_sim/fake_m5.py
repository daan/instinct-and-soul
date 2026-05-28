"""Fake M5 module: capture Display calls; stub buttons / power / update."""
import json
import os


class _CapturingDisplay:
    def __init__(self, clock, log_path: str):
        self._clock = clock
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log = open(log_path, "w")

    def _emit(self, payload: dict) -> None:
        payload["t"] = self._clock.now_ms
        self._log.write(json.dumps(payload) + "\n")

    def fillScreen(self, rgb):                       self._emit({"kind": "fillScreen",   "rgb": int(rgb)})
    def fillRect(self, x, y, w, h, rgb):             self._emit({"kind": "fillRect",     "x": int(x), "y": int(y), "w": int(w), "h": int(h), "rgb": int(rgb)})
    def fillCircle(self, cx, cy, r, rgb):            self._emit({"kind": "fillCircle",   "cx": int(cx), "cy": int(cy), "r": int(r), "rgb": int(rgb)})
    def fillTriangle(self, x1, y1, x2, y2, x3, y3, rgb): self._emit({"kind": "fillTriangle", "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2), "x3": int(x3), "y3": int(y3), "rgb": int(rgb)})
    def fillArc(self, cx, cy, r0, r1, a0, a1, rgb):  self._emit({"kind": "fillArc",      "cx": int(cx), "cy": int(cy), "r0": int(r0), "r1": int(r1), "a0": float(a0), "a1": float(a1), "rgb": int(rgb)})
    def drawLine(self, x1, y1, x2, y2, rgb):         self._emit({"kind": "drawLine",     "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2), "rgb": int(rgb)})
    def setBrightness(self, v):                      self._emit({"kind": "setBrightness","value": int(v)})

    def close(self):
        try: self._log.close()
        except Exception: pass


class _StubButton:
    def isPressed(self):  return False
    def wasPressed(self): return False
    def isReleased(self): return True
    def wasReleased(self): return False
    def isHolding(self):  return False


class _StubPower:
    def getBatteryLevel(self):   return 80
    def getBatteryVoltage(self): return 3950
    def isCharging(self):        return False


class _M5:
    """Module-like namespace gathering Display, BtnA, BtnB, Power, update()."""

    def __init__(self, clock, display_log_path: str):
        self.Display = _CapturingDisplay(clock, display_log_path)
        self.BtnA  = _StubButton()
        self.BtnB  = _StubButton()
        self.Power = _StubPower()

    def update(self):
        # The real M5.update() ticks the audio engine and polls buttons.
        # In the sim there's nothing to tick — tone events were already
        # captured at the moment Speaker.tone() was called.
        pass

    def close(self):
        self.Display.close()
