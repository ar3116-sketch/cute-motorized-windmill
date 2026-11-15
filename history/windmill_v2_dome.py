# Motorized Dutch tower windmill for the design-class brief ("Divide Continuous Surface" + "Merge Surfaces").
# Source of truth: change numbers here and re-run, never edit the outputs.
# Run headless:  freecadcmd windmill.py   (OUT_DIR env var or this folder) -> Windmill.FCStd, windmill_results.json,
#                colors.json, stl/*.stl
# Frame: origin at the centre of the base on the floor, Z up, +X = front (the sails face +X). mm.
import os, json, math
import FreeCAD as App, Part, Mesh, MeshPart
from FreeCAD import Vector as V

OUT_DIR = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))

# ---------- Requirements (limit, source) ----------
ENVELOPE = (101.6, 101.6, 152.4)  # user: 4 x 4 x 6 in max (same as the rally car brief), sails included while running
PRINTER = (256.0, 256.0, 256.0)   # user: printer build volume (rally car brief)
CLEAR_MIN = 1.0                   # mm, minimum running clearance for moving parts (assumed, FDM)

# ---------- Bought / owned parts (dimensions) ----------
# TT gear motor 1:48 (Adafruit 3777 drawing): gearbox 37 x 22.44 x 18.6, can + gearbox + tab = 70 long,
# output shaft dia 5.4 with 3.7 across flats, protruding 9.3 (front) and 8.7 (rear).
# Shaft position along the gearbox is read from the drawing as 14.0 from the tab hole, tab 4.8 long: ASSUMED, measure.
TT = dict(gb_L=37.0, gb_H=22.44, gb_T=18.6, can_L=28.2, can_W=20.4, can_T=18.0, tab_L=4.8, tab_H=10.0, tab_T=3.0,
          shaft_d=5.4, shaft_flat=3.7, shaft_front=9.3, shaft_rear=8.7, shaft_from_can_end=25.4,
          rpm_3v=(90, 120), stall_kgcm_3v=0.4)
BATT = dict(L=58.0, W=32.0, H=16.0)           # 2 x AA holder with leads: ASSUMED typical, measure yours
SWITCH = dict(L=8.6, W=3.6, H=3.5, lever=4.0)  # SS-12F15 slide switch body
MAG = dict(d=6.0, t=2.0)                       # 6 x 2 mm N52 disc magnets
ROD_D = 3.0                                    # windshaft: 3 mm steel rod (or an M3 x 75 screw with the head cut off)

# ---------- Parameters ----------
BASE_AF, BASE_H = 96.0, 22.0       # octagonal plinth across flats, height
LID_T = 2.0                        # removable bottom lid under the battery bay
FLOOR_TOP = BASE_H                 # tower floor = plinth top
TOWER_AF0, TOWER_AF1 = 80.0, 58.0  # v2: chunkier, less taper (cuter)  # smock tower across flats at bottom / top
TOWER_TOP = 96.0
WALL = 2.4
STAGE_Z, STAGE_T, STAGE_AF = 42.0, 2.5, 92.0   # stage (gallery) merged into the tower
RAIL_H = 6.0
CURB_IN_AF, CURB_H = 38.0, 4.0     # thick ring at the tower top: carries the cap magnets
SHAFT_Z = 102.0                    # windshaft height
SAIL_R = 48.0                      # sail tip radius
M_GEAR = 1.0                       # gear module
Z_PIN, Z_GEAR = 12, 36             # 3:1 reduction
GEAR_FACE = 5.0
X_MOTOR = -4.0                     # centre of the TT gearbox thickness (along X)
CAP_X = (-32.0, 32.0)
CAP_W, CAP_H = 58.0, 32.0
HUB_X0, HUB_L, HUB_D = 34.0, 7.8, 14.0
DOME_R, DOME_H, DOME_T = 31.5, 33.0, 2.0     # v2 cap: round dome
BRIM_R, BRIM_H = 32.8, 2.2
FINIAL_R = 3.2
CROSS_X0, CROSS_T, STOCK_W = 41.8, 3.0, 4.0
SAIL_IN, SAIL_W, SAIL_T = 13.0, 15.0, 1.6
POST_W = 8.0

CD = M_GEAR * (Z_PIN + Z_GEAR) / 2.0           # 24 mm centre distance
MOTOR_Z = SHAFT_Z - CD                         # TT output shaft height
results = {"checks": {}, "parts": {}, "notes": []}


def record(name, value, limit, ok):
    results["checks"][name] = {"value": value, "limit": limit, "pass": bool(ok)}
    print(("PASS " if ok else "FAIL ") + name, value, limit)


C225 = math.cos(math.radians(22.5))


