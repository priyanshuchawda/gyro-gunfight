#!/usr/bin/env python3
"""A 3D shooting range you aim at with the physical gun.

    game/.venv/bin/python range3d/main.py                 # live gun
    game/.venv/bin/python range3d/main.py --simulate      # no hardware
    game/.venv/bin/python range3d/main.py --port /dev/ttyUSB1

Light-gun model rather than first person: the camera stays put and the gun
moves a reticle inside the view, which is what you are doing physically when
you point at the monitor. It also keeps yaw drift off the camera, where it
would be far more disorienting than on a crosshair you can re-centre.

Serial is read directly instead of through the HTTP bridge, using the same
parser the bridge uses, so there is one less hop and one less thing to start.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from ursina import (  # noqa: E402
    Cylinder,
    Grid,
    Entity,
    Text,
    Ursina,
    Vec2,
    Vec3,
    application,
    camera,
    color,
    destroy,
    held_keys,
    invoke,
    raycast,
    time as utime,
    window,
)

from aim_bridge import AimSource, read_serial, simulate  # noqa: E402

ROUND_SECONDS = 60
MAG_SIZE = 6
RELOAD_S = 0.9
# Degrees of gun movement to cross the screen, matching the 2D range's feel.
AIM_SPAN = 70.0
SMOOTHING = 0.45
TARGET_COUNT = 5


def make_drone(position: Vec3, scale: float) -> Entity:
    """A quadcopter built from primitives.

    Modelled from shapes rather than a downloaded mesh: at this size the
    silhouette is all that reads, and it keeps the repo free of assets with
    licences attached.
    """
    shell = color.rgb32(58, 62, 70)
    dark = color.rgb32(34, 37, 43)

    drone = Entity(position=position, scale=scale, collider="box")
    # The collider is the whole silhouette; the visible parts hang off it as
    # children so a shot anywhere on the drone counts.
    drone.scale_y = scale * 0.8

    Entity(parent=drone, model="cube", scale=(0.62, 0.42, 0.52), color=shell)
    Entity(parent=drone, model="cube", scale=(0.34, 0.30, 0.62), color=dark,
           position=(0, 0.1, -0.06))
    # Forward sensor, the one warm detail against all the grey.
    Entity(parent=drone, model="sphere", scale=(0.17, 0.28, 0.17),
           position=(0, 0.02, -0.34), color=color.rgb32(226, 92, 66))

    rotors = []
    for dx, dz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        angle = math.degrees(math.atan2(dz, dx))
        Entity(parent=drone, model="cube", scale=(0.78, 0.13, 0.13),
               position=(dx * 0.3, 0, dz * 0.3), rotation=(0, -angle, 0),
               color=dark)
        pod = Entity(parent=drone, model="cube", scale=(0.2, 0.22, 0.2),
                     position=(dx * 0.62, 0.02, dz * 0.62), color=shell)
        rotor = Entity(parent=pod, model=Cylinder(resolution=10, radius=0.5,
                                                  height=0.06),
                       scale=(2.9, 1, 2.9), position=(0, 0.6, 0),
                       color=color.rgba32(40, 44, 52, 150))
        rotors.append(rotor)
    drone.rotors = rotors
    return drone


class Range3D:
    def __init__(self, source: AimSource) -> None:
        self.source = source
        self.reticle_pos = Vec2(0, 0)
        self.offset = None  # captured on the first packet, like the 2D range
        self.last_shots = None
        self.state = "ready"
        self.score = 0
        self.hits = 0
        self.shots = 0
        self.ammo = MAG_SIZE
        self.reloading_until = 0.0
        self.elapsed = 0.0
        self.targets: list[Entity] = []
        self.rate_packets = 0
        self.rate = 0

        self._build_world()
        self._build_hud()

    # -- scene ------------------------------------------------------------
    def _build_world(self) -> None:
        window.color = color.rgb32(228, 231, 235)
        # Eye height sits mid-way up the target band so the reticle rests at
        # the centre of the action instead of below it.
        camera.position = Vec3(0, 3.4, -9)
        camera.rotation = Vec3(0, 0, 0)
        camera.fov = 70

        wall = color.rgb32(242, 243, 245)
        tile = color.rgba32(120, 130, 145, 70)

        Entity(model="plane", scale=(60, 1, 60), position=(0, 0, 6),
               color=color.rgb32(214, 217, 222))

        # Back wall the drones fly against. The tile grid is what makes the
        # room read as a test chamber and gives the eye a scale reference.
        Entity(model="cube", scale=(34, 16, 0.4), position=(0, 8, 14), color=wall)
        Entity(model=Grid(17, 8), scale=(34, 16), position=(0, 8, 13.75),
               color=tile)
        for x in (-17, 17):
            Entity(model="cube", scale=(0.4, 16, 30), position=(x, 8, 2),
                   color=color.rgb32(236, 238, 241))

        # Floor bands, dark with one warm stripe, running across the room so
        # depth is readable at a glance.
        for z, shade in ((1.5, 150), (4.5, 172), (10.5, 172), (13.2, 150)):
            Entity(model="cube", scale=(34, 0.02, 0.55), position=(0, 0.02, z),
                   color=color.rgb32(shade, shade + 4, shade + 10))
        Entity(model="cube", scale=(34, 0.02, 0.7), position=(0, 0.03, 7.5),
               color=color.rgb32(226, 138, 62))

        # Blocks on the floor, both as scenery and as something for stray
        # shots to stop against instead of vanishing into the distance.
        for x, z, h in ((-7.5, 8.5, 2.2), (7.5, 8.5, 2.2), (-2.4, 12.0, 1.5),
                        (3.6, 12.0, 1.8)):
            Entity(model="cube", scale=(1.5, h, 1.5), position=(x, h / 2, z),
                   color=color.rgb32(250, 250, 252), collider="box")

        self.muzzle_light = Entity(
            model="quad", parent=camera.ui, scale=6,
            color=color.rgba32(255, 190, 90, 0), z=1,
        )

    def _build_hud(self) -> None:
        # A ring plus four ticks, so the aim point stays readable against both
        # the dark floor and a bright target.
        self.reticle = Entity(parent=camera.ui)
        Entity(parent=self.reticle, model="circle", scale=0.030,
               color=color.rgba32(255, 90, 70, 90))
        Entity(parent=self.reticle, model="circle", scale=0.022,
               color=color.rgba32(11, 14, 20, 210))
        for dx, dy, sx, sy in ((0, 0.026, 0.002, 0.014), (0, -0.026, 0.002, 0.014),
                               (0.026, 0, 0.014, 0.002), (-0.026, 0, 0.014, 0.002)):
            Entity(parent=self.reticle, model="quad", position=(dx, dy, -0.01),
                   scale=(sx, sy), color=color.rgba32(255, 120, 100, 230))
        Entity(parent=self.reticle, model="circle", scale=0.005, z=-0.02,
               color=color.rgb32(255, 235, 220))

        # Dark on light: the room is white, so the readable HUD from the old
        # dark scene would have been invisible here.
        ink = color.rgb32(38, 44, 54)
        faint = color.rgb32(120, 130, 145)
        self.hud_score = Text(parent=camera.ui, text="", origin=(-0.5, 0.5),
                              position=(-0.86, 0.46), scale=1.1, color=ink)
        self.hud_timer = Text(parent=camera.ui, text="", origin=(0, 0.5),
                              position=(0, 0.46), scale=1.4, color=ink)
        self.hud_ammo = Text(parent=camera.ui, text="", origin=(0.5, 0.5),
                             position=(0.86, 0.46), scale=1.1, color=ink)
        self.hud_link = Text(parent=camera.ui, text="", origin=(-0.5, -0.5),
                             position=(-0.86, -0.46), scale=0.75, color=faint)
        self.banner = Text(parent=camera.ui, text="", origin=(0, 0), scale=2.2,
                           color=ink)
        self.banner_sub = Text(parent=camera.ui, text="", origin=(0, 0),
                               position=(0, -0.07), scale=1.0, color=faint)
        self._show_banner("RANGE READY", "pull the trigger to start")

    def _show_banner(self, title: str, sub: str) -> None:
        self.banner.text = title
        self.banner_sub.text = sub

    # -- round flow -------------------------------------------------------
    def start_round(self) -> None:
        for t in self.targets:
            destroy(t)
        self.targets.clear()
        self.state = "playing"
        self.score = self.hits = self.shots = 0
        self.ammo = MAG_SIZE
        self.elapsed = 0.0
        self.reloading_until = 0.0
        self._show_banner("", "")
        self.recentre()
        for _ in range(TARGET_COUNT):
            self.spawn_target()

    def end_round(self) -> None:
        self.state = "over"
        for t in self.targets:
            destroy(t)
        self.targets.clear()
        accuracy = round(self.hits / self.shots * 100) if self.shots else 0
        self._show_banner(
            f"{self.score} POINTS",
            f"{self.hits}/{self.shots} hits, {accuracy}% accuracy - trigger to play again",
        )

    def spawn_target(self) -> None:
        target = make_drone(
            position=Vec3(random.uniform(-8.5, 8.5), random.uniform(1.8, 6.2),
                          random.uniform(6, 13)),
            scale=random.uniform(0.85, 1.35),
        )
        target.drift = Vec3(random.uniform(-1.3, 1.3), random.uniform(-0.5, 0.5), 0)
        target.bob = random.uniform(0, 6.28)
        target.born = self.elapsed
        self.targets.append(target)

    # -- aiming -----------------------------------------------------------
    def recentre(self) -> None:
        state = self.source.snapshot()
        self.offset = (state.pitch, state.yaw)

    def update_aim(self) -> None:
        state = self.source.snapshot()
        if self.offset is None:
            self.offset = (state.pitch, state.yaw)

        dy = state.pitch - self.offset[0]
        dx = state.yaw - self.offset[1]

        aspect = window.aspect_ratio
        # UI space spans 1.0 vertically and `aspect` horizontally, so the
        # horizontal span is scaled to keep degrees-per-unit equal on both axes.
        target_x = -dx / AIM_SPAN * aspect
        target_y = -dy / AIM_SPAN * aspect
        limit_x, limit_y = aspect / 2, 0.5
        target_x = max(-limit_x, min(limit_x, target_x))
        target_y = max(-limit_y, min(limit_y, target_y))

        k = 1 - SMOOTHING
        self.reticle_pos = Vec2(
            self.reticle_pos.x + (target_x - self.reticle_pos.x) * k,
            self.reticle_pos.y + (target_y - self.reticle_pos.y) * k,
        )
        self.reticle.position = (self.reticle_pos.x, self.reticle_pos.y, 0)

    def aim_ray(self) -> Vec3:
        """World-space direction the reticle is pointing."""
        half = math.tan(math.radians(camera.fov) / 2)
        # UI y of 0.5 is the top of the screen, which is `half` at unit depth.
        return Vec3(
            camera.forward
            + camera.right * (self.reticle_pos.x * 2 * half)
            + camera.up * (self.reticle_pos.y * 2 * half)
        ).normalized()

    # -- shooting ---------------------------------------------------------
    def fire(self) -> None:
        if self.state != "playing":
            self.start_round()
            return
        if self.elapsed < self.reloading_until or self.ammo <= 0:
            return

        self.ammo -= 1
        self.shots += 1
        self.muzzle_light.color = color.rgba32(255, 190, 90, 55)
        invoke(setattr, self.muzzle_light, "color", color.rgba32(255, 190, 90, 0),
               delay=0.05)

        hit = raycast(camera.world_position, self.aim_ray(), distance=60,
                      debug=False)
        if hit.hit and hit.entity in self.targets:
            self.register_hit(hit.entity)

    def register_hit(self, target: Entity) -> None:
        self.hits += 1
        # Smaller and further targets are worth more.
        distance = (target.world_position - camera.world_position).length()
        self.score += int(40 + (1.3 - target.scale_x) * 60 + distance * 3)
        self.targets.remove(target)
        destroy(target)
        self.spawn_target()

    # -- per frame --------------------------------------------------------
    def update(self, dt: float) -> None:
        state = self.source.snapshot()
        self.update_aim()

        # The device counts debounced presses, so a dropped packet cannot lose
        # or duplicate a shot the way watching for a 0->1 edge would.
        if self.last_shots is None or state.shots < self.last_shots:
            self.last_shots = state.shots
        while state.shots > self.last_shots:
            self.last_shots += 1
            self.fire()

        if self.state == "playing":
            self.elapsed += dt
            if self.elapsed >= ROUND_SECONDS:
                self.end_round()
                return
            if self.ammo <= 0 and self.elapsed >= self.reloading_until:
                self.reloading_until = self.elapsed + RELOAD_S
                invoke(self._finish_reload, delay=RELOAD_S)
            for target in list(self.targets):
                target.x += target.drift.x * dt
                target.y += target.drift.y * dt
                if abs(target.x) > 9.0:
                    target.drift.x *= -1
                if not 1.4 < target.y < 6.6:
                    target.drift.y *= -1
                target.bob += dt
                # A slight hover wobble and a bank into the turn, so they read
                # as flying rather than sliding along a rail.
                target.y += math.sin(target.bob * 3.1) * dt * 0.35
                target.rotation_z = -target.drift.x * 7
                for rotor in target.rotors:
                    rotor.rotation_y += 1400 * dt

        self.refresh_hud(state)

    def _finish_reload(self) -> None:
        self.ammo = MAG_SIZE

    def refresh_hud(self, state) -> None:
        accuracy = round(self.hits / self.shots * 100) if self.shots else 0
        self.hud_score.text = f"<orange>{self.score}<default>\n{self.hits}/{self.shots}  {accuracy}%"
        if self.state == "playing":
            self.hud_timer.text = f"{max(0, ROUND_SECONDS - self.elapsed):.0f}"
        else:
            self.hud_timer.text = ""
        reloading = self.elapsed < self.reloading_until
        self.hud_ammo.text = "RELOADING" if reloading else "|" * self.ammo
        link = state.source if state.connected else "no controller"
        self.hud_link.text = f"{link}   {self.rate} Hz   [space] fire  [c] centre  [esc] quit"


def run_selftest(game: "Range3D") -> None:
    """Check that a shot lands where the reticle is drawn.

    The projection from reticle position to world ray is the easiest thing
    here to get quietly wrong: an aspect ratio or a factor of two out and the
    game still looks perfect while every shot misses by a consistent margin.
    Placing a target at a known offset and firing is the only way to catch it.
    """
    failures = 0

    def check(name: str, got, want) -> None:
        nonlocal failures
        if got == want:
            print(f"  ok    {name:<44} {got}")
        else:
            print(f"  FAIL  {name:<44} got {got!r}, want {want!r}")
            failures += 1

    game.state = "playing"
    for t in list(game.targets):
        destroy(t)
    game.targets.clear()

    def place(ui_x: float, ui_y: float, distance: float = 10.0) -> Entity:
        """Put a drone exactly where the reticle at (ui_x, ui_y) points."""
        game.reticle_pos = Vec2(ui_x, ui_y)
        game.reticle.position = (ui_x, ui_y, 0)
        spot = camera.world_position + game.aim_ray() * distance
        # A real drone rather than a stand-in sphere, so this covers the
        # collider the game actually spawns.
        target = make_drone(position=spot, scale=1.0)
        target.drift = Vec3(0, 0, 0)
        target.bob = 0.0
        game.targets.append(target)
        return target

    # Dead centre first: the simplest case, and if this fails nothing else
    # is worth reading.
    place(0, 0)
    game.ammo, game.hits, game.shots = 6, 0, 0
    game.fire()
    check("a centred shot hits a centred target", game.hits, 1)

    # Then the corners, where an aspect ratio mistake shows up. Centre stays
    # empty, so a hit can only come from the ray going the right way.
    for name, (ux, uy) in {
        "up and left": (-0.55, 0.34),
        "up and right": (0.55, 0.34),
        "down and left": (-0.55, -0.34),
        "down and right": (0.55, -0.34),
    }.items():
        for t in list(game.targets):
            destroy(t)
        game.targets.clear()
        place(ux, uy)
        game.ammo, game.hits = 6, 0
        game.fire()
        check(f"a shot {name} hits", game.hits, 1)

    # And the inverse: aiming away from the only target must miss, or the
    # checks above would pass even with the ray pointing anywhere.
    for t in list(game.targets):
        destroy(t)
    game.targets.clear()
    place(0.55, 0.34)
    game.reticle_pos = Vec2(-0.55, -0.34)
    game.ammo, game.hits = 6, 0
    game.fire()
    check("aiming away from the target misses", game.hits, 0)

    print(f"\n{'FAILURES' if failures else 'all 3D aim checks passed'}")
    application.quit()
    if failures:
        # Ursina swallows a non-zero return from quit(), so record it here.
        Path("/tmp/range3d_selftest_failed").write_text(str(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--no-reset", action="store_true",
                        help="do not toggle DTR/RTS when opening the port")
    parser.add_argument("--frames", type=int, default=0,
                        help="quit after N frames (for automated checks)")
    parser.add_argument("--shot", help="save a screenshot before quitting")
    parser.add_argument("--selftest", action="store_true",
                        help="check the reticle and the raycast agree, then exit")
    args = parser.parse_args()

    source = AimSource()
    if args.simulate:
        worker = threading.Thread(target=simulate, args=(source,), daemon=True)
    else:
        worker = threading.Thread(
            target=read_serial,
            args=(source, args.port, args.baud, not args.no_reset),
            daemon=True,
        )
    worker.start()

    app = Ursina(title="Gyro Gunfight - 3D Range", borderless=False,
                 development_mode=False, vsync=True)
    game = Range3D(source)

    counters = {"frames": 0, "last_seq": 0, "since": 0.0}

    def update():
        dt = min(utime.dt, 0.05)  # a stall must not teleport the targets

        if args.selftest:
            counters["frames"] += 1
            if counters["frames"] > 5:
                run_selftest(game)
            return

        game.update(dt)

        counters["frames"] += 1
        counters["since"] += dt
        if counters["since"] >= 1.0:
            seq = source.snapshot().seq
            game.rate = int(seq - counters["last_seq"])
            counters["last_seq"] = seq
            counters["since"] = 0.0

        if args.frames and counters["frames"] >= args.frames:
            snap = source.snapshot()
            if args.shot:
                # The window's own framebuffer, so a terminal sitting on top
                # of it cannot end up in the picture.
                from panda3d.core import Filename

                app.win.saveScreenshot(Filename.fromOsSpecific(args.shot))
                print(f"SHOT {args.shot}")
            print(f"FRAMES {counters['frames']} rate={game.rate}Hz "
                  f"connected={snap.connected} state={game.state} "
                  f"targets={len(game.targets)}")
            application.quit()

    def input(key):
        if key == "escape":
            application.quit()
        elif key == "space":
            game.fire()
        elif key == "c":
            game.recentre()

    app.update = update
    app.input = input
    globals()["update"] = update
    globals()["input"] = input

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
