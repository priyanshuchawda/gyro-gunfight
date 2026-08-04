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
    DirectionalLight,
    Entity,
    Grid,
    Text,
    Ursina,
    Vec2,
    Vec3,
    application,
    camera,
    color,
    destroy,
    invoke,
    raycast,
    scene,
    time as utime,
    window,
)
from ursina.shaders import lit_with_shadows_shader, unlit_shader  # noqa: E402

from aim_bridge import AimSource, read_serial, simulate  # noqa: E402

ROUND_SECONDS = 60
MAG_SIZE = 6
RELOAD_S = 0.9
# Degrees of gun movement to cross the screen, matching the 2D range's feel.
AIM_SPAN = 70.0
SMOOTHING = 0.45
TARGET_COUNT = 5


def view_scale() -> float:
    """UI units to direction offset per unit of depth.

    `camera.fov` is the **horizontal** field of view. Ursina hands it straight
    to Panda's `set_fov`, whose single-argument form sets the horizontal angle
    and derives the vertical one from the aspect ratio. Reading it as vertical
    scales every ray by the aspect ratio -- 1.89x on this display -- so shots
    landed correctly at dead centre and progressively further out from the
    crosshair everywhere else.

    Verified against the renderer rather than against its own inverse; see
    `check_projection_against_render` in the self-test.
    """
    return 2.0 * math.tan(math.radians(camera.fov) / 2) / window.aspect_ratio


def world_to_ui(point: Vec3) -> Vec2:
    """Where the renderer draws a world point, in UI units.

    Only valid for the fixed, unrotated camera this game uses.
    """
    rel = point - camera.world_position
    if rel.z <= 0.001:
        return Vec2(0, 0)
    span = rel.z * view_scale()
    return Vec2(rel.x / span, rel.y / span)


SHELL = color.rgb32(62, 67, 78)
SHELL_DARK = color.rgb32(33, 36, 43)
ACCENT = color.rgb32(236, 92, 58)
GLASS = color.rgb32(96, 158, 186)


def make_drone(position: Vec3, scale: float) -> Entity:
    """A quadcopter built from primitives.

    Modelled from shapes rather than a downloaded mesh: at this size the
    silhouette is all that reads, and it keeps the repo free of assets with
    licences attached.
    """
    drone = Entity(position=position, scale=scale, collider="box")
    # The collider is the whole silhouette; the visible parts hang off it as
    # children so a shot anywhere on the drone counts.
    drone.scale_y = scale * 0.8

    body = Entity(parent=drone, model="cube", scale=(0.6, 0.34, 0.56),
                  color=SHELL)
    # A chamfer plate above and below turns a plain box into something that
    # catches the light differently along its length.
    Entity(parent=body, model="cube", scale=(0.86, 0.34, 0.82),
           position=(0, 0.42, 0), color=SHELL_DARK)
    Entity(parent=body, model="cube", scale=(0.7, 0.3, 1.05),
           position=(0, -0.36, 0), color=SHELL_DARK)
    # Camera gimbal slung underneath, which is what makes it read as a drone
    # rather than a floating brick.
    gimbal = Entity(parent=drone, model="sphere", scale=(0.24, 0.2, 0.24),
                    position=(0, -0.22, -0.1), color=SHELL_DARK)
    Entity(parent=gimbal, model="sphere", scale=0.62, position=(0, 0, -0.5),
           color=GLASS)
    # Forward sensor, the one warm detail against all the grey.
    Entity(parent=drone, model="sphere", scale=(0.15, 0.24, 0.15),
           position=(0, 0.06, -0.32), color=ACCENT)

    rotors = []
    for dx, dz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        angle = math.degrees(math.atan2(dz, dx))
        Entity(parent=drone, model="cube", scale=(0.8, 0.1, 0.14),
               position=(dx * 0.31, 0.02, dz * 0.31), rotation=(0, -angle, 0),
               color=SHELL_DARK)
        pod = Entity(parent=drone, model="cube", scale=(0.19, 0.26, 0.19),
                     position=(dx * 0.64, 0.05, dz * 0.64), color=SHELL)
        Entity(parent=pod, model="sphere", scale=(0.8, 0.5, 0.8),
               position=(0, 0.7, 0), color=SHELL_DARK)
        rotor = Entity(
            parent=pod,
            model=Cylinder(resolution=3, radius=0.5, height=0.04),
            scale=(3.1, 1, 3.1), position=(0, 0.95, 0),
            color=color.rgba32(30, 33, 40, 130),
        )
        rotors.append(rotor)
    drone.rotors = rotors
    drone.shadow = None
    return drone