def oct_wire(af, z, x0=0.0, y0=0.0):
    r = af / 2.0 / C225
    pts = [V(x0 + r * math.cos(math.radians(22.5 + 45 * k)), y0 + r * math.sin(math.radians(22.5 + 45 * k)), z) for k in range(8)]
    return Part.makePolygon(pts + [pts[0]])


def oct_prism(af, z0, z1):
    return Part.Face(oct_wire(af, z0)).extrude(V(0, 0, z1 - z0))


def frustum(af0, af1, z0, z1):
    return Part.makeLoft([oct_wire(af0, z0), oct_wire(af1, z1)], True, True)


def af_at(z):
    return TOWER_AF0 + (TOWER_AF1 - TOWER_AF0) * (z - FLOOR_TOP) / (TOWER_TOP - FLOOR_TOP)


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cyl_x(r, x0, x1, y=0.0, z=0.0):
    return Part.makeCylinder(r, x1 - x0, V(x0, y, z), V(1, 0, 0))


def cyl_z(r, z0, z1, x=0.0, y=0.0):
    return Part.makeCylinder(r, z1 - z0, V(x, y, z0), V(0, 0, 1))


def one_solid(s):
    s = s.removeSplitter()
    return s.Solids[0] if len(s.Solids) == 1 else s


# ---------- gears (involute spur, profile in the YZ plane, extruded along X) ----------
def gear_face(z, m, cy, cz, bore=None):
    rp = m * z / 2.0; rb = rp * math.cos(math.radians(20)); ra = rp + m; rf = rp - 1.25 * m
    inv = lambda a: math.tan(a) - a
    # half tooth angle at the pitch circle
    half = math.pi / (2 * z) + inv(math.radians(20))
    pts = []
    n = 6
    for k in range(z):
        th = 2 * math.pi * k / z
        flank = []
        for i in range(n + 1):
            r = max(rb, rf) + (ra - max(rb, rf)) * i / n
            a = math.acos(min(1.0, rb / r))
            flank.append((r, half - inv(a)))
        left = [(th - phi, r) for r, phi in flank]
        right = [(th + phi, r) for r, phi in reversed(flank)]
        root_a = th - half - (math.pi / z - half) * 0.5
        pts.append((th - math.pi / z, rf))
        pts += [(a_, r) for a_, r in left]
        pts += [(a_, r) for a_, r in right]
    xyz = [V(0, cy + r * math.cos(a), cz + r * math.sin(a)) for a, r in pts]
    clean = [xyz[0]]
    for p in xyz[1:]:
        if (p - clean[-1]).Length > 1e-3: clean.append(p)
    if (clean[0] - clean[-1]).Length < 1e-3: clean.pop()
    return Part.Face(Part.makePolygon(clean + [clean[0]]))


def gear_solid(z, x0, cy, cz, bore_d, flat=None):
    f = gear_face(z, M_GEAR, cy, cz)
    g = f.extrude(V(GEAR_FACE, 0, 0)); g.translate(V(x0, 0, 0))
    hole = cyl_x(bore_d / 2, x0 - 1, x0 + GEAR_FACE + 1, cy, cz)
    if flat is not None:   # D or double-D: keep the hole between the flats
        keep = box(x0 - 1, x0 + GEAR_FACE + 1, cy - bore_d, cy + bore_d, cz - flat / 2, cz + flat / 2)
        hole = hole.common(keep)
    return one_solid(g.cut(hole))


# ---------- TT motor (vendor reference, upright: can down, output shaft along X) ----------
gb_z0 = MOTOR_Z - TT["shaft_from_can_end"]
gb_x0, gb_x1 = X_MOTOR - TT["gb_T"] / 2, X_MOTOR + TT["gb_T"] / 2
tt_gearbox = box(gb_x0, gb_x1, -TT["gb_H"] / 2, TT["gb_H"] / 2, gb_z0, gb_z0 + TT["gb_L"])
tt_can = box(X_MOTOR - TT["can_T"] / 2, X_MOTOR + TT["can_T"] / 2, -TT["can_W"] / 2, TT["can_W"] / 2, gb_z0 - TT["can_L"], gb_z0)
tt_can = tt_can.makeFillet(4.0, [e for e in tt_can.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[-1].Point.z) > 1])
tt_tab = box(X_MOTOR - TT["tab_T"] / 2, X_MOTOR + TT["tab_T"] / 2, -TT["tab_H"] / 2, TT["tab_H"] / 2, gb_z0 + TT["gb_L"], gb_z0 + TT["gb_L"] + TT["tab_L"])
tt_body = tt_gearbox.fuse([tt_can, tt_tab]).removeSplitter()
tt_shaft = cyl_x(TT["shaft_d"] / 2, gb_x0 - TT["shaft_rear"], gb_x1 + TT["shaft_front"], 0, MOTOR_Z)
tt_shaft = tt_shaft.common(box(gb_x0 - 20, gb_x1 + 20, -5, 5, MOTOR_Z - TT["shaft_flat"] / 2, MOTOR_Z + TT["shaft_flat"] / 2))
motor_top = gb_z0 + TT["gb_L"] + TT["tab_L"]

