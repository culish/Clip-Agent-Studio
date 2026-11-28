"""Clip Agent 3D kit: helpers for short engineering / how-it-works animations. Runs INSIDE Blender (3.6+, 4.x, 5.x).

Scene code written by an AI only calls these helpers (plus math/random/mathutils/bpy when needed), so the scenes stay
short, readable and robust across Blender versions. Units are metres, Z is up, the floor is z = 0, times are seconds.
"""
from __future__ import annotations

import math
import random

import bpy  # noqa: I001 - bpy dulu: modul bpy (pip) baru menyediakan bmesh setelah bpy diimpor
import bmesh
from mathutils import Euler, Matrix, Vector

P: dict = {"W": 1080, "H": 1920, "fps": 30, "T": 6.0, "quality": "good", "style": "studio", "lang": "id"}
STATE: dict = {"camera_set": False, "objects": [], "labels": [], "n": 0, "cut_front": None}

STYLES = {
    # bg = latar/cyclorama, ink = teks, plate = papan label, world = warna langit (cahaya sekitar)
    "studio": {"bg": "#E9EDF2", "world": "#DDE6F0", "ink": "#16202C", "plate": "#FFFFFF", "accent": "#FF7A1A",
               "floor_rough": 0.85},
    "blueprint": {"bg": "#0E2238", "world": "#14324F", "ink": "#EAF6FF", "plate": "#123A5C", "accent": "#35D0FF",
                  "floor_rough": 0.6},
    "warm": {"bg": "#F3E8D8", "world": "#F6EBDC", "ink": "#2B2118", "plate": "#FFFDF8", "accent": "#E4572E",
             "floor_rough": 0.9},
}
COLORS = {
    "concrete": "#B9B5AC", "soil": "#8A5F3C", "sand": "#D9C08C", "gravel": "#8E8A84", "grass": "#5FA44B",
    "water": "#3BA7E0", "dirty_water": "#7A6A3A", "sludge": "#4E3B22", "steel": "#A8B0B9", "metal": "#A8B0B9",
    "iron": "#5C6066", "copper": "#C77B4A", "brass": "#C9A13B", "aluminum": "#C9CED4", "chrome": "#D8DDE2",
    "pvc": "#ECEEF0", "plastic": "#E6E8EA", "rubber": "#26282B", "wood": "#B07A4A", "brick": "#B5523B",
    "glass": "#BFE6F5", "fire": "#FF6A1A", "air": "#D6F1FF", "gas": "#9BE38B", "oil": "#3A2A12",
    "red": "#E5484D", "orange": "#FF7A1A", "yellow": "#FFC53D", "green": "#30A46C", "teal": "#12A594",
    "blue": "#3B82F6", "navy": "#1E3A5F", "purple": "#8E4EC6", "pink": "#E93D82", "white": "#F7F8FA",
    "gray": "#8B9199", "grey": "#8B9199", "dark": "#2A2F36", "black": "#15171A", "brown": "#7A4E2D",
}


# ====================================================================== utilitas
def f(t: float) -> int:
    """Detik -> nomor frame (frame pertama = 1)."""
    return 1 + int(round(max(0.0, float(t)) * P["fps"]))