class Effects:
    """Debris, tracers, impact marks and the muzzle flash.

    Everything is a short-lived Entity on one list rather than a particle
    system, because the counts here are tiny and a list that gets swept each
    frame cannot leak entities the way ad-hoc invoke(destroy) calls can.
    """

    def __init__(self) -> None:
        self.items: list[tuple[Entity, float, float, str, Vec3]] = []

    def _add(self, entity: Entity, life: float, kind: str,
             velocity: Vec3 = Vec3(0, 0, 0)) -> None:
        self.items.append((entity, life, life, kind, velocity))

    def burst(self, position: Vec3, scale: float = 1.0) -> None:
        flash = Entity(model="sphere", position=position, scale=0.1 * scale,
                       color=color.rgba32(255, 214, 150, 235),
                       shader=unlit_shader)
        self._add(flash, 0.16, "flash")

        ring = Entity(model="sphere", position=position, scale=0.2 * scale,
                      color=color.rgba32(255, 150, 80, 150), shader=unlit_shader)
        self._add(ring, 0.34, "flash")

        for _ in range(14):
            direction = Vec3(random.uniform(-1, 1), random.uniform(-0.4, 1),
                             random.uniform(-1, 1)).normalized()
            shard = Entity(
                model="cube", position=position,
                scale=random.uniform(0.05, 0.13) * scale,
                color=random.choice((SHELL, SHELL_DARK, ACCENT)),
                rotation=Vec3(random.uniform(0, 360), random.uniform(0, 360), 0),
            )
            self._add(shard, random.uniform(0.5, 1.0), "debris",
                      direction * random.uniform(3.5, 8.0))

    def tracer(self, start: Vec3, end: Vec3) -> None:
        delta = end - start
        length = delta.length()
        if length < 0.01:
            return
        beam = Entity(model="cube", position=start + delta * 0.5,
                      color=color.rgba32(255, 208, 140, 170),
                      shader=unlit_shader)
        beam.look_at(end)
        beam.scale = Vec3(0.016, 0.016, length)
        # Not flagged "flash": the expansion those get would blow a beam this
        # close to the eye up into a wedge across the whole screen.
        self._add(beam, 0.05, "decal")

    def wreck(self, drone: Entity, push: Vec3) -> None:
        """Hand a killed drone over to be tumbled out of the sky.

        It keeps its model and stops being a target, so it cannot be shot
        twice while it falls.
        """
        drone.collider = None
        self._add(drone, 1.7, "wreck", push)

    def impact(self, position: Vec3, normal: Vec3) -> None:
        # Faces back along the normal, not down it: an Ursina circle shows its
        # -z side, so looking at the normal buries the visible face in the
        # wall. Sized to read at the back of the room, roughly a tenth of a
        # drone, which is small enough not to litter the chamber.
        mark = Entity(model="circle", position=position + normal * 0.02,
                      scale=0.45, color=color.rgba32(58, 66, 80, 190),
                      shader=unlit_shader, double_sided=True)
        mark.look_at(position - normal)
        self._add(mark, 6.0, "decal")
        ring = Entity(model="circle", position=position + normal * 0.03,
                      scale=0.62, color=color.rgba32(120, 128, 142, 90),
                      shader=unlit_shader, double_sided=True)
        ring.look_at(position - normal)
        self._add(ring, 2.5, "decal")
        for _ in range(5):
            direction = (normal + Vec3(random.uniform(-0.6, 0.6),
                                       random.uniform(-0.2, 0.8),
                                       random.uniform(-0.6, 0.6))).normalized()
            spark = Entity(model="cube", position=position, scale=0.035,
                           color=color.rgba32(255, 200, 130, 220),
                           shader=unlit_shader)
            self._add(spark, 0.3, "debris", direction * random.uniform(2, 4.5))

    def update(self, dt: float) -> None:
        alive = []
        for entity, remaining, life, kind, velocity in self.items:
            remaining -= dt
            if remaining <= 0:
                destroy(entity)
                continue
            fade = remaining / life
            if kind == "debris":
                entity.position += velocity * dt
                velocity = Vec3(velocity.x, velocity.y - 14 * dt, velocity.z)
                entity.rotation_x += 420 * dt
                entity.rotation_y += 300 * dt
            elif kind == "flash":
                entity.scale *= 1 + 5.5 * dt
            elif kind == "wreck":
                entity.position += velocity * dt
                velocity = Vec3(velocity.x, velocity.y - 18 * dt, velocity.z)
                if entity.y < 0.3 and velocity.y < 0:
                    entity.y = 0.3
                    velocity = Vec3(velocity.x * 0.4, -velocity.y * 0.3,
                                    velocity.z * 0.4)
                entity.rotation_x += 250 * dt
                entity.rotation_z += 170 * dt
                # Shrunk away rather than faded: alpha on a parent does not
                # reach its children, and a drone is a dozen child entities.
                if remaining < 0.45:
                    entity.scale *= max(0.0, 1 - dt * 7)

            if kind == "decal":
                entity.alpha = min(1.0, fade * 4)
            elif kind != "wreck":
                entity.alpha = fade
            alive.append((entity, remaining, life, kind, velocity))
        self.items = alive

    def clear(self) -> None:
        for entity, *_ in self.items:
            destroy(entity)
        self.items.clear()


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
        self.popups: list[list] = []
        self.rate_packets = 0
        self.rate = 0

        self._build_world()
        self._build_hud()

    # -- scene ------------------------------------------------------------
    def _build_world(self) -> None:
        window.color = color.rgb32(214, 219, 226)
        # Eye height sits mid-way up the target band so the reticle rests at
        # the centre of the action instead of below it.
        camera.position = Vec3(0, 3.4, -9)
        camera.rotation = Vec3(0, 0, 0)
        camera.fov = 70
        self.camera_home = Vec3(camera.position)
        self.shake = 0.0

        # Everything built from here on is lit and casts shadows. Flat colour
        # made the drones read as stickers; a single sun is what gives the
        # boxes and rotor arms enough shading to look like objects in a room.
        Entity.default_shader = lit_with_shadows_shader
        # The stock shadow colour is `rgba(0, .5, 1, .25)`, and the shader
        # subtracts it from shadowed pixels, so out of the box every shadow in
        # the room comes out cyan. Neutral grey is what a shadow should be.
        lit_with_shadows_shader.default_input["shadow_color"] = color.rgba(0, 0, 0, 0.38)

        wall = color.rgb32(238, 240, 244)
        tile = color.rgba32(120, 130, 145, 70)

        room = [
            Entity(model="plane", scale=(44, 1, 44), position=(0, 0, 6),
                   color=color.rgb32(216, 219, 225)),
            # Back wall the drones fly against. The tile grid is what makes
            # the room read as a test chamber and gives a scale reference.
            Entity(model="cube", scale=(34, 16, 0.4), position=(0, 8, 14),
                   color=wall, collider="box"),
        ]
        Entity(model=Grid(17, 8), scale=(34, 16), position=(0, 8, 13.75),
               color=tile, shader=unlit_shader)
        for x in (-17, 17):
            room.append(Entity(model="cube", scale=(0.4, 16, 30),
                               position=(x, 8, 2), collider="box",
                               color=color.rgb32(236, 239, 243)))
        # The room receives shadows but must not cast them. A 16 m side wall
        # lit from the left throws a slab across the whole back wall, which
        # looks like a rendering fault rather than a shadow. 0b0001 is the
        # mask the shadow camera renders.
        for surface in room:
            surface.hide(0b0001)

        # A grid on the floor rather than the stripes that were here before.
        # Stripes only mark the few depths they sit at; a grid converges, so
        # the eye reads distance anywhere in the room.
        Entity(model=Grid(22, 22), scale=(44, 44), rotation_x=90,
               position=(0, 0.01, 6), color=tile, shader=unlit_shader)
        Entity(model="cube", scale=(34, 0.02, 0.14), position=(0, 0.03, 7.5),
               color=color.rgb32(226, 138, 62)).hide(0b0001)

        # Blocks on the floor, both as scenery and as something for stray
        # shots to stop against instead of vanishing into the distance.
        for x, z, h in ((-7.5, 8.5, 2.2), (7.5, 8.5, 2.2), (-2.4, 12.0, 1.5),
                        (3.6, 12.0, 1.8)):
            Entity(model="cube", scale=(1.5, h, 1.5), position=(x, h / 2, z),
                   color=color.rgb32(248, 249, 251), collider="box")

        # Sun from over the left shoulder, so drones throw a shadow onto the
        # floor and the back wall. That shadow is the main depth cue for how
        # far away a drone is.
        self.sun = DirectionalLight(shadow_map_resolution=Vec2(2048, 2048))
        # Assigned after construction on purpose: `Light.__init__` accepts a
        # `color` argument and then never passes it on, so a colour handed to
        # the constructor is dropped and the light stays full white. Full
        # white clips this room, because the shader adds a flat albedo term
        # and a diffuse term that together pass 1.0 on anything near-white.
        self.sun.color = color.rgb32(203, 203, 203)
        self.sun.position = Vec3(-8, 18, -4)
        self.sun.look_at(Vec3(2, 0, 9))
        # Fit the shadow map to the play volume instead of the whole scene:
        # the 44 m floor would otherwise stretch the map until shadow edges
        # dissolved into stair-steps.
        bounds = Entity(model="cube", scale=(26, 12, 20), position=(0, 5, 7),
                        visible=False)
        self.sun.update_bounds(bounds)
        # No AmbientLight: the shader only reads light source 0, so a second
        # light would change nothing. Its job is done by the shader's flat
        # albedo term, which never goes to black on unlit faces.

        # A glow low on the screen where the gun would be, not a full-screen
        # wash: covering the whole viewport tinted every pixel warm for the
        # length of the flash, which looked like the render had gone wrong.
        self.muzzle_light = Entity(
            model="circle", parent=camera.ui, scale=(1.1, 0.5),
            position=(0.05, -0.62), shader=unlit_shader,
            color=color.rgba32(255, 190, 90, 0), z=1,
        )
        self.effects = Effects()

    def _build_hud(self) -> None:
        # A ring plus four ticks, so the aim point stays readable against both
        # the dark floor and a bright target.
        self.reticle = Entity(parent=camera.ui)
        Entity(parent=self.reticle, model="circle", scale=0.030,
               shader=unlit_shader, color=color.rgba32(255, 90, 70, 90))
        Entity(parent=self.reticle, model="circle", scale=0.022,
               shader=unlit_shader, color=color.rgba32(11, 14, 20, 210))
        for dx, dy, sx, sy in ((0, 0.026, 0.002, 0.014), (0, -0.026, 0.002, 0.014),
                               (0.026, 0, 0.014, 0.002), (-0.026, 0, 0.014, 0.002)):
            Entity(parent=self.reticle, model="quad", position=(dx, dy, -0.01),
                   scale=(sx, sy), shader=unlit_shader,
                   color=color.rgba32(255, 120, 100, 230))
        Entity(parent=self.reticle, model="circle", scale=0.005, z=-0.02,
               shader=unlit_shader, color=color.rgb32(255, 235, 220))

        # Corner brackets that appear only while a drone is under the
        # reticle. At this range a drone is a few dozen pixels wide, and
        # without the confirmation you cannot tell a near miss from a hit
        # until after you have spent the round.
        self.lock = Entity(parent=self.reticle, enabled=False)
        for sx in (-1, 1):
            for sy in (-1, 1):
                for w, h in ((0.016, 0.003), (0.003, 0.016)):
                    Entity(parent=self.lock, model="quad", scale=(w, h),
                           shader=unlit_shader, color=color.rgb32(240, 78, 40),
                           position=(sx * (0.052 - w / 2), sy * (0.052 - h / 2),
                                     -0.03))

        # Four diagonal ticks that flash on a kill. In a light-gun game the
        # muzzle never moves, so without this the only confirmation of a hit
        # is a drone disappearing somewhere in peripheral vision.
        self.hitmark = Entity(parent=self.reticle, enabled=False)
        self.hitmark_scale = 1.0
        for angle in (45, 135, 225, 315):
            rad = math.radians(angle)
            Entity(parent=self.hitmark, model="quad", rotation_z=angle + 90,
                   position=(math.cos(rad) * 0.045, math.sin(rad) * 0.045, -0.03),
                   scale=(0.004, 0.022), shader=unlit_shader,
                   color=color.rgb32(255, 245, 235))

        # Dark on light: the room is white, so the readable HUD from the old
        # dark scene would have been invisible here.
        ink = color.rgb32(38, 44, 54)
        faint = color.rgb32(88, 96, 110)
        self.hud_score = Text(parent=camera.ui, text="", origin=(-0.5, 0.5),
                              position=(-0.86, 0.46), scale=1.1, color=ink)
        self.hud_timer = Text(parent=camera.ui, text="", origin=(0, 0.5),
                              position=(0, 0.46), scale=1.4, color=ink)
        self.hud_ammo = Text(parent=camera.ui, text="", origin=(0.5, 0.5),
                             position=(0.86, 0.46), scale=1.1, color=ink)
        self.hud_link = Text(parent=camera.ui, text="", origin=(-0.5, -0.5),
                             position=(-0.86, -0.46), scale=0.75, color=faint)
        # The device can be streaming perfectly while its gyro bias is known to
        # be wrong, which looks exactly like a gun that drifts for no reason.
        self.hud_warn = Text(parent=camera.ui, text="", origin=(0, -0.5),
                             position=(0, -0.36), scale=0.95,
                             color=color.rgb32(214, 96, 40))
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
        self.effects.clear()
        for text, _ in self.popups:
            destroy(text)
        self.popups.clear()
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
            position=Vec3(random.uniform(-8.5, 8.5), random.uniform(1.9, 7.4),
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

        hit = raycast(camera.world_position, self.aim_ray(), distance=60,
                      debug=False)
        self.lock.enabled = bool(hit.hit and hit.entity in self.targets)

    def aim_ray(self) -> Vec3:
        """World-space direction the reticle is pointing."""
        scale = view_scale()
        return Vec3(
            camera.forward
            + camera.right * (self.reticle_pos.x * scale)
            + camera.up * (self.reticle_pos.y * scale)
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
        self.muzzle_light.color = color.rgba32(255, 190, 90, 130)
        invoke(setattr, self.muzzle_light, "color", color.rgba32(255, 190, 90, 0),
               delay=0.05)
        self.shake = 0.09

        direction = self.aim_ray()
        hit = raycast(camera.world_position, direction, distance=60, debug=False)
        # The tracer leaves from below the eye rather than from the camera
        # itself, which would put it exactly behind the reticle and make it
        # invisible. Slung low and right, it reads as coming from the gun.
        muzzle = (camera.world_position + camera.down * 0.34 + camera.right * 0.22
                  + camera.forward * 1.4)
        end = hit.world_point if hit.hit else camera.world_position + direction * 60
        self.effects.tracer(muzzle, end)

        if hit.hit and hit.entity in self.targets:
            self.register_hit(hit.entity)
        elif hit.hit:
            self.effects.impact(Vec3(hit.world_point), Vec3(hit.world_normal))

    def register_hit(self, target: Entity) -> None:
        self.hits += 1
        # Smaller and further targets are worth more.
        distance = (target.world_position - camera.world_position).length()
        points = int(40 + (1.3 - target.scale_x) * 60 + distance * 3)
        self.score += points
        self.effects.burst(Vec3(target.world_position), target.scale_x)
        self.popup(target.world_position, points)
        self.hitmark.enabled = True
        self.hitmark_scale = 1.5
        self.hitmark.scale = 1.5
        self.shake = 0.16
        self.targets.remove(target)
        # Only a light shove downrange: enough to sell the impact, not enough
        # to carry the wreck through the back wall before it hits the floor.
        push = Vec3(target.drift.x, 1.6, 1.2) + Vec3(
            random.uniform(-1.5, 1.5), random.uniform(0, 1.2),
            random.uniform(-0.8, 0.8))
        self.effects.wreck(target, push)
        self.spawn_target()

    def popup(self, world_position: Vec3, points: int) -> None:
        """Float the score for a kill up from where the drone was."""
        if world_position.z - camera.world_position.z <= 0.1:
            return
        ui = world_to_ui(Vec3(world_position))
        text = Text(parent=camera.ui, text=f"+{points}", origin=(0, 0), scale=0.9,
                    color=color.rgb32(232, 108, 58),
                    position=(ui.x, ui.y, -0.05))
        self.popups.append([text, 0.9])

    # -- per frame --------------------------------------------------------
    def update(self, dt: float) -> None:
        state = self.source.snapshot()
        self.update_aim()
        self.effects.update(dt)
        self._update_feedback(dt)

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
                if not 1.5 < target.y < 7.8:
                    target.drift.y *= -1
                target.bob += dt
                # A slight hover wobble and a bank into the turn, so they read
                # as flying rather than sliding along a rail.
                target.y += math.sin(target.bob * 3.1) * dt * 0.35
                target.rotation_z = -target.drift.x * 7
                for rotor in target.rotors:
                    rotor.rotation_y += 1400 * dt

        self.refresh_hud(state)

    def _update_feedback(self, dt: float) -> None:
        # Recoil kick. The camera is fixed in a light-gun game, so a short
        # decaying jolt is the only thing that gives a shot any weight.
        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt * 0.6)
            camera.position = self.camera_home + Vec3(
                random.uniform(-1, 1) * self.shake,
                random.uniform(-1, 1) * self.shake,
                0,
            )
        elif camera.position != self.camera_home:
            camera.position = self.camera_home

        if self.hitmark.enabled:
            self.hitmark_scale = max(1.0, self.hitmark_scale - dt * 6)
            self.hitmark.scale = self.hitmark_scale
            if self.hitmark_scale <= 1.0 and self.shake <= 0.02:
                self.hitmark.enabled = False

        alive = []
        for entry in self.popups:
            text, remaining = entry
            remaining -= dt
            if remaining <= 0:
                destroy(text)
                continue
            text.y += dt * 0.12
            text.alpha = min(1.0, remaining * 2.5)
            alive.append([text, remaining])
        self.popups = alive

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
        self.hud_warn.text = ("" if state.bias_ok else
                              "gyro bias not trusted - rest the gun on the "
                              "desk for a second")
        link = state.source if state.connected else "no controller"
        self.hud_link.text = f"{link}   {self.rate} Hz   [space] fire  [c] centre  [esc] quit"


def check_projection_against_render(report) -> None:
    """Compare `world_to_ui` with where the renderer actually puts things.

    This exists because the shooting checks below cannot catch a wrong
    projection. They place a target along `aim_ray` and then fire along
    `aim_ray`, so they agree with themselves at any scale factor -- including
    the aspect-ratio error that shipped, where every shot away from the centre
    landed well off the crosshair while all six checks passed.

    The only non-circular reference is the rendered image. Markers go at known
    world points, the frame is read back, and the pixels have to agree.
    Positions are measured relative to a marker on the camera axis, which
    cancels any constant offset between window and framebuffer coordinates.
    """
    try:
        import numpy as np
        from PIL import Image
        from panda3d.core import Filename
    except ImportError as exc:
        print(f"  skip  projection vs render ({exc})")
        return

    # Colours the scene and HUD do not contain, so the nearest pixel to each is
    # unambiguously its marker.
    marks = [
        (Vec3(0, 0, 12), (255, 0, 255)),   # on the camera axis: the origin
        (Vec3(4.5, 0, 12), (0, 255, 0)),
        (Vec3(0, 3.0, 12), (0, 128, 255)),
        (Vec3(-6.0, -1.6, 16), (255, 255, 0)),
        (Vec3(7.0, 2.4, 20), (0, 255, 128)),
    ]
    spawned = []
    for offset, rgb in marks:
        spawned.append(Entity(
            model="sphere", scale=0.45, shader=unlit_shader,
            color=color.rgb32(*rgb),
            position=camera.world_position + Vec3(offset.x, offset.y, offset.z)))

    base = application.base
    for _ in range(2):
        base.graphicsEngine.renderFrame()
    path = "/tmp/range3d_projection.png"
    base.win.saveScreenshot(Filename.fromOsSpecific(path))

    frame = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    height, width, _ = frame.shape
    aspect = window.aspect_ratio

    def rendered_ui(rgb):
        distance = np.abs(frame - np.array(rgb, dtype=np.int16)).sum(axis=2)
        mask = distance < 60
        if not mask.any():
            return None
        ys, xs = np.nonzero(mask)
        # Centroid of the whole blob, so the answer is not one stray pixel.
        return ((xs.mean() / width - 0.5) * aspect, 0.5 - ys.mean() / height)

    origin = rendered_ui(marks[0][1])
    if origin is None:
        report("projection markers rendered", False)
        for e in spawned:
            destroy(e)
        return

    worst = 0.0
    for offset, rgb in marks[1:]:
        drawn = rendered_ui(rgb)
        if drawn is None:
            report(f"marker {rgb} was rendered", False)
            continue
        want = world_to_ui(camera.world_position + offset)
        got = (drawn[0] - origin[0], drawn[1] - origin[1])
        worst = max(worst, abs(got[0] - want.x), abs(got[1] - want.y))
        print(f"        {str(rgb):<18} drawn ({got[0]:+.3f},{got[1]:+.3f})  "
              f"predicted ({want.x:+.3f},{want.y:+.3f})")

    # A factor-of-aspect error puts these 0.2 to 0.4 UI units apart, so this
    # tolerance is far tighter than the bug it is here to catch.
    report(f"projection matches the render (worst {worst:.3f} UI)", worst < 0.02)

    for e in spawned:
        destroy(e)


def run_selftest(game: "Range3D") -> None:
    """Check that a shot lands where the reticle is drawn."""
    failures = 0

    def check(name: str, got, want) -> None:
        nonlocal failures
        if got == want:
            print(f"  ok    {name:<44} {got}")
        else:
            print(f"  FAIL  {name:<44} got {got!r}, want {want!r}")
            failures += 1

    def report(name: str, ok: bool) -> None:
        nonlocal failures
        if ok:
            print(f"  ok    {name}")
        else:
            print(f"  FAIL  {name}")
            failures += 1

    game.state = "playing"
    for t in list(game.targets):
        destroy(t)
    game.targets.clear()

    # Anchor the projection to the renderer before anything below leans on it.
    check_projection_against_render(report)

    # The two directions must invert each other exactly, or the reticle, the
    # score popups and the shots would each be using a different idea of where
    # a screen position is.
    worst = 0.0
    for ux, uy in ((0, 0), (0.6, 0.35), (-0.6, -0.35), (0.9, -0.2)):
        game.reticle_pos = Vec2(ux, uy)
        back = world_to_ui(camera.world_position + game.aim_ray() * 14.0)
        worst = max(worst, abs(back.x - ux), abs(back.y - uy))
    report(f"reticle to ray and back agree (worst {worst:.4f} UI)",
           worst < 0.001)

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
    parser.add_argument("--reset", action="store_true",
                        help="reboot the board on connect, forcing it to "
                             "recalibrate. Off by default: it would otherwise "
                             "measure gyro bias exactly as you pick the gun up")
    parser.add_argument("--frames", type=int, default=0,
                        help="quit after N frames (for automated checks)")
    parser.add_argument("--shot", help="save a screenshot before quitting")
    parser.add_argument("--selftest", action="store_true",
                        help="check the reticle and the raycast agree, then exit")
    parser.add_argument("--demo", action="store_true",
                        help="play the round automatically, for screenshots")
    args = parser.parse_args()

    source = AimSource()
    if args.simulate:
        worker = threading.Thread(target=simulate, args=(source,), daemon=True)
    else:
        worker = threading.Thread(
            target=read_serial,
            args=(source, args.port, args.baud, args.reset),
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

        if args.demo:
            if game.state != "playing":
                game.start_round()
            # Walk the reticle onto a drone and shoot it, so a screenshot
            # catches the game mid-fight instead of at the ready banner.
            if game.targets and counters["frames"] % 20 == 0:
                target = game.targets[counters["frames"] // 20 % len(game.targets)]
                ui = world_to_ui(Vec3(target.world_position))
                shot = counters["frames"] // 20
                # Every fourth shot is thrown wide on purpose, so the demo
                # exercises the wall impact path and not just clean kills.
                miss = 0.14 if shot % 4 == 3 else 0.0
                game.reticle_pos = Vec2(ui.x + miss, ui.y - miss)
                game.reticle.position = (game.reticle_pos.x, game.reticle_pos.y, 0)
                game.ammo = MAG_SIZE
                game.fire()

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