# ---------- MERGED BODY: plinth + tower + stage + rail + curb + bearing posts + motor cradle (one print) ----------
plinth = oct_prism(BASE_AF, LID_T, BASE_H)
plinth = plinth.fuse(frustum(BASE_AF, BASE_AF - 3.0, BASE_H - 2.5, BASE_H))   # chamfered top edge into the tower
tower_out = frustum(TOWER_AF0, TOWER_AF1, FLOOR_TOP - 0.01, TOWER_TOP)
tower_in = frustum(TOWER_AF0 - 2 * WALL, TOWER_AF1 - 2 * WALL, FLOOR_TOP + 3.0, TOWER_TOP + 0.5)
stage = oct_prism(STAGE_AF, STAGE_Z, STAGE_Z + STAGE_T).cut(frustum(TOWER_AF0 - 2 * WALL, TOWER_AF1 - 2 * WALL, FLOOR_TOP, TOWER_TOP))
rail = oct_prism(STAGE_AF, STAGE_Z + STAGE_T + RAIL_H - 1.2, STAGE_Z + STAGE_T + RAIL_H).cut(oct_prism(STAGE_AF - 2.4, 0, 200))
posts = []
r_post = STAGE_AF / 2 / C225 - 1.2
for k in range(8):
    a = math.radians(22.5 + 45 * k)
    posts.append(cyl_z(0.8, STAGE_Z + STAGE_T - 0.2, STAGE_Z + STAGE_T + RAIL_H, r_post * math.cos(a), r_post * math.sin(a)))
    a2 = math.radians(45 * k)   # mid-flat posts
    rm = STAGE_AF / 2 - 1.2
    posts.append(cyl_z(0.8, STAGE_Z + STAGE_T - 0.2, STAGE_Z + STAGE_T + RAIL_H, rm * math.cos(a2), rm * math.sin(a2)))
brackets = []   # stage knee braces merge the stage underside into the tower wall
for k in range(8):
    a = math.radians(45 * k)
    r_in = af_at(STAGE_Z - 8) / 2 - 1.0
    b = box(r_in, STAGE_AF / 2 - 3, -0.9, 0.9, STAGE_Z - 8, STAGE_Z)
    b = b.cut(Part.makeCylinder(8, 2, V(STAGE_AF / 2 - 3, -1, STAGE_Z - 8), V(0, 1, 0)))
    b.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(a)); brackets.append(b)
curb = frustum(af_at(TOWER_TOP - CURB_H), TOWER_AF1, TOWER_TOP - CURB_H, TOWER_TOP).cut(oct_prism(CURB_IN_AF, 0, 200))
post_f = box(21.0, 25.5, -POST_W / 2, POST_W / 2, TOWER_TOP - 2, SHAFT_Z + 4)
post_r = box(-25.5, -21.0, -POST_W / 2, POST_W / 2, TOWER_TOP - 2, SHAFT_Z + 4)
for p_ in (post_f, post_r):
    pass
# motor cradle: a sleeve round the gearbox, webbed to the rear and side walls; can rests on a seat pad
cl = 0.3
x_g0 = gb_x1 + 3.5                             # gear plane on the front shaft, 3.5 mm off the gearbox face
sleeve_o = box(gb_x0 - cl - 2.0, gb_x1 + cl + 2.0, -TT["gb_H"] / 2 - cl - 2.0, TT["gb_H"] / 2 + cl + 2.0, gb_z0 + 4, gb_z0 + TT["gb_L"] - 2)
web_l = box(gb_x0 - 1, gb_x1 + 1, TT["gb_H"] / 2 + 1, af_at(gb_z0 + 4) / 2, gb_z0 + 4, gb_z0 + 12)
web_r = box(gb_x0 - 1, gb_x1 + 1, -af_at(gb_z0 + 4) / 2, -TT["gb_H"] / 2 - 1, gb_z0 + 4, gb_z0 + 12)
web_b = box(-af_at(gb_z0 + 4) / 2, gb_x0 - 1, -6, 6, gb_z0 + 4, gb_z0 + 12)
seat = box(X_MOTOR - 7, X_MOTOR + 7, -7, 7, FLOOR_TOP, gb_z0 - TT["can_L"] - 0.3)
body = plinth.fuse([tower_out, stage, rail, curb, post_f, post_r, sleeve_o, web_l, web_r, web_b, seat] + posts + brackets)
body = body.cut(tower_in)
# re-add the parts the inner cut removed (cradle, webs, seat, posts and curb live inside the tower envelope)
body = body.fuse([curb, post_f, post_r, sleeve_o.common(tower_out), web_l.common(tower_out), web_r.common(tower_out),
                  web_b.common(tower_out), seat])
