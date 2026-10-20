"""Makes the crew's clips no Quaternius pack has, on the Universal
Animation Library's own mannequin, and writes them to OUT/poses.glb for
scripts/deck-crew-assets.mjs to re-cut beside the packs' clips:

  - Idle_HandsBehind_Loop: standing at ease, the hands clasped at the small
    of the back, elbows out;
  - Idle_PADD_Loop: a PADD read - the left hand holding it at the chest,
    the right tapping at it now and then, the head bowed to it;
  - Sitting_PADD_Loop: the same read in a seat, over the pack's
    Sitting_Idle_Loop: the elbows in by the ribs, the PADD at reading
    distance before the chest, the head down to it;
  - Idle_Shift_Loop: the weight from one foot to the other and back, 7.5 s,
    on the idle's first pose held still: the page makes it additive
    (relative to its first frame, where the weight is even) and lays it
    over whatever standing idle a person has.

The idles are the pack's Idle_Loop (Sitting_Idle_Loop for the seated
read) with the arms (and for the PADD the head) taken over by IK to
targets that ride the spine, baked to keys: so the body still sways and
breathes as the idle does, and the arms move with it instead of hanging in
a frozen pose. Only rotations matter (and the pelvis's translation): the
assets script keeps nothing else, as for every clip.

Blender 4.3, headless (scripts/deck-crew-build.sh runs it, niced):
  blender -b --factory-startup -P scripts/deck-crew-poses.py -- UAL1_Standard.glb OUT_DIR [--preview]
--preview also renders each pose from the front and the side (OUT/pose-*.png),
on the mannequin, to look at.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], argv[1]
PREVIEW = "--preview" in argv
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
# the importer names an action "<animation>_<armature>"
idle = bpy.data.actions["Idle_Loop_Armature"]
# the pack's scene has a camera, a light and two props besides
for o in list(bpy.data.objects):
    if o.type in ("CAMERA", "LIGHT") or o.name in ("Cube", "Icosphere"):
        bpy.data.objects.remove(o)
f0, f1 = (int(round(x)) for x in idle.frame_range)
sc = bpy.context.scene
sc.frame_start, sc.frame_end = f0, f1

# Where things are, in the armature's rest pose, in world space: the
# mannequin faces Blender's -Y (glTF's +Z), its left is +X, up is +Z.
pb = arm.pose.bones
rest = {b.name: arm.matrix_world @ b.head_local for b in arm.data.bones}
hip = rest["pelvis"]


def target(name, parent_bone, at):
    """An empty at world point `at` (rest pose), riding `parent_bone`."""
    e = bpy.data.objects.new(name, None)
    sc.collection.objects.link(e)
    e.location = at
    e.parent, e.parent_type, e.parent_bone = arm, "BONE", parent_bone
    # keep its world place: parented to a bone, the empty is put relative
    # to the bone's tail; undo that with the parent's inverse at rest
    bm = arm.matrix_world @ arm.data.bones[parent_bone].matrix_local
    tail = Vector((0, arm.data.bones[parent_bone].length, 0))
    from mathutils import Matrix
    e.matrix_parent_inverse = (bm @ Matrix.Translation(tail)).inverted()
    return e


def ik(bone, tgt, pole, pole_angle=0.0):
    """IK on the forearm (its tail is the wrist): the forearm and upper arm
    bend to bring the wrist to `tgt`, the elbow toward `pole`."""
    c = pb[bone].constraints.new("IK")
    c.target, c.pole_target, c.chain_count, c.pole_angle = tgt, pole, 2, pole_angle
    return c


ARM_BONES = [p + s for s in ("_l", "_r") for p in ("clavicle", "upperarm", "lowerarm", "hand")]


def make(name, setup, extra=(), base=None, loops=1, every=False):
    """`base` (Idle_Loop) copied as `name`, `setup` adding its constraints,
    baked. `loops`: the base played that many times over (its curves
    cycled), for a clip longer than the base's own; `every`: every bone
    baked, not only the arms and `extra` (the cycled base's other bones
    would otherwise keep one loop's keys, in a clip `loops` times as long)."""
    act = (base or idle).copy()
    act.name = name
    a0, a1 = (int(round(x)) for x in act.frame_range)
    end = a0 + (a1 - a0) * loops
    if loops > 1:
        for fc in act.fcurves:
            fc.modifiers.new("CYCLES")
    arm.animation_data.action = act
    sc.frame_start, sc.frame_end = a0, end
    made = setup(a0, end)
    bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode="POSE")
    for b in pb:
        b.bone.select = every or b.name in ARM_BONES or b.name in extra or b.name.startswith(("thumb", "index", "middle", "ring", "pinky"))
    bpy.ops.nla.bake(frame_start=a0, frame_end=end, only_selected=True, visual_keying=True,
                     clear_constraints=True, use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")
    for fc in act.fcurves:
        for m in list(fc.modifiers):
            fc.modifiers.remove(m)
    for o in made:
        bpy.data.objects.remove(o)
    act.use_fake_user = True
    return act


def hands_behind(a0, a1):
    # the hands at the small of the back, the right over the left's wrist;
    # the elbows out and a little back
    tl = target("tl", "spine_01", hip + Vector((0.03, 0.15, 0.11)))
    tr = target("tr", "spine_01", hip + Vector((-0.03, 0.16, 0.13)))
    pl = target("pl", "spine_02", hip + Vector((0.55, 0.35, 0.25)))
    pr = target("pr", "spine_02", hip + Vector((-0.55, 0.35, 0.25)))
    ik("lowerarm_l", tl, pl, math.radians(-90))
    ik("lowerarm_r", tr, pr, math.radians(-90))
    return [tl, tr, pl, pr]


def read(pad_at, pole_at, bow, taps):
    """A PADD read: the left hand holds it at `pad_at` (from the chest, at
    rest), the right taps it `taps` times a loop and lowers again between,
    the elbows toward `pole_at` (from the hip, either side), the head bowed
    to it by `bow` (the damped track's influence)."""
    def setup(a0, a1):
        pad = rest["spine_03"] + pad_at
        tl = target("tl", "spine_03", pad + Vector((0.07, 0.0, 0.0)))
        tr = target("tr", "spine_03", pad + Vector((-0.06, -0.02, 0.0)))
        # the tap: the right hand comes up to the screen, and otherwise
        # rests lower, at the PADD's bottom edge
        at, low = tr.location.copy(), Vector((0.0, 0.04, -0.09))
        for n in range(taps):
            for k, d in ((0.0, 1), (0.3, 1), (0.42, 0), (0.55, 0), (0.68, 1), (1.0, 1)):
                tr.location = at + low * d
                tr.keyframe_insert("location", frame=a0 + (a1 - a0) * (n + k) / taps)
        pl = target("pl", "spine_02", hip + Vector((pole_at.x, pole_at.y, pole_at.z)))
        pr = target("pr", "spine_02", hip + Vector((-pole_at.x, pole_at.y, pole_at.z)))
        ik("lowerarm_l", tl, pl, math.radians(-90))
        ik("lowerarm_r", tr, pr, math.radians(-90))
        look = target("look", "spine_03", pad)
        c = pb["Head"].constraints.new("DAMPED_TRACK")
        c.target, c.track_axis, c.influence = look, "TRACK_Z", bow
        return [tl, tr, pl, pr, look]
    return setup


# standing: the PADD at the chest's height, a forearm out in front
padd = read(Vector((0.06, -0.3, -0.03)), Vector((0.45, 0.1, 0.0)), 0.55, 1)
# seated: nearer, a little lower, the elbows down by the ribs and the head
# further down; over three loops of the sitting idle (5 s), two taps
SIT_PAD, SIT_POLE, SIT_BOW = Vector((0.02, -0.28, 0.1)), Vector((0.3, 0.2, -0.25)), 0.8
padd_sit = read(SIT_PAD, SIT_POLE, SIT_BOW, 2)


# The weight shift: on the idle's first pose, held, the pelvis 2.2 cm
# toward one foot, its side over that foot 2 deg up, the spine leaning
# back the other way over it and the neck keeping the head level; the
# feet held where they stand by IK on the legs. A sine over the loop (the
# weight even at its start and middle, on the left at a quarter, the right
# at three quarters), keyed every 1/24 of it.
SHIFT_D, SHIFT_TH, SHIFT_LOOPS = 0.022, math.radians(2.0), 3
SWAY_BONES = ("pelvis", "spine_01", "neck_01", "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r")


def shift(a0, a1):
    from mathutils import Matrix
    act = arm.animation_data.action
    # the idle's first pose, held: every curve a constant
    for fc in act.fcurves:
        v = fc.evaluate(a0)
        for m in list(fc.modifiers):
            fc.modifiers.remove(m)
        while len(fc.keyframe_points) > 1:
            fc.keyframe_points.remove(fc.keyframe_points[-1])
        fc.keyframe_points[0].co = (a0, v)
    sc.frame_set(a0)
    bpy.context.view_layer.update()
    m0 = {n: pb[n].matrix.copy() for n in ("pelvis", "spine_01", "neck_01")}
    feet = []
    for s in ("l", "r"):
        # the feet stay put: an empty at each ankle (world, unparented), and
        # the knees bend toward one ahead of them
        e = bpy.data.objects.new("f" + s, None); sc.collection.objects.link(e)
        e.location = arm.matrix_world @ pb["foot_" + s].head
        k = bpy.data.objects.new("k" + s, None); sc.collection.objects.link(k)
        k.location = arm.matrix_world @ pb["calf_" + s].head + Vector((0, -0.5, 0))
        c = pb["calf_" + s].constraints.new("IK")
        c.target, c.pole_target, c.chain_count, c.pole_angle = e, k, 2, math.radians(-90)
        feet += [e, k]
    piv = lambda n, rot: Matrix.Translation(m0[n].to_translation()) @ rot @ Matrix.Translation(-m0[n].to_translation())
    # Each bone's own turn, taken to its local space against the held pose
    # (convert_space reads the parents as they are, at rest in that pose):
    # a child keyed so carries its parents' turns on top, so the spine
    # leans P @ S and the neck P @ S @ K. Nothing is re-evaluated between
    # setting and keying (an update would play the action back over it).
    N = 24
    for i in range(N + 1):
        f = a0 + (a1 - a0) * i / N
        w = math.sin(2 * math.pi * i / N)
        # toward +X (the left foot) by d, that hip up: about -Y, +X goes up
        P = Matrix.Translation(Vector((SHIFT_D * w, 0, 0))) @ piv("pelvis", Matrix.Rotation(-SHIFT_TH * w, 4, "Y"))
        S = piv("spine_01", Matrix.Rotation(1.4 * SHIFT_TH * w, 4, "Y"))
        K = piv("neck_01", Matrix.Rotation(-0.4 * SHIFT_TH * w, 4, "Y"))
        for n, M in (("pelvis", P), ("spine_01", S), ("neck_01", K)):
            loc, rot, _ = arm.convert_space(pose_bone=pb[n], matrix=M @ m0[n], from_space="POSE", to_space="LOCAL").decompose()
            pb[n].location, pb[n].rotation_quaternion = loc, rot
            pb[n].keyframe_insert("location", frame=f)
            pb[n].keyframe_insert("rotation_quaternion", frame=f)
    return feet


acts = [make("Idle_HandsBehind_Loop", hands_behind), make("Idle_PADD_Loop", padd, extra=("Head", "neck_01")),
        make("Sitting_PADD_Loop", padd_sit, extra=("Head", "neck_01"), base=bpy.data.actions["Sitting_Idle_Loop_Armature"], loops=3, every=True),
        make("Idle_Shift_Loop", shift, loops=SHIFT_LOOPS, every=True)]
# the shift's still pose is all its other bones are: only those it moves go
shact = acts[-1]
for fc in list(shact.fcurves):
    if not any(fc.data_path.startswith(f'pose.bones["{n}"]') for n in SWAY_BONES):
        shact.fcurves.remove(fc)
for a in list(bpy.data.actions):
    if a not in acts:
        bpy.data.actions.remove(a)

if PREVIEW:
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 8
    sc.cycles.use_denoising = False   # this build has no OpenImageDenoise
    sc.cycles.device = "CPU"
    sc.render.resolution_x, sc.render.resolution_y = 360, 480
    w = bpy.data.worlds.new("w")
    w.color = (0.6, 0.6, 0.65)
    sc.world = w
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.rotation_euler = (0.8, 0.2, 0.6)
    sc.collection.objects.link(sun)
    for a in acts:
        arm.animation_data.action = a
        a0, a1 = (int(round(x)) for x in a.frame_range)
        # the shift at its quarter, the weight on the left foot
        sc.frame_set(a0 + (a1 - a0) // 4 if a.name == "Idle_Shift_Loop" else (a0 + a1) // 2)
        for side, loc, rot in (("front", (0, -3.2, 1.1), (math.radians(90), 0, 0)),
                               ("side", (3.2, 0, 1.1), (math.radians(90), 0, math.radians(90))),
                               ("back", (0, 3.2, 1.1), (math.radians(90), 0, math.radians(180)))):
            cam.location, cam.rotation_euler = loc, rot
            sc.render.filepath = os.path.join(OUT, f"pose-{a.name}-{side}.png")
            bpy.ops.render.render(write_still=True)

# the armature alone, with these two actions
for o in list(bpy.data.objects):
    if o is not arm:
        bpy.data.objects.remove(o)
arm.animation_data.action = None
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "poses.glb"), export_format="GLB", export_animations=True,
                          export_animation_mode="ACTIONS", export_force_sampling=True, export_frame_step=2,
                          export_skins=True, export_yup=True)
print(f"[deck-crew] poses.glb: {', '.join(a.name for a in acts)}")