def rgba(c, alpha: float = 1.0) -> tuple:
    """'#RRGGBB', nama warna (lihat COLORS), atau (r, g, b) 0..1 -> RGBA linear untuk Blender."""
    if isinstance(c, (tuple, list)):
        r, g, b = [float(v) for v in c[:3]]
        return (r, g, b, float(c[3]) if len(c) > 3 else alpha)
    s = str(c or "gray").strip()
    s = COLORS.get(s.lower(), s)
    if not s.startswith("#") or len(s) not in (4, 7):
        s = COLORS["gray"]
    if len(s) == 4:
        s = "#" + "".join(ch * 2 for ch in s[1:])

    def lin(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (lin(int(s[1:3], 16)), lin(int(s[3:5], 16)), lin(int(s[5:7], 16)), alpha)


def V(v) -> Vector:
    return Vector((float(v[0]), float(v[1]), float(v[2]))) if v is not None else Vector((0, 0, 0))


def _link(obj, name: str | None = None):
    if name:
        obj.name = name
    if obj.name not in bpy.context.scene.collection.objects and not obj.users_collection:
        bpy.context.scene.collection.objects.link(obj)
    STATE["objects"].append(obj)
    return obj


def _set_input(node, names, value):
    for n in names:
        if n in node.inputs:
            try:
                node.inputs[n].default_value = value
                return True
            except (TypeError, ValueError):
                continue
    return False


def _uid(prefix: str) -> str:
    STATE["n"] += 1
    return f"{prefix}_{STATE['n']}"


# ====================================================================== bahan (material)
def mat(color="gray", rough: float = 0.5, metal: float = 0.0, alpha: float = 1.0, emit: float = 0.0,
        name: str | None = None):
    """Bahan dasar. alpha < 1 = tembus pandang (air, kaca). emit > 0 = bercahaya (lampu, sorotan)."""
    m = bpy.data.materials.new(name or _uid("mat"))
    col = rgba(color)
    m.diffuse_color = (col[0], col[1], col[2], alpha)          # warna untuk mode render Cepat (Workbench)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    _set_input(bsdf, ["Base Color"], col)
    _set_input(bsdf, ["Roughness"], float(rough))
    _set_input(bsdf, ["Metallic"], float(metal))
    if emit:
        _set_input(bsdf, ["Emission Color", "Emission"], col)
        _set_input(bsdf, ["Emission Strength"], float(emit))
    if alpha < 1.0:
        _set_input(bsdf, ["Alpha"], float(alpha))
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            try:
                setattr(m, attr, val)
            except (AttributeError, TypeError):
                pass
        for attr in ("use_backface_culling", "show_transparent_back"):
            try:
                setattr(m, attr, False)
            except AttributeError:
                pass
    m["base_alpha"] = float(alpha)
    return m


def concrete():
    return mat("concrete", rough=0.9)


def metal(color="steel"):
    return mat(color, rough=0.32, metal=0.9)


def water(color="water", alpha: float = 0.55):
    return mat(color, rough=0.08, alpha=alpha)


def glass(alpha: float = 0.25):
    return mat("glass", rough=0.05, alpha=alpha)


def plastic(color="pvc"):
    return mat(color, rough=0.45)


def glow(color="orange", strength: float = 4.0):
    return mat(color, rough=0.4, emit=strength)


def _as_mat(m):
    if m is None:
        return mat("gray")
    if isinstance(m, bpy.types.Material):
        return m
    return mat(m)


def _assign(obj, m, smooth: bool = False):
    if obj.data is not None and hasattr(obj.data, "materials"):
        obj.data.materials.clear()
        obj.data.materials.append(_as_mat(m))
    if smooth and obj.type == "MESH":
        for p in obj.data.polygons:
            p.use_smooth = True
    return obj


# ====================================================================== bentuk dasar
def _mesh_obj(name: str, bm) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return bpy.data.objects.new(name, me)


def _bevel(obj, width: float, segments: int = 3):
    if width and width > 0:
        md = obj.modifiers.new("bevel", "BEVEL")
        md.width = float(width)
        md.segments = segments
        try:
            md.limit_method = "ANGLE"
        except (AttributeError, TypeError):
            pass
    return obj


def _orient(obj, axis):
    """Putar objek yang dibuat sepanjang Z agar sejajar sumbu 'X'/'Y'/'Z' atau vektor arah."""
    if axis in (None, "Z", "z"):
        return
    d = {"X": (1, 0, 0), "x": (1, 0, 0), "Y": (0, 1, 0), "y": (0, 1, 0)}.get(axis, axis)
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = Vector((0, 0, 1)).rotation_difference(V(d).normalized()).to_euler()


def box(size=(1, 1, 1), at=(0, 0, 0), mat=None, bevel: float = 0.02, name: str | None = None, base: bool = False):
    """Balok. size = (panjang X, lebar Y, tinggi Z). base=True: `at` adalah titik tengah ALAS (titik putar di bawah)."""
    sx, sy, sz = [float(v) for v in size]
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz + (sz / 2 if base else 0)))
    obj = _mesh_obj(name or _uid("box"), bm)
    obj.location = V(at)
    _bevel(obj, min(bevel, min(sx, sy, sz) * 0.3))
    return _link(_assign(obj, mat))