# gearbox pocket open at the top (motor drops in from above), shaft slots front and rear
pocket = box(gb_x0 - cl, gb_x1 + cl, -TT["gb_H"] / 2 - cl, TT["gb_H"] / 2 + cl, gb_z0 - TT["can_L"] - 1, 200)
shaft_slot = box(gb_x0 - 30, gb_x1 + 30, -4.0, 4.0, MOTOR_Z - 4.0, 200)
body = body.cut(pocket).cut(shaft_slot.common(box(gb_x0 - 30, gb_x1 + 30, -4, 4, MOTOR_Z - 4, gb_z0 + TT["gb_L"])).common(tower_in))
# windshaft holes in the two bearing posts
body = body.cut(cyl_x(ROD_D / 2 + 0.2, -60, 60, 0, SHAFT_Z))
# battery bay (open below, closed by the lid), wire hole, switch window, lid screw bosses
bay = box(-BATT["L"] / 2 - 1, BATT["L"] / 2 + 1, -BATT["W"] / 2 - 1, BATT["W"] / 2 + 1, LID_T - 1, LID_T + BATT["H"] + 1)
body = body.cut(bay)
body = body.cut(cyl_z(3.5, LID_T + BATT["H"], FLOOR_TOP + 4, -14, 0))
sw_y = -BASE_AF / 2
body = body.cut(box(-12 - SWITCH["L"] / 2 - 0.3, -12 + SWITCH["L"] / 2 + 0.3, sw_y - 1, sw_y + 6, 8.0, 8.0 + SWITCH["H"] + 0.6))
LID_SCREWS = [(sx * 36.0, sy * 20.0) for sx in (-1, 1) for sy in (-1, 1)]
for x, y in LID_SCREWS:
    body = body.cut(cyl_z(0.8, LID_T - 0.5, LID_T + 8, x, y))          # 1.6 mm pilot for M2 x 8 self-tapping
# decorative door and windows (recessed 1 mm, not through)
xd = af_at(FLOOR_TOP) / 2
door = box(xd - 3, xd + 2, -7, 7, FLOOR_TOP, FLOOR_TOP + 11).fuse(Part.makeCylinder(7, 5, V(xd - 3, 0, FLOOR_TOP + 11), V(1, 0, 0)))
body = body.cut(door.cut(frustum(TOWER_AF0 - 3.0, TOWER_AF1 - 3.0, FLOOR_TOP - 1, TOWER_TOP + 1)))       # 1.5 mm deep arched door
step = box(xd - 1, xd + 3.5, -8.5, 8.5, FLOOR_TOP - 0.01, FLOOR_TOP + 1.6)
slope = (TOWER_AF0 - TOWER_AF1) / 2 / (TOWER_TOP - FLOOR_TOP)
tilt = math.degrees(math.atan(slope))                       # wall lean, so windows sit square to the wall
for zc, ang, r in ((62, 45, 3.6), (62, 135, 3.6), (62, 225, 3.6), (62, 315, 3.6), (80, 90, 3.2), (80, 270, 3.2), (80, 180, 3.2)):
    xw = af_at(zc) / 2
    hole = Part.makeCylinder(r, 2.2, V(-1.1, 0, 0), V(1, 0, 0))
    ring = Part.makeCylinder(r + 1.4, 2.0, V(-0.8, 0, 0), V(1, 0, 0)).cut(Part.makeCylinder(r, 4, V(-2, 0, 0), V(1, 0, 0)))
    for sh in (hole, ring):
        sh.rotate(V(0, 0, 0), V(0, 1, 0), -tilt); sh.translate(V(xw, 0, zc)); sh.rotate(V(0, 0, 0), V(0, 0, 1), ang)
    body = body.cut(hole).fuse(ring)
body = body.fuse(step)
# cap magnet pockets in the curb (from the top)
MAGNETS = [(23.0, 10.0), (23.0, -10.0), (-16.3, 16.3), (-16.3, -16.3)]
for x, y in MAGNETS:
    body = body.cut(cyl_z(MAG["d"] / 2 + 0.1, TOWER_TOP - MAG["t"] - 0.2, TOWER_TOP + 1, x, y))
# running-clearance pockets round both gears (wheel OD 38, pinion OD 14) through the merged body
gear_pocket = cyl_x(M_GEAR * (Z_GEAR + 2) / 2 + CLEAR_MIN + 0.2, x_g0 - CLEAR_MIN - 0.2, x_g0 + GEAR_FACE + CLEAR_MIN + 0.2, 0, SHAFT_Z)
pin_pocket = cyl_x(M_GEAR * (Z_PIN + 2) / 2 + CLEAR_MIN + 0.2, x_g0 - CLEAR_MIN - 0.2, x_g0 + GEAR_FACE + CLEAR_MIN + 0.2, 0, MOTOR_Z)
body = body.cut(gear_pocket).cut(pin_pocket)
body = one_solid(body)

