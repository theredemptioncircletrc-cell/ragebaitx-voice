"""Builds an ffmpeg crop filter that follows the action, from the AI's focus points.

usage: python cropexpr.py IN_W IN_H POINTS_JSON
  POINTS_JSON: [[seconds, x], ...] where x is 0..1 = horizontal centre of the action
prints: crop=W:H:X:0  (X is a smooth time-based expression, commas escaped for -vf)
"""
import json
import sys


def main():
    iw, ih = int(sys.argv[1]), int(sys.argv[2])
    pts = json.loads(sys.argv[3] or "[]")
    cw = int(ih * 9 / 16) // 2 * 2
    if cw >= iw:
        print(f"crop={iw}:{ih}:0:0")
        return
    clean = []
    for p in pts:
        try:
            t, x = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= x <= 1:
            clean.append((t, x))
    clean.sort()
    if not clean:
        clean = [(0.0, 0.5)]
    # Smooth a little so the camera glides instead of jumping.
    xs = [c[1] for c in clean]
    sm = [sum(xs[max(0, i - 1):i + 2]) / len(xs[max(0, i - 1):i + 2]) for i in range(len(xs))]
    lo, hi = cw / 2, iw - cw / 2
    px = [(t, min(hi, max(lo, x * iw)) - cw / 2) for (t, _), x in zip(clean, sm)]
    # Piecewise-linear x(t): hold the first value before the first point, the last value after the last.
    expr = f"{px[-1][1]:.1f}"
    for i in range(len(px) - 2, -1, -1):
        (t0, x0), (t1, x1) = px[i], px[i + 1]
        if t1 <= t0:
            continue
        seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-({t0:.2f}))/{t1 - t0:.2f}"
        expr = f"if(lt(t,{t1:.2f}),{seg},{expr})"
    expr = f"if(lt(t,{px[0][0]:.2f}),{px[0][1]:.1f},{expr})"
    print(f"crop={cw}:{ih}:" + expr.replace(",", "\\,") + ":0")


if __name__ == "__main__":
    main()