def cylinder(r: float = 0.5, h: float = 1.0, at=(0, 0, 0), axis="Z", mat=None, verts: int = 48, bevel: float = 0.01,
             name: str | None = None, base: bool = False, open_top: bool = False):
    """Silinder (tabung pejal). axis: 'X', 'Y', 'Z' atau vektor arah. base=True: titik putar di alas."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=int(verts), radius1=float(r), radius2=float(r),
                          depth=float(h))
    if base:
        for v in bm.verts:
            v.co.z += h / 2
    if open_top:
        top = [fc for fc in bm.faces if all(abs(v.co.z - (h if base else h / 2)) < 1e-5 for v in fc.verts)]
        bmesh.ops.delete(bm, geom=top, context="FACES_ONLY")
    obj = _mesh_obj(name or _uid("cyl"), bm)
    obj.location = V(at)
    _orient(obj, axis)
    _bevel(obj, min(bevel, r * 0.2))
    return _link(_assign(obj, mat, smooth=True))


def tube(r: float = 0.3, h: float = 1.0, wall: float = 0.04, at=(0, 0, 0), axis="Z", mat=None, name: str | None = None,
         base: bool = False):
    """Pipa lurus berongga (dinding setebal `wall`), terlihat dari ujungnya."""
    obj = cylinder(r, h, at, axis, mat, bevel=0, name=name or _uid("tube"), base=base)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    caps = [fc for fc in bm.faces if len(fc.verts) > 4]
    bmesh.ops.delete(bm, geom=caps, context="FACES_ONLY")
    bm.to_mesh(obj.data)
    bm.free()
    sol = obj.modifiers.new("wall", "SOLIDIFY")
    sol.thickness = float(wall)
    sol.offset = -1
    return obj


def tank(size=(2, 1.2, 1.2), wall: float = 0.08, at=(0, 0, 0), mat=None, open_top: bool = True, name: str | None = None):
    """Bak/tangki persegi berongga (alas di z = at.z). Pakai cut() agar bagian dalamnya terlihat."""
    sx, sy, sz = [float(v) for v in size]
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz + sz / 2))
    if open_top:
        top = [fc for fc in bm.faces if fc.normal.z > 0.9]
        bmesh.ops.delete(bm, geom=top, context="FACES_ONLY")
    obj = _mesh_obj(name or _uid("tank"), bm)
    obj.location = V(at)
    sol = obj.modifiers.new("wall", "SOLIDIFY")
    sol.thickness = float(wall)
    sol.offset = -1
    _bevel(obj, wall * 0.3, 2)
    return _link(_assign(obj, mat or concrete()))


def wall(a=(0, 0, 0), b=(2, 0, 0), h: float = 1.0, thick: float = 0.1, mat=None, name: str | None = None):
    """Dinding/sekat tegak dari titik a ke titik b di lantai (z = a.z), setinggi h."""
    a, b = V(a), V(b)
    d = b - a
    obj = box((d.length, thick, h), at=(0, 0, 0), mat=mat, bevel=0.01, name=name or _uid("wall"), base=True)
    obj.location = (a + b) / 2
    obj.rotation_euler = (0, 0, math.atan2(d.y, d.x))
    return obj


def sphere(r: float = 0.5, at=(0, 0, 0), mat=None, name: str | None = None, segments: int = 32):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=max(8, segments // 2), radius=float(r))
    obj = _mesh_obj(name or _uid("sphere"), bm)
    obj.location = V(at)
    return _link(_assign(obj, mat, smooth=True))


def cone(r1: float = 0.5, r2: float = 0.0, h: float = 1.0, at=(0, 0, 0), axis="Z", mat=None, name: str | None = None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=40, radius1=float(r1), radius2=float(r2), depth=float(h))
    obj = _mesh_obj(name or _uid("cone"), bm)
    obj.location = V(at)
    _orient(obj, axis)
    return _link(_assign(obj, mat, smooth=True))


def torus(R: float = 1.0, r: float = 0.2, at=(0, 0, 0), axis="Z", mat=None, name: str | None = None):
    bm = bmesh.new()
    seg_major, seg_minor = 48, 16
    rings = []
    for i in range(seg_major):
        a = 2 * math.pi * i / seg_major
        ring = []
        for j in range(seg_minor):
            b = 2 * math.pi * j / seg_minor
            x = (R + r * math.cos(b)) * math.cos(a)
            y = (R + r * math.cos(b)) * math.sin(a)
            ring.append(bm.verts.new((x, y, r * math.sin(b))))
        rings.append(ring)
    for i in range(seg_major):
        for j in range(seg_minor):
            a, b = rings[i], rings[(i + 1) % seg_major]
            bm.faces.new((a[j], b[j], b[(j + 1) % seg_minor], a[(j + 1) % seg_minor]))
    obj = _mesh_obj(name or _uid("torus"), bm)
    obj.location = V(at)
    _orient(obj, axis)
    return _link(_assign(obj, mat, smooth=True))


def plane(size=(4, 4), at=(0, 0, 0), mat=None, name: str | None = None):
    sx, sy = (size, size) if isinstance(size, (int, float)) else size
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy
    obj = _mesh_obj(name or _uid("plane"), bm)
    obj.location = V(at)
    return _link(_assign(obj, mat))


def gear(r: float = 0.6, teeth: int = 14, thick: float = 0.15, at=(0, 0, 0), axis="Z", mat=None, hole: float = 0.12,
         name: str | None = None):
    """Roda gigi (untuk mesin, transmisi, jam). Putar dengan spin()."""
    teeth = max(6, int(teeth))
    tooth = r * 0.16
    pts = []
    for i in range(teeth):
        a0 = 2 * math.pi * i / teeth
        step = 2 * math.pi / teeth
        for k, (frac, rad) in enumerate(((0.0, r - tooth * 0.4), (0.18, r + tooth), (0.5, r + tooth), (0.68, r - tooth * 0.4))):
            a = a0 + step * frac
            pts.append((rad * math.cos(a), rad * math.sin(a)))
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, -thick / 2)) for x, y in pts]
    face = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    for v in [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]:
        v.co.z += thick
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = _mesh_obj(name or _uid("gear"), bm)
    obj.location = V(at)
    _orient(obj, axis)
    _link(_assign(obj, mat or metal()))
    if hole > 0:
        cut_obj = cylinder(hole, thick * 3, at=(0, 0, 0), mat=None, bevel=0, name=_uid("gearhole"))
        cut_obj.parent = obj
        cut_obj.hide_render = True
        cut_obj.display_type = "WIRE"
        STATE["objects"].remove(cut_obj)
        md = obj.modifiers.new("hole", "BOOLEAN")
        md.operation = "DIFFERENCE"
        md.object = cut_obj
    return obj


def pipe(points, r: float = 0.08, mat=None, smooth: bool = True, name: str | None = None):
    """Pipa/kabel/selang mengikuti titik-titik [(x,y,z), ...]. Sudutnya dibulatkan bila smooth=True."""
    pts = [V(p) for p in points]
    cu = bpy.data.curves.new(name or _uid("pipe"), "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = float(r)
    cu.bevel_resolution = 4
    try:
        cu.use_fill_caps = True
    except AttributeError:
        pass
    if smooth and len(pts) > 2:
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(len(pts) - 1)
        for bp, p in zip(sp.bezier_points, pts):
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        cu.resolution_u = 16
    else:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for pt, p in zip(sp.points, pts):
            pt.co = (p.x, p.y, p.z, 1.0)
    obj = bpy.data.objects.new(cu.name, cu)
    obj["path_points"] = [list(p) for p in pts]
    return _link(_assign(obj, mat or plastic()))


def spring(r: float = 0.25, wire: float = 0.03, turns: float = 6, h: float = 1.0, at=(0, 0, 0), mat=None,
           name: str | None = None):
    n = int(turns * 24)
    pts = [(r * math.cos(2 * math.pi * turns * i / n), r * math.sin(2 * math.pi * turns * i / n), h * i / n)
           for i in range(n + 1)]
    obj = pipe(pts, wire, mat or metal(), smooth=False, name=name or _uid("spring"))
    obj.location = V(at)
    return obj


def group(objs, at=(0, 0, 0), name: str | None = None):
    """Satukan beberapa objek di bawah satu induk agar bisa digerakkan/diputar bersama."""
    e = bpy.data.objects.new(name or _uid("group"), None)
    e.location = V(at)
    _link(e)
    bpy.context.view_layer.update()
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = e
        o.matrix_parent_inverse = e.matrix_world.inverted()
        o.matrix_world = mw
    return e


def cut(objs, side: str = "front", at=(0, 0, 0), depth: float = 50.0):
    """Potongan penampang (cutaway): buang separuh objek agar bagian dalamnya terlihat.
    side: 'front' (sisi -Y, menghadap kamera bawaan), 'back', 'left', 'right', 'top'."""
    objs = objs if isinstance(objs, (list, tuple)) else [objs]
    c = V(at)
    off = {"front": (0, -depth / 2, 0), "back": (0, depth / 2, 0), "left": (-depth / 2, 0, 0),
           "right": (depth / 2, 0, 0), "top": (0, 0, depth / 2)}.get(side, (0, -depth / 2, 0))
    cutter = bpy.data.objects.new(_uid("cutter"), bpy.data.meshes.new(_uid("cutter")))
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=depth)
    bm.to_mesh(cutter.data)
    bm.free()
    cutter.location = c + V(off)
    bpy.context.scene.collection.objects.link(cutter)
    if side == "front":
        STATE["cut_front"] = c.y
    cutter.hide_render = True
    cutter.display_type = "WIRE"
    for o in objs:
        if o.type not in ("MESH", "CURVE"):
            continue
        md = o.modifiers.new("cutaway", "BOOLEAN")
        md.operation = "DIFFERENCE"
        md.object = cutter
    return cutter


# ====================================================================== teks, label, panah
def _cam():
    return bpy.context.scene.camera


def text(txt: str, at=(0, 0, 0), size: float = 0.35, color=None, extrude: float = 0.015, face_camera: bool = True,
         align: str = "CENTER", bold: bool = True, name: str | None = None):
    """Teks 3D. face_camera=True: selalu menghadap kamera (mudah dibaca)."""
    cu = bpy.data.curves.new(name or _uid("text"), "FONT")
    cu.body = str(txt)
    cu.size = float(size)
    cu.extrude = float(extrude)
    cu.align_x = align if align in ("LEFT", "CENTER", "RIGHT") else "CENTER"
    cu.align_y = "CENTER"
    if bold:
        cu.offset = 0.0
        try:
            cu.bevel_depth = size * 0.012
        except AttributeError:
            pass
    obj = bpy.data.objects.new(cu.name, cu)
    obj.location = V(at)
    _link(obj)
    _assign(obj, mat(color or STYLES[P["style"]]["ink"], rough=0.6))
    if face_camera and _cam() is not None:
        con = obj.constraints.new("COPY_ROTATION")
        con.target = _cam()
    return obj


def label(txt: str, point=(0, 0, 0), offset=(0, 0, 0.9), size: float = 0.22, color=None, plate: bool = True,
          dot: bool = True, name: str | None = None):
    """Label bergaya infografis: papan teks + garis penunjuk ke `point`. Mengembalikan objek induknya
    (pakai appear()/disappear() pada objek ini)."""
    p, o = V(point), V(offset)
    st = STYLES[P["style"]]
    root = bpy.data.objects.new(name or _uid("label"), None)
    root.location = p
    _link(root)
    parts = []
    t = text(txt, at=(0, 0, 0), size=size, color=color or st["ink"], extrude=0.004, face_camera=False)
    parts.append(t)
    bpy.context.view_layer.update()
    w, h = max(t.dimensions.x, size), max(t.dimensions.y, size * 0.8)
    holder = bpy.data.objects.new(_uid("labelface"), None)
    _link(holder)
    holder.location = o
    if plate:                                    # papan di bidang XY lokal, di belakang teks
        pl = box((w + size * 0.9, h + size * 0.7, size * 0.1), at=(0, 0, -size * 0.07), mat=mat(st["plate"], rough=0.7),
                 bevel=size * 0.04, name=_uid("plate"))
        pl.parent = holder
        parts.append(pl)
    t.parent = holder
    t.location = (0, 0, 0)
    t.rotation_euler = (0, 0, 0)
    if _cam() is not None:
        con = holder.constraints.new("COPY_ROTATION")
        con.target = _cam()
    holder.parent = root
    if o.length > 0.05:
        ln = pipe([(0, 0, 0), tuple(o * (1 - (h / 2 + size * 0.35) / max(o.length, 1e-3)))], r=size * 0.035,
                  mat=mat(st["ink"], rough=0.6), smooth=False, name=_uid("leader"))
        ln.parent = root
    if dot:
        d = sphere(size * 0.12, at=(0, 0, 0), mat=mat(st["accent"], rough=0.4, emit=1.5), name=_uid("dot"))
        d.parent = root
    STATE["labels"].append(root)
    return root


def arrow(start=(0, 0, 0), end=(1, 0, 0), color=None, r: float = 0.05, name: str | None = None):
    """Panah tebal dari start ke end (arah aliran, gaya, gerak)."""
    a, b = V(start), V(end)
    d = b - a
    L = max(d.length, 1e-3)
    head = min(L * 0.35, r * 5)
    m = mat(color or STYLES[P["style"]]["accent"], rough=0.4, emit=0.6)
    root = bpy.data.objects.new(name or _uid("arrow"), None)
    root.location = a
    _link(root)
    shaft = cylinder(r, L - head, at=(0, 0, (L - head) / 2), mat=m, bevel=0, verts=24)
    tip = cone(r * 2.4, 0, head, at=(0, 0, L - head / 2), mat=m)
    shaft.parent = tip.parent = root
    root.rotation_mode = "QUATERNION"
    root.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    return root


# ====================================================================== animasi (semua waktu dalam detik)
def _key(obj, path: str, t: float, value=None, interp: str = "BEZIER"):
    if value is not None:
        setattr(obj, path, value)
    obj.keyframe_insert(data_path=path, frame=f(t))
    ad = obj.animation_data
    if ad and ad.action:
        for fc in _fcurves(ad.action):
            if fc.data_path == path:
                for kp in fc.keyframe_points:
                    if abs(kp.co.x - f(t)) < 0.5:
                        kp.interpolation = interp


def _fcurves(action):
    """F-curve sebuah action (Blender 5 memakai layered action: layers -> strips -> channelbags)."""
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        try:
            return list(fcs)
        except TypeError:
            pass
    out = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def _rest_scale(obj):
    if "rest_scale" not in obj:
        obj["rest_scale"] = list(obj.scale)
    return Vector(obj["rest_scale"])


def appear(obj, t: float = 0.0, dur: float = 0.5, how: str = "pop"):
    """Munculkan objek pada detik t. how: 'pop' (membesar memantul), 'grow' (tumbuh ke atas dari alasnya),
    'rise' (naik dari bawah), 'drop' (jatuh dari atas), 'left'/'right' (masuk dari samping)."""
    s = _rest_scale(obj)
    dur = max(0.1, float(dur))
    if how == "grow":
        _key(obj, "scale", t, Vector((s.x, s.y, 0.001)))
        _key(obj, "scale", t + dur, s.copy())
        return obj
    if how in ("rise", "drop", "left", "right"):
        loc = obj.location.copy()
        off = {"rise": (0, 0, -2.5), "drop": (0, 0, 3.0), "left": (-4, 0, 0), "right": (4, 0, 0)}[how]
        _key(obj, "scale", max(0.0, t - 1 / P["fps"]), Vector((0, 0, 0)), "CONSTANT")
        _key(obj, "scale", t, s.copy(), "CONSTANT")
        _key(obj, "location", t, loc + V(off))
        _key(obj, "location", t + dur, loc)
        return obj
    _key(obj, "scale", t, Vector((0, 0, 0)))
    _key(obj, "scale", t + dur * 0.7, s * 1.08)
    _key(obj, "scale", t + dur, s.copy())
    return obj


def disappear(obj, t: float, dur: float = 0.4):
    s = _rest_scale(obj)
    _key(obj, "scale", t, obj.scale.copy() if obj.scale.length > 0 else s.copy())
    _key(obj, "scale", t + max(0.1, dur), Vector((0, 0, 0)))
    return obj


def show_between(obj, t0: float, t1: float, dur: float = 0.35, how: str = "pop"):
    appear(obj, t0, dur, how)
    disappear(obj, max(t0 + dur, t1 - dur), dur)
    return obj


def move(obj, t0: float, t1: float, to=(0, 0, 0), frm=None):
    """Geser objek ke posisi `to` antara detik t0 dan t1 (halus di awal dan akhir)."""
    if frm is not None:
        obj.location = V(frm)
    _key(obj, "location", t0, obj.location.copy())
    _key(obj, "location", t1, V(to))
    return obj


def rotate(obj, t0: float, t1: float, to_deg=(0, 0, 90)):
    obj.rotation_mode = "XYZ"
    _key(obj, "rotation_euler", t0, obj.rotation_euler.copy())
    _key(obj, "rotation_euler", t1, Euler([math.radians(v) for v in to_deg]))
    return obj


def spin(obj, axis: str = "Z", rps: float = 0.5, t0: float = 0.0, t1: float | None = None):
    """Putar terus-menerus (roda, kipas, gir, turbin). rps = putaran per detik (negatif = berlawanan)."""
    t1 = P["T"] if t1 is None else t1
    obj.rotation_mode = "XYZ"
    i = {"X": 0, "Y": 1, "Z": 2}.get(str(axis).upper(), 2)
    start = obj.rotation_euler.copy()
    end = start.copy()
    end[i] = start[i] + 2 * math.pi * rps * (t1 - t0)
    _key(obj, "rotation_euler", t0, start, "LINEAR")
    _key(obj, "rotation_euler", t1, end, "LINEAR")
    return obj


def oscillate(obj, axis: str = "Z", amp: float = 0.2, hz: float = 1.0, t0: float = 0.0, t1: float | None = None):
    """Gerak bolak-balik (piston, pompa, katup, getaran)."""
    t1 = P["T"] if t1 is None else t1
    i = {"X": 0, "Y": 1, "Z": 2}.get(str(axis).upper(), 2)
    base = obj.location.copy()
    steps = max(2, int((t1 - t0) * hz * 8))
    for k in range(steps + 1):
        t = t0 + (t1 - t0) * k / steps
        p = base.copy()
        p[i] = base[i] + amp * math.sin(2 * math.pi * hz * (t - t0))
        _key(obj, "location", t, p, "LINEAR")
    return obj


def level(obj, t0: float, t1: float, frm: float = 0.0, to: float = 1.0):
    """Ubah tinggi (skala Z) objek yang titik putarnya di alas (box(..., base=True), cylinder(..., base=True)):
    air yang naik/turun, tumpukan endapan, batang yang memanjang. frm/to = 0..1 dari tinggi aslinya."""
    s = _rest_scale(obj)
    _key(obj, "scale", t0, Vector((s.x, s.y, max(0.001, s.z * frm))))
    _key(obj, "scale", t1, Vector((s.x, s.y, max(0.001, s.z * to))))
    return obj


def pulse(obj, t0: float, t1: float, color=None, times: int = 2):
    """Sorot sebuah bagian dengan cahaya berdenyut (untuk 'perhatikan bagian ini')."""
    m = obj.active_material
    if m is None or not m.use_nodes:
        return obj
    m = m.copy()
    obj.active_material = m
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return obj
    col = rgba(color or STYLES[P["style"]]["accent"])
    _set_input(bsdf, ["Emission Color", "Emission"], col)
    sock = bsdf.inputs.get("Emission Strength")
    if sock is None:
        return obj
    n = max(1, int(times))
    for k in range(2 * n + 1):
        t = t0 + (t1 - t0) * k / (2 * n)
        sock.default_value = 0.0 if k % 2 == 0 else 2.5
        sock.keyframe_insert("default_value", frame=f(t))
    return obj


def explode(objs, t0: float, t1: float, offsets):
    """Tampilan urai (exploded view): tiap objek bergeser sejauh offset-nya lalu tetap di sana."""
    for o, off in zip(objs, offsets):
        move(o, t0, t1, to=o.location + V(off))
    return objs


def _path_points(path):
    if hasattr(path, "get") and path.get("path_points"):
        return [V(p) for p in path["path_points"]], path.matrix_world.copy()
    return [V(p) for p in path], Matrix.Identity(4)


def flow(path, t0: float = 0.0, t1: float | None = None, n: int = 18, r: float = 0.05, color="water", speed: float = 0.8,
         shape: str = "ball", see_through: bool = True):
    """Partikel yang mengalir sepanjang jalur (air, udara, gas, listrik, kotoran). `path` = daftar titik atau objek
    hasil pipe(). speed = meter per detik. shape: 'ball' atau 'cube'. see_through=True: pipa dibuat bening agar
    alirannya terlihat."""
    if see_through and isinstance(path, bpy.types.Object) and path.active_material is not None:
        base = path.active_material
        clear = mat(base.diffuse_color[:3], rough=0.1, alpha=0.35)
        path.data.materials.clear()
        path.data.materials.append(clear)
    pts, mw = _path_points(path)
    pts = [mw @ p for p in pts]
    if len(pts) < 2:
        return []
    t1 = P["T"] if t1 is None else t1
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]
    total = max(sum(seg), 1e-3)

    def at(s):
        s = s % total
        for i, L in enumerate(seg):
            if s <= L or i == len(seg) - 1:
                return pts[i].lerp(pts[i + 1], min(1.0, s / max(L, 1e-6)))
            s -= L
        return pts[-1]
    m = mat(color, rough=0.3, emit=0.4)
    out = []
    step = 1.0 / P["fps"] * 2
    for k in range(int(n)):
        p = sphere(r, at=pts[0], mat=m, segments=12) if shape == "ball" else box((r * 2,) * 3, at=pts[0], mat=m, bevel=0)
        phase = total * k / n + random.uniform(0, total / n * 0.4)
        t = t0
        while t <= t1 + 1e-6:
            _key(p, "location", t, at(phase + speed * (t - t0)), "LINEAR")
            t += step
        _key(p, "scale", max(0.0, t0 - step), Vector((0, 0, 0)), "CONSTANT")
        _key(p, "scale", t0, Vector((1, 1, 1)), "CONSTANT")
        if t1 < P["T"] - 0.05:
            _key(p, "scale", t1, Vector((0, 0, 0)), "CONSTANT")
        out.append(p)
    return out


def settle(t0: float, t1: float, at=(0, 0, 1.0), area=(1.0, 0.6), floor_z: float = 0.0, n: int = 30,
           r: float = 0.04, color="sludge"):
    """Partikel yang turun perlahan dari ketinggian at.z dan mengendap di floor_z (lumpur, pasir, endapan),
    tersebar di persegi `area` (lebar X, Y) di sekitar at."""
    c = V(at)
    m = mat(color, rough=0.9)
    out = []
    y_lo = c.y - area[1] / 2
    if STATE.get("cut_front") is not None:                         # jangan melayang di depan bidang potong
        y_lo = max(y_lo, STATE["cut_front"] + r * 1.5)
    for k in range(int(n)):
        x = c.x + random.uniform(-area[0] / 2, area[0] / 2)
        y = random.uniform(y_lo, max(y_lo + 1e-3, c.y + area[1] / 2))
        p = sphere(r * random.uniform(0.7, 1.3), at=(x, y, c.z), mat=m, segments=10)
        tt = t0 + (t1 - t0) * random.uniform(0.0, 0.5)
        _key(p, "scale", max(0.0, tt - 0.05), Vector((0, 0, 0)), "CONSTANT")
        _key(p, "scale", tt, Vector((1, 1, 1)), "CONSTANT")
        _key(p, "location", tt, Vector((x, y, c.z)))
        _key(p, "location", min(t1, tt + (t1 - t0) * 0.6), Vector((x, y, floor_z + r)))
        out.append(p)
    return out


# ====================================================================== kamera
def _cam_target():
    tgt = bpy.data.objects.get("CamTarget")
    if tgt is None:
        tgt = bpy.data.objects.new("CamTarget", None)
        bpy.context.scene.collection.objects.link(tgt)
    return tgt


def camera(at=(0, -9, 4), look=(0, 0, 1), lens: float = 40.0):
    """Letakkan kamera di `at` dan arahkan ke `look`. lens kecil = sudut lebar."""
    cam = _cam()
    cam.location = V(at)
    cam.data.lens = float(lens)
    _cam_target().location = V(look)
    STATE["camera_set"] = True
    return cam


def cam_move(t0: float, t1: float, at=None, look=None, lens: float | None = None):
    """Gerakan kamera halus antara t0 dan t1 (dolly, naik, mendekat)."""
    cam, tgt = _cam(), _cam_target()
    if at is not None:
        _key(cam, "location", t0, cam.location.copy())
        _key(cam, "location", t1, V(at))
    if look is not None:
        _key(tgt, "location", t0, tgt.location.copy())
        _key(tgt, "location", t1, V(look))
    if lens is not None:
        cam.data.keyframe_insert("lens", frame=f(t0))
        cam.data.lens = float(lens)
        cam.data.keyframe_insert("lens", frame=f(t1))
    STATE["camera_set"] = True
    return cam


def orbit(center=(0, 0, 1), radius: float = 9.0, height: float = 4.0, deg0: float = -100, deg1: float = -60,
          t0: float = 0.0, t1: float | None = None):
    """Kamera berputar pelan mengelilingi `center` (sudut 0 = sisi +X, -90 = depan/sisi -Y)."""
    t1 = P["T"] if t1 is None else t1
    c = V(center)
    cam = _cam()
    _cam_target().location = c
    steps = max(2, int((t1 - t0) * 4))
    for k in range(steps + 1):
        a = math.radians(deg0 + (deg1 - deg0) * k / steps)
        t = t0 + (t1 - t0) * k / steps
        _key(cam, "location", t, Vector((c.x + radius * math.cos(a), c.y + radius * math.sin(a), c.z + height)),
             "LINEAR" if 0 < k < steps else "BEZIER")
    STATE["camera_set"] = True
    return cam


def _corners(objs):
    bpy.context.view_layer.update()
    pts = []
    for o in objs:
        if o.type not in ("MESH", "CURVE", "FONT") or o.hide_render or o.name.startswith(("cutter", "Backdrop")):
            continue
        if o.matrix_world.to_scale().length < 1e-4:
            continue
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    return pts or [Vector((x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (0, 2)]


def fit(objs=None, az: float = -60.0, el: float = 22.0, margin: float = 1.1, t: float | None = None, lens: float = 40.0):
    """Arahkan kamera agar semua `objs` (bawaan: semua objek) pas di bingkai, dilihat dari sudut az/el (derajat;
    az -90 = dari depan/sisi -Y, 0 = dari kanan/sisi +X; el = ketinggian sudut pandang).
    Dengan t: hanya pasang keyframe kamera pada detik t (gabungkan beberapa fit() untuk pindah sudut/mendekat)."""
    objs = objs if objs is not None else list(STATE["objects"])
    objs = objs if isinstance(objs, (list, tuple)) else [objs]
    pts = _corners(objs)
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c = (lo + hi) / 2
    cam = _cam()
    cam.data.lens = float(lens)
    fov = cam.data.angle                                           # sudut pada sisi terpanjang sensor
    W, H = P["W"], P["H"]
    if W >= H:
        fov_h, fov_v = fov, 2 * math.atan(math.tan(fov / 2) * H / W)
    else:
        fov_v, fov_h = fov, 2 * math.atan(math.tan(fov / 2) * W / H)
    a, e = math.radians(az), math.radians(el)
    back = Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))   # dari pusat ke kamera
    fwd = -back
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd).normalized()
    th, tv = math.tan(fov_h / 2) / margin, math.tan(fov_v / 2) / margin
    d = 0.5
    for p in pts:
        q = p - c
        x, y, z = abs(q.dot(right)), abs(q.dot(up)), q.dot(back)
        d = max(d, z + x / th, z + y / tv)
    pos = c + back * d
    if t is None:
        cam.location = pos
        _cam_target().location = c
    else:
        _key(cam, "location", t, pos)
        _key(_cam_target(), "location", t, c)
    STATE["camera_set"] = True
    return cam


# ====================================================================== penyiapan (dipanggil runner)
def _engine(scene, quality: str):
    order = {"fast": ["BLENDER_WORKBENCH"], "good": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
             "best": ["CYCLES"]}.get(quality, ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"])
    for eng in order + ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"]:
        try:
            scene.render.engine = eng
            return eng
        except TypeError:
            continue
    return scene.render.engine


def _gpu_cycles(scene):
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = dev
                prefs.get_devices()
                if any(d.type == dev for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = True
                    scene.cycles.device = "GPU"
                    return dev
            except (TypeError, ValueError, AttributeError):
                continue
    except (KeyError, AttributeError):
        pass
    scene.cycles.device = "CPU"
    return "CPU"


def _backdrop(st):
    """Latar studio melengkung (cyclorama) supaya tidak ada garis cakrawala."""
    bm = bmesh.new()
    prof = [(-40.0, 0.0)]
    R = 8.0
    for k in range(13):
        a = math.pi / 2 * k / 12
        prof.append((14.0 + R * math.sin(a), R - R * math.cos(a)))
    prof.append((14.0 + R, 45.0))
    rows = []
    for x in (-60.0, 60.0):
        rows.append([bm.verts.new((x, y, z)) for y, z in prof])
    for i in range(len(prof) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    me = bpy.data.meshes.new("Backdrop")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("Backdrop", me)
    bpy.context.scene.collection.objects.link(obj)
    for p in me.polygons:
        p.use_smooth = True
    m = mat(st["bg"], rough=st["floor_rough"], name="BackdropMat")
    me.materials.append(m)
    return obj


def setup(params: dict):
    """Kosongkan adegan, atur resolusi/fps/durasi, mesin render, cahaya studio, kamera, dan latar."""
    P.update(params)
    if P.get("style") not in STYLES:
        P["style"] = "studio"
    random.seed(int(P.get("seed", 7)))
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = int(P["W"]), int(P["H"])
    sc.render.resolution_percentage = int(P.get("scale", 100))
    sc.render.fps = int(P["fps"])
    sc.frame_start, sc.frame_end = 1, max(1, int(round(float(P["T"]) * P["fps"])))
    eng = _engine(sc, P.get("quality", "good"))
    P["engine"] = eng
    try:
        sc.view_settings.view_transform = "AgX"
    except TypeError:
        try:
            sc.view_settings.view_transform = "Filmic"
        except TypeError:
            pass
    try:
        sc.view_settings.look = "AgX - Medium High Contrast" if sc.view_settings.view_transform == "AgX" else "None"
    except TypeError:
        pass
    st = STYLES[P["style"]]
    world = sc.world or bpy.data.worlds.new("World")
    sc.world = world
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg is not None:
        bg.inputs[0].default_value = rgba(st["world"])
        bg.inputs[1].default_value = 0.9 if P["style"] != "blueprint" else 0.6
    if eng == "CYCLES":
        sc.cycles.samples = int(P.get("samples", 48))
        try:
            sc.cycles.use_denoising = True
            sc.cycles.use_adaptive_sampling = True
        except AttributeError:
            pass
        P["device"] = _gpu_cycles(sc)
    elif eng.startswith("BLENDER_EEVEE"):
        ee = sc.eevee
        for attr, val in (("taa_render_samples", int(P.get("samples", 24))), ("use_gtao", True),
                          ("use_soft_shadows", True), ("use_shadows", True), ("use_raytracing", False)):
            try:
                setattr(ee, attr, val)
            except (AttributeError, TypeError):
                pass
    else:                                                           # Workbench: cepat, tetap berwarna
        sh = sc.display.shading
        for attr, val in (("light", "STUDIO"), ("color_type", "MATERIAL"), ("show_shadows", True),
                          ("show_cavity", True), ("show_specular_highlight", True), ("shadow_intensity", 0.35)):
            try:
                setattr(sh, attr, val)
            except (AttributeError, TypeError):
                pass
        try:
            sc.display.render_aa = "16"
        except (AttributeError, TypeError):
            pass
    # cahaya: matahari lembut + cahaya isi dari samping
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.2 if P["style"] != "blueprint" else 2.0
    try:
        sun.data.angle = math.radians(12)
    except AttributeError:
        pass
    sun.rotation_euler = (math.radians(48), math.radians(8), math.radians(-35))
    sc.collection.objects.link(sun)
    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    fill.data.energy = 600
    fill.data.size = 8
    fill.location = (-7, -6, 6)
    fill.rotation_euler = (math.radians(55), 0, math.radians(-50))
    sc.collection.objects.link(fill)
    if P.get("backdrop", True):
        _backdrop(st)
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = 40
    cam.data.clip_end = 500
    con = cam.constraints.new("TRACK_TO")
    con.target = _cam_target()
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    cam.location = (0, -10, 4)
    _cam_target().location = (0, 0, 1)
    STATE.update(camera_set=False, objects=[], labels=[], n=0, cut_front=None)
    return sc


def finish():
    """Dipanggil runner setelah build(): turunkan lantai latar bila ada bagian di bawah z = 0 (bawah tanah),
    supaya tidak tertutup lantai dan tidak ada dua permukaan berimpit (bayangan hitam)."""
    bd = bpy.data.objects.get("Backdrop")
    if bd is None:
        return
    pts = _corners(list(STATE["objects"]))
    low = min((p.z for p in pts), default=0.0)
    bd.location.z = min(0.0, low) - 0.004


def words(t0: float = 0.0, t1: float | None = None) -> list:
    """Kata narasi adegan ini [(detik, kata), ...] untuk menyamakan aksi dengan ucapan."""
    t1 = P["T"] if t1 is None else t1
    return [(w[0], w[1]) for w in P.get("words", []) if t0 <= w[0] <= t1]


def when(word: str, default: float = 0.0) -> float:
    """Detik saat kata (atau awal kata) diucapkan di adegan ini; `default` bila tidak ada."""
    key = str(word).lower().strip(" .,!?")
    for t, w in P.get("words", []):
        if str(w).lower().strip(" .,!?\"'").startswith(key):
            return float(t)
    return float(default)