# ---------- DIVIDE 1: removable cap (magnets) ----------
def ell_wire(x, w, h, z0):
    pts = [V(x, (w / 2) * math.cos(math.pi * i / 24), z0 + h * math.sin(math.pi * i / 24)) for i in range(25)]
    e = Part.BSplineCurve(); e.interpolate(pts)
    return Part.Wire([e.toShape(), Part.makeLine(pts[-1], pts[0])])


def half_ellipsoid(r, h, z0):
    sph = Part.makeSphere(1.0); m = App.Matrix(); m.scale(r, r, h)
    e = sph.transformGeometry(m).common(box(-r - 1, r + 1, -r - 1, r + 1, 0, h + 1)); e.translate(V(0, 0, z0)); return e


cap_o = half_ellipsoid(DOME_R, DOME_H, TOWER_TOP).fuse(cyl_z(BRIM_R, TOWER_TOP, TOWER_TOP + BRIM_H))
cap_i = half_ellipsoid(DOME_R - DOME_T, DOME_H - DOME_T, TOWER_TOP - 0.01).fuse(cyl_z(DOME_R - DOME_T, TOWER_TOP - 1, TOWER_TOP))
cap = cap_o.cut(cap_i)
cap_ring = cap_o.common(box(-60, 60, -60, 60, TOWER_TOP, TOWER_TOP + 2.5)).cut(oct_prism(42.0, 0, 200))
cap_ring = cap_ring.cut(box(20.5, 60, -POST_W / 2 - 0.5, POST_W / 2 + 0.5, 0, 200)).cut(box(-60, -20.5, -POST_W / 2 - 0.5, POST_W / 2 + 0.5, 0, 200))
cap_ring = cap_ring.cut(gear_pocket)
cap = cap.fuse([cap_ring] + [cyl_z(4.5, TOWER_TOP, TOWER_TOP + 4, x, y) for x, y in MAGNETS])
for x, y in MAGNETS:
    cap = cap.cut(cyl_z(MAG["d"] / 2 + 0.1, TOWER_TOP - 0.1, TOWER_TOP + MAG["t"] + 0.2, x, y))
cap = cap.cut(box(DOME_R - 8, BRIM_R + 2, -3.0, 3.0, TOWER_TOP - 1, SHAFT_Z + 3.0))      # front notch for the windshaft
cap = cap.cut(box(-BRIM_R - 2, -DOME_R + 8, -3.0, 3.0, TOWER_TOP - 1, SHAFT_Z + 3.0))    # rear notch
top = TOWER_TOP + DOME_H
cap = cap.fuse([cyl_z(1.3, top - 1.5, top + 4.5), Part.makeSphere(FINIAL_R, V(0, 0, top + 4.5 + FINIAL_R * 0.8))])   # little ball on top
cap = one_solid(cap)

# ---------- drive: pinion, wheel, windshaft, hub ----------
pinion = gear_solid(Z_PIN, x_g0, 0.0, MOTOR_Z, TT["shaft_d"] + 0.2, TT["shaft_flat"] + 0.15)
wheel = gear_solid(Z_GEAR, x_g0, 0.0, SHAFT_Z, ROD_D + 0.1, None)
wheel = one_solid(wheel.fuse(cyl_x(4.5, x_g0 - 4, x_g0, 0, SHAFT_Z).cut(cyl_x(ROD_D / 2 + 0.05, x_g0 - 5, x_g0 + 1, 0, SHAFT_Z))))
shaft_x0, shaft_x1 = -TOWER_AF1 / 2 - 1.0, CROSS_X0 + 3.0
windshaft = cyl_x(ROD_D / 2, shaft_x0, shaft_x1, 0, SHAFT_Z)
hub = cyl_x(HUB_D / 2, HUB_X0, HUB_X0 + HUB_L, 0, SHAFT_Z).fuse(box(HUB_X0 + HUB_L - 0.01, CROSS_X0 + CROSS_T, -4, 4, SHAFT_Z - 4, SHAFT_Z + 4))
hub = hub.fuse(cyl_x(HUB_D / 2 - 2.5, HUB_X0 - 0.01, HUB_X0, 0, SHAFT_Z))
hub = one_solid(hub.cut(cyl_x(ROD_D / 2 + 0.05, HUB_X0 - 1, CROSS_X0 + CROSS_T + 1, 0, SHAFT_Z)).cut(cyl_x(MAG["d"] / 2 + 0.1, CROSS_X0 + CROSS_T - MAG["t"] - 0.2, CROSS_X0 + CROSS_T + 1, 0, SHAFT_Z + 0.0).cut(cyl_x(ROD_D / 2 + 1.2, 0, 100, 0, SHAFT_Z))))
spinner = Part.makeSphere(4.5, V(CROSS_X0 + CROSS_T, 0, SHAFT_Z)).common(box(CROSS_X0 + CROSS_T, CROSS_X0 + CROSS_T + 5, -5, 5, SHAFT_Z - 5, SHAFT_Z + 5))


