# 3D range

A drone range in a white test chamber that you aim at with the physical gun.

Quadcopters drift across the room at varying depth and you shoot them down.
The drones are built from primitives rather than downloaded meshes: at this
size only the silhouette reads, and it keeps the repo free of assets with
licences attached.

```bash
cd ~/game
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ursina pyserial

.venv/bin/python range3d/main.py             # live gun on /dev/ttyUSB0
.venv/bin/python range3d/main.py --simulate  # no hardware needed
```

Space fires, `c` re-centres the aim, escape quits.

## Why light-gun rather than first person

The camera does not move. The gun steers a reticle inside a fixed view, which
is what you are physically doing when you point at a monitor.

Turning the gun into a first-person camera would be the obvious alternative and
it is the wrong choice here. Yaw has no magnetometer behind it, so it is
dead-reckoned and slowly returns to centre. On a crosshair that is a minor
nuisance you fix with `c`; on the camera itself it means the whole world
creeping sideways while you stand still.

Pitch and roll do not have this problem — gravity anchors them — which is worth
remembering when designing anything else for this hardware.

## Why it reads the serial port directly

The 2D range goes through `tools/aim_bridge.py` because a browser cannot open a
serial port. Python can, so this imports the bridge's parser and reads the
device itself: one less process to start and one less hop of latency. The
parser is shared rather than copied, so the pseudo-terminal tests in
`tools/test_bridge.py` cover this path too.

## Checking it works

```bash
.venv/bin/python range3d/main.py --simulate --selftest
```

This places a target exactly where the reticle points, fires, and checks it
was hit — at the centre and at all four corners, plus a deliberate miss so the
corner checks cannot pass by accident.

The projection from reticle position to world ray is the easy thing to get
quietly wrong here. An aspect ratio or a factor of two out of place and the
game still looks perfect while every shot lands a consistent distance from
where you aimed, which is maddening to diagnose by playing.

`--frames N --shot out.png` renders N frames and saves the window's own
framebuffer, which is how the rendering gets checked without a person looking
at it.