# ---------- DIVIDE 2: swappable sail crosses (lattice "open" set and solid "closed" set) ----------
def sail_cross(kind):
    parts = []
    stock = box(CROSS_X0, CROSS_X0 + CROSS_T, -SAIL_R, SAIL_R, -STOCK_W / 2, STOCK_W / 2)
    stock = stock.fuse(box(CROSS_X0, CROSS_X0 + CROSS_T, -STOCK_W / 2, STOCK_W / 2, -SAIL_R, SAIL_R))
    stock = stock.fuse(cyl_x(8.0, CROSS_X0, CROSS_X0 + CROSS_T))
    parts.append(stock)
    xs0, xs1 = CROSS_X0 + CROSS_T - SAIL_T - 0.4, CROSS_X0 + CROSS_T - 0.4
    for k in range(4):
        sail = []
        y0, y1 = SAIL_IN, SAIL_R - 1.0
        z0, z1 = STOCK_W / 2 - 0.2, STOCK_W / 2 + SAIL_W
        if kind == "solid":
            sail.append(box(xs0, xs1, y0, y1, z0, z1))
        else:
            sail += [box(xs0, xs1, y0, y1, z1 - 1.4, z1), box(xs0, xs1, y0, y0 + 1.4, z0, z1), box(xs0, xs1, y1 - 1.4, y1, z0, z1),
                     box(xs0, xs1, y0, y1, (z0 + z1) / 2 - 0.5, (z0 + z1) / 2 + 0.5)]
            n = 8
            for i in range(1, n):
                y = y0 + (y1 - y0) * i / n
                sail.append(box(xs0, xs1, y - 0.5, y + 0.5, z0, z1))
            # narrow leading-edge board on the other side of the stock
            sail.append(box(xs0, xs1, y0 + 4, y1, -STOCK_W / 2 - 3.0, -STOCK_W / 2 + 0.2))
        s = sail[0].fuse(sail[1:]) if len(sail) > 1 else sail[0]
        s.rotate(V(0, 0, 0), V(1, 0, 0), 90 * k)
        parts.append(s)
    c = parts[0].fuse(parts[1:]).removeSplitter()
    c.rotate(V(0, 0, 0), V(1, 0, 0), 45)                # display as an X
    c.translate(V(0, 0, SHAFT_Z))
    c = c.cut(box(CROSS_X0 - 1, CROSS_X0 + CROSS_T + 1, -4.15, 4.15, SHAFT_Z - 4.15, SHAFT_Z + 4.15))   # square socket on the hub key
    return one_solid(c)


sails_lattice = sail_cross("lattice")
sails_solid = sail_cross("solid")

# ---------- lid, battery holder, switch, magnets, wires ----------
lid = oct_prism(BASE_AF - 0.6, 0, LID_T)
for x, y in LID_SCREWS:
    lid = lid.cut(cyl_z(1.1, -1, LID_T + 1, x, y)).cut(cyl_z(2.1, -1, 1.0, x, y))
lid = one_solid(lid.cut(box(-6, 6, -1, 1, -1, 0.6)))
battery = box(-BATT["L"] / 2, BATT["L"] / 2, -BATT["W"] / 2, BATT["W"] / 2, LID_T + 0.3, LID_T + 0.3 + BATT["H"])
cells = [cyl_x(7.25, -25, 25, y, LID_T + 0.3 + 8.0) for y in (-7.6, 7.6)]
switch = box(-12 - SWITCH["L"] / 2, -12 + SWITCH["L"] / 2, sw_y + 0.6, sw_y + 0.6 + SWITCH["W"], 8.3, 8.3 + SWITCH["H"]).fuse(
    box(-13, -11, sw_y - 1.6, sw_y + 1, 9.2, 10.8))
magnets = [cyl_z(MAG["d"] / 2, TOWER_TOP - MAG["t"], TOWER_TOP, x, y) for x, y in MAGNETS] + \
          [cyl_z(MAG["d"] / 2, TOWER_TOP, TOWER_TOP + MAG["t"], x, y) for x, y in MAGNETS] + \
          [cyl_x(MAG["d"] / 2, CROSS_X0 + CROSS_T - MAG["t"], CROSS_X0 + CROSS_T, 0, SHAFT_Z)]


def wire_path(pts, r=0.8):
    sh = []
    for a, b in zip(pts, pts[1:]):
        a, b = V(*a), V(*b)
        sh.append(Part.makeCylinder(r, (b - a).Length, a, b - a)); sh.append(Part.makeSphere(r, b))
    return sh[0].fuse(sh[1:])


w_red = wire_path([(-14, 3, LID_T + 10), (-14, 1.5, FLOOR_TOP + 6), (-8, 6, gb_z0 - TT["can_L"] - 2), (X_MOTOR + 9, 6, gb_z0 - TT["can_L"] + 4)])
w_blk = wire_path([(-14, -2, LID_T + 10), (-14, -1.5, FLOOR_TOP + 6), (-8, -6, gb_z0 - TT["can_L"] - 2), (X_MOTOR + 9, -6, gb_z0 - TT["can_L"] + 4)])
w_sw = wire_path([(-25, -12, LID_T + 9), (-12, sw_y + 5, 9.5)])

# ---------- checks ----------
def overlap(a, b):
    try:
        return a.common(b).Volume
    except Exception:
        return -1.0


printed = {"Body_merged": body, "Cap": cap, "Lid": lid, "Hub": hub, "Pinion_12T": pinion, "Wheel_36T": wheel,
           "Sails_lattice": sails_lattice, "Sails_solid": sails_solid}
for n, s in printed.items():
    bb = tight_bb(s) if 'tight_bb' in globals() else s.BoundBox
    results["parts"][n] = {"valid": s.isValid(), "solids": len(s.Solids), "bbox_mm": [round(bb.XLength, 1), round(bb.YLength, 1), round(bb.ZLength, 1)],
                           "volume_cm3": round(s.Volume / 1000, 2)}
    record(f"printed_part_ok/{n}", [s.isValid(), len(s.Solids)], [True, 1], s.isValid() and len(s.Solids) == 1)
    record(f"fits_printer/{n}", sorted([round(bb.XLength, 1), round(bb.YLength, 1), round(bb.ZLength, 1)]), PRINTER, max(bb.XLength, bb.YLength, bb.ZLength) <= min(PRINTER))

sweep = Part.makeCylinder(SAIL_R + 0.5, CROSS_T + 0.6, V(CROSS_X0 - 0.3, 0, SHAFT_Z), V(1, 0, 0))   # sail disc while turning
assembly_display = [body, cap, lid, hub, pinion, wheel, windshaft, sweep, spinner]
def tight_bb(sh):   # BoundBox is loose on spline faces (it uses control points); optimalBoundingBox is exact
    try:
        return sh.optimalBoundingBox(True, False)
    except Exception:
        return sh.BoundBox
bb = tight_bb(assembly_display[0])
for s in assembly_display[1:]: bb.add(tight_bb(s))
size = [round(bb.XLength, 2), round(bb.YLength, 2), round(bb.ZLength, 2)]
record("envelope_running_with_sail_sweep_mm", size, list(ENVELOPE), all(a <= b for a, b in zip(size, ENVELOPE)))
record("envelope_centred_x_y_mm", [round(bb.XMin, 2), round(bb.XMax, 2), round(bb.YMin, 2), round(bb.YMax, 2)],
       [-ENVELOPE[0] / 2, ENVELOPE[0] / 2], bb.XMin >= -ENVELOPE[0] / 2 and bb.XMax <= ENVELOPE[0] / 2 and bb.YMin >= -ENVELOPE[1] / 2 and bb.YMax <= ENVELOPE[1] / 2)

pairs = {"motor_vs_body": (tt_body, body), "motor_shaft_vs_body": (tt_shaft, body), "motor_vs_cap": (tt_body, cap),
         "pinion_vs_body": (pinion, body), "wheel_vs_body": (wheel, body), "wheel_vs_cap": (wheel, cap), "pinion_vs_cap": (pinion, cap),
         "wheel_vs_motor": (wheel, tt_body), "sail_sweep_vs_body": (sweep, body), "sail_sweep_vs_cap": (sweep, cap),
         "hub_vs_cap": (hub, cap), "battery_vs_body": (battery, body), "battery_vs_lid": (battery, lid), "switch_vs_body": (switch, body),
         "windshaft_vs_body": (windshaft, body), "windshaft_vs_cap": (windshaft, cap)}
for n, (a, b_) in pairs.items():
    v = overlap(a, b_)
    record(f"no_interference/{n}_mm3", round(v, 3), 0.0, 0 <= v < 0.01)

# running clearances for the moving parts (distance between solids)
for n, (a, b_) in {"wheel_to_body": (wheel, body), "wheel_to_cap": (wheel, cap), "pinion_to_body": (pinion, body),
                   "sails_to_body": (sails_lattice, body), "sails_to_cap": (sails_lattice, cap), "hub_to_cap": (hub, cap)}.items():
    d = a.distToShape(b_)[0]
    record(f"running_clearance/{n}_mm", round(d, 2), CLEAR_MIN, d >= CLEAR_MIN)

record("gear_centre_distance_mm", round(SHAFT_Z - MOTOR_Z, 3), CD, abs((SHAFT_Z - MOTOR_Z) - CD) < 0.01)
rpm = [round(r * Z_PIN / Z_GEAR, 1) for r in TT["rpm_3v"]]
record("sail_rpm_at_3V", rpm, "15 to 60 (assumed: reads as a windmill, not a fan)", 15 <= rpm[0] and rpm[1] <= 60)
results["notes"] += [
    "Merge Surfaces: plinth, tower, stage and rail, knee braces, curb ring, both windshaft bearing posts, motor cradle and seat are one printed body (Body_merged).",
    "Divide Continuous Surface: the cap lifts off on 4 magnet pairs (asymmetric pattern keys its orientation); the sail cross pulls off the hub key (1 magnet) and swaps between the lattice and solid sets; the lid opens for the batteries.",
    "TT motor shaft position along the gearbox (25.4 mm from the can end) is read from the Adafruit drawing: measure before printing the cradle.",
    "2 x AA holder size 58 x 32 x 16 mm is assumed: measure yours.",
]
results["drive"] = {"centre_distance_mm": CD, "ratio": Z_GEAR / Z_PIN, "motor_rpm_3V": TT["rpm_3v"], "sail_rpm_3V": rpm,
                    "sail_tip_speed_m_s": [round(r * 2 * math.pi * SAIL_R / 1000 / 60, 2) for r in rpm]}

# ---------- document ----------
doc = App.newDocument("Windmill")
COL = {}


def add(name, shape, color, group=None, label=None):
    o = doc.addObject("Part::Feature", name); o.Shape = shape
    if label: o.Label = label
    COL[name] = color
    if group: group.addObject(o)
    return o


g_print = doc.addObject("App::DocumentObjectGroup", "Printed")
g_buy = doc.addObject("App::DocumentObjectGroup", "Bought")
g_alt = doc.addObject("App::DocumentObjectGroup", "Alternate_sails")
add("Body_merged", body, (0.97, 0.92, 0.82), g_print, "Body (merged: plinth, tower, stage, cradle, bearings)")
add("Cap", cap, (0.91, 0.47, 0.44), g_print, "Cap (divided, magnets)")
add("Lid", lid, (0.52, 0.72, 0.86), g_print, "Battery lid")
add("Hub", hub, (0.52, 0.72, 0.86), g_print)
add("Pinion_12T", pinion, (0.85, 0.65, 0.20), g_print)
add("Wheel_36T", wheel, (0.85, 0.65, 0.20), g_print)
add("Sails_lattice", sails_lattice, (0.99, 0.98, 0.95), g_print, "Sail cross - lattice (divided, swappable)")
add("Sails_solid", sails_solid, (0.62, 0.84, 0.74), g_alt, "Sail cross - solid (alternate set)")
add("TT_motor", tt_body, (0.98, 0.80, 0.10), g_buy, "TT gear motor 1:48")
add("TT_shaft", tt_shaft, (0.95, 0.95, 0.95), g_buy)
add("Windshaft_3mm", windshaft, (0.72, 0.74, 0.77), g_buy, "Windshaft 3 mm rod")
add("Battery_2xAA", battery.fuse(cells), (0.12, 0.12, 0.13), g_buy, "2 x AA holder")
add("Switch", switch, (0.15, 0.35, 0.75), g_buy)
add("Magnets", Part.makeCompound(magnets), (0.75, 0.76, 0.78), g_buy)
add("Spinner", spinner, (0.91, 0.47, 0.44), g_print)
add("Wire_red", w_red, (0.85, 0.10, 0.08), g_buy)
add("Wire_black", w_blk, (0.08, 0.08, 0.08), g_buy)
add("Wire_switch", w_sw, (0.85, 0.10, 0.08), g_buy)
doc.recompute()
doc.saveAs(os.path.join(OUT_DIR, "Windmill.FCStd"))
json.dump({k: list(v) for k, v in COL.items()}, open(os.path.join(OUT_DIR, "colors.json"), "w"), indent=1)

os.makedirs(os.path.join(OUT_DIR, "stl"), exist_ok=True)
for n, s in printed.items():
    m = MeshPart.meshFromShape(Shape=s, LinearDeflection=0.05, AngularDeflection=0.25, Relative=False)
    m.write(os.path.join(OUT_DIR, "stl", n + ".stl"))
results["all_pass"] = all(c["pass"] for c in results["checks"].values())
json.dump(results, open(os.path.join(OUT_DIR, "windmill_results.json"), "w"), indent=1)
print("ALL_PASS", results["all_pass"])
