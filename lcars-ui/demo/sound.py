#!/usr/bin/env python3
"""The reel's soundtrack: the app's own voice, plus a bed to put it on.

Three things live here.

**The chirps.** The app has 25 named sounds (`SFX` in index.html) and they are
not recordings — each one is a little table of oscillator frequencies played by
`sndPlay()`. Headless Chromium has no audio device, so none of it can be
captured; but `sndAc` and `sndMaster` are plain top-level bindings, so they can
be pointed at an `OfflineAudioContext` and the app's *own* scheduler asked to
render each sound exactly. That is what `render_sfx()` does. The result is the
app's real voice, sample for sample, and it is reproducible.

**The bed.** A starship bridge is mostly drone and filtered air, which is
cheap and convincing to synthesise: a couple of low sines beating against each
other, noise through a soft lowpass, and a very slow swell over the whole
thing.

**The pad.** An original progression — stacked fifths and ninths, long swells
— quiet under the tour and lifted under the title and end cards. It is written
in the idiom; it is not anyone's cue.

    python3 demo/sound.py --preview     # render the sfx and 20s of bed+pad
    python3 demo/sound.py --sfx         # just the sfx wavs

`build.sh` calls `track()` with the event timeline to make the real thing.
"""
import argparse
import array
import json
import math
import pathlib
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
SR = 48000


def np():
    """numpy, or a message that says which package is missing."""
    try:
        import numpy
    except ImportError:
        sys.exit("demo/sound.py needs numpy:  sudo apt-get install python3-numpy")
    return numpy


# ------------------------------------------------------------------- wav io
def write_wav(path, left, right=None, sr=SR):
    """16-bit stereo. Clipped rather than wrapped, and told about it.

    Works on plain lists as well as arrays, so rendering the app's sounds
    needs nothing but Playwright and the standard library. The mix goes
    through the fast path, because several million samples one at a time in
    Python is slow enough to notice.
    """
    right = left if right is None else right
    try:
        import numpy as n
    except ImportError:
        n = None

    if n is not None:
        left = n.asarray(left, dtype=n.float64)
        right = n.asarray(right, dtype=n.float64)
        peak = float(max(n.abs(left).max(), n.abs(right).max())) if len(left) else 0.0
        both = n.stack([n.clip(left, -1, 1), n.clip(right, -1, 1)], axis=1)
        pcm = (both * 32767.0).astype("<i2").tobytes()
    else:
        peak = max((abs(v) for v in left), default=0.0)
        out = array.array("h")
        for a, b in zip(left, right):
            out.append(int(max(-1.0, min(1.0, a)) * 32767))
            out.append(int(max(-1.0, min(1.0, b)) * 32767))
        if sys.byteorder == "big":
            out.byteswap()
        pcm = out.tobytes()

    if peak > 1.0:
        print(f"   ! {path.name} peaked at {peak:.2f}, clipping")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return path


def read_wav(path):
    n = np()
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        ch = w.getnchannels()
    a = n.frombuffer(frames, dtype="<i2").astype(n.float64) / 32767.0
    return a.reshape(-1, ch) if ch > 1 else n.stack([a, a], axis=1)


# ------------------------------------------------------- the app's own voice
def render_sfx(out=None, sr=SR):
    """Render every entry in the app's SFX table through its own sndPlay().

    One browser, one OfflineAudioContext per sound. `sndAc` and `sndMaster`
    are rebound rather than reimplemented, so what comes out is what the page
    would have made — including the envelope shapes and the exponential ramps
    that keep the square waves from clicking.
    """
    import demo as D
    from playwright.sync_api import sync_playwright

    out = pathlib.Path(out or OUT / "sfx")
    out.mkdir(parents=True, exist_ok=True)
    made = {}
    with sync_playwright() as p:
        browser, ctx, page = D.open_app(p, out, 800, 600, record=False)
        names = page.evaluate("Object.keys(SFX)")
        for name in names:
            got = page.evaluate("""async a => {
              const [name, sr] = a;
              // long enough for the longest sound plus its release tail
              const oac = new OfflineAudioContext(1, sr * 2, sr);
              sndAc = oac;
              sndMaster = oac.createGain();
              sndMaster.connect(oac.destination);
              sndMaster.gain.value = SND_GAIN * snd.vol;
              sndPlay(SFX[name]);
              const buf = await oac.startRendering();
              const ch = buf.getChannelData(0);
              let last = 0;
              for (let i = 0; i < ch.length; i++) if (Math.abs(ch[i]) > 2e-4) last = i;
              return Array.from(ch.slice(0, last + Math.round(sr * 0.01)));
            }""", [name, sr])
            write_wav(out / f"{name}.wav", got, sr=sr)
            made[name] = len(got) / sr
        browser.close()
    return made


# --------------------------------------------------------------- the synth
def _lowpass(x, hz, sr=SR):
    """A gentle rolloff, done in the frequency domain.

    A one-pole filter is a sample-by-sample recurrence, which in Python over
    several million samples is slow enough to notice. This is one rfft and one
    inverse, and for a pad and some noise it sounds the same.
    """
    n = np()
    spec = n.fft.rfft(x)
    f = n.fft.rfftfreq(len(x), 1 / sr)
    spec *= 1.0 / (1.0 + (f / hz) ** 2)          # -6 dB/oct, soft knee
    return n.fft.irfft(spec, len(x))


def _saw(t, hz):
    """Naive ramp. It aliases up high; everything here is low and filtered."""
    n = np()
    return 2.0 * n.mod(t * hz, 1.0) - 1.0


def bed(seconds, sr=SR):
    """Bridge ambience: drone, air, and a very slow swell.

    Almost none of this is musical — it is two low sines a fifth apart, beating
    slightly because they are detuned by a fraction of a hertz, under noise
    soft enough to read as room rather than hiss.
    """
    n = np()
    t = n.arange(int(seconds * sr)) / sr

    drone = (0.50 * n.sin(2 * n.pi * 55.0 * t)
             + 0.50 * n.sin(2 * n.pi * 55.13 * t)     # the beat
             + 0.30 * n.sin(2 * n.pi * 82.5 * t)      # a fifth up
             + 0.12 * n.sin(2 * n.pi * 110.0 * t)
             + 0.06 * n.sin(2 * n.pi * 164.8 * t))

    rng = n.random.default_rng(1701)
    air = _lowpass(rng.standard_normal(len(t)), 700.0, sr)
    air /= (n.abs(air).max() or 1.0)
    # the air breathes, slowly and not quite regularly
    air *= 0.55 + 0.45 * (0.5 + 0.5 * n.sin(2 * n.pi * 0.043 * t + 1.1))

    swell = 0.80 + 0.20 * n.sin(2 * n.pi * 0.017 * t)
    mono = (0.055 * drone + 0.030 * air) * swell

    # a little width: the air, delayed a few ms on one side
    d = int(0.011 * sr)
    left = mono.copy()
    right = mono.copy()
    right[d:] += 0.012 * air[:-d] * swell[d:]
    left[d:] += 0.012 * air[:-d][::-1] * swell[d:] * 0.6
    return left, right


# An original progression. Open voicings — fifths and ninths, no thirds in the
# bass — which is most of why the idiom sounds like it does.
CHORDS = [
    (110.00, 164.81, 246.94, 329.63),   # A2  E3  B3  E4   — Am(add9), no third
    (87.31,  130.81, 196.00, 293.66),   # F2  C3  G3  D4   — Fmaj9, no third
    (130.81, 196.00, 293.66, 392.00),   # C3  G3  D4  G4   — Cadd9
    (98.00,  146.83, 220.00, 293.66),   # G2  D3  A3  D4   — Gsus2
]


def pad(seconds, bar=11.0, sr=SR):
    """Slow stacked-saw chords, each one swelling in and out of the next."""
    n = np()
    total = int(seconds * sr)
    t = n.arange(total) / sr
    left = n.zeros(total)
    right = n.zeros(total)

    i = 0
    start = 0.0
    while start < seconds:
        chord = CHORDS[i % len(CHORDS)]
        i += 1
        a0 = int(start * sr)
        a1 = min(total, int((start + bar * 1.7) * sr))   # long overlapping tail
        if a1 - a0 < sr:
            break
        span = t[a0:a1] - start
        # in over four seconds, out over the rest: a swell, not a stab
        env = n.minimum(span / 4.0, 1.0) * n.clip(1.0 - (span - 4.0) / (bar * 1.7 - 4.0), 0, 1)
        env = env ** 1.6

        voice = n.zeros(len(span))
        for k, hz in enumerate(chord):
            for cents in (-7.0, 0.0, 7.0):            # three detuned saws each
                f = hz * (2.0 ** (cents / 1200.0))
                voice += _saw(span, f) / (1.6 + k)
        voice = _lowpass(voice, 900.0 + 500.0 * float(env.mean()), sr)
        voice *= env / (n.abs(voice).max() or 1.0)

        # the two sides take the chord at slightly different detunes
        left[a0:a1] += voice * 0.62
        right[a0:a1] += n.roll(voice, int(0.017 * sr)) * 0.62
        start += bar

    return 0.16 * left, 0.16 * right


# ------------------------------------------------------------------ the mix
def track(events, seconds, sfx_dir=None, lifts=(), out=None, sr=SR):
    """bed + pad + every chirp at its moment, as one wav.

    `events` is [[name, seconds], …] already on the finished video's clock.
    `lifts` is [(start, end), …] where the pad comes up — the title and end
    cards, which have no app noise under them to compete with.
    """
    n = np()
    sfx_dir = pathlib.Path(sfx_dir or OUT / "sfx")
    out = pathlib.Path(out or OUT / "track.wav")
    total = int(seconds * sr)

    bl, br = bed(seconds, sr)
    pl, pr = pad(seconds, sr=sr)

    # the pad sits back under the tour and comes up under the cards
    gain = n.full(total, 0.42)
    tt = n.arange(total) / sr
    for a, b in lifts:
        ramp = 1.5
        up = n.clip((tt - (a - ramp)) / ramp, 0, 1) * n.clip(((b + ramp) - tt) / ramp, 0, 1)
        gain = n.maximum(gain, 0.42 + 0.58 * up)
    left = bl + pl * gain
    right = br + pr * gain

    cache, missing = {}, set()
    for name, at in events:
        if name not in cache:
            f = sfx_dir / f"{name}.wav"
            if not f.exists():
                missing.add(name)
                cache[name] = None
            else:
                cache[name] = read_wav(f)
        a = cache[name]
        if a is None:
            continue
        i = int(at * sr)
        if i < 0 or i >= total:
            continue
        j = min(total, i + len(a))
        left[i:j] += a[:j - i, 0] * 2.6          # the chirps sit on top
        right[i:j] += a[:j - i, 1] * 2.6
    if missing:
        print(f"   ! no wav for {', '.join(sorted(missing))} — run --sfx")

    write_wav(out, left, right, sr)
    return out


def from_plan(plan_path, out=None):
    """Build the whole soundtrack from what build.sh measured off the video.

    Each part of the reel was filmed separately and carries its own clap, so
    each has its own page-clock-to-video-clock offset. The plan says, per part,
    where the clap landed in the raw recording, where the head was trimmed to,
    and where the part sits in the finished cut; everything else follows.
    """
    plan_path = pathlib.Path(plan_path)
    plan = json.loads(plan_path.read_text())
    base = plan_path.parent
    seconds = float(plan["seconds"])

    events, dropped = [], 0
    for part in plan["parts"]:
        log = json.loads((base / part["audio"]).read_text())
        clap_page = log["clap_page_ms"] / 1000.0
        for name, ms in log["events"]:
            # where it was in the raw recording, then into the trimmed
            # segment, then into the finished cut
            t = (part["clap_video"] + (ms / 1000.0 - clap_page)
                 - part["cut"] + part["offset"])
            if 0.0 <= t < seconds:
                events.append([name, t])
            else:
                dropped += 1
    # the boot chime and anything else placed by hand
    events += [[n, float(t)] for n, t in plan.get("extra", [])]
    events.sort(key=lambda e: e[1])

    print(f"   {len(events)} sounds placed"
          + (f", {dropped} outside the cut" if dropped else ""))
    return track(events, seconds, lifts=plan.get("lifts", []), out=out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sfx", action="store_true", help="render the app's sounds")
    ap.add_argument("--preview", action="store_true",
                    help="render the sounds and 20s of bed+pad, and report")
    ap.add_argument("--track", metavar="PLAN.JSON",
                    help="build the full soundtrack from build.sh's plan")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    out = pathlib.Path(args.out)

    if args.track:
        print("  ", from_plan(args.track, out / "track.wav"))
        return 0

    if args.sfx or args.preview:
        made = render_sfx(out / "sfx")
        print(f"   {len(made)} sounds -> {out / 'sfx'}")
        longest = sorted(made.items(), key=lambda kv: -kv[1])[:4]
        print("   longest:", ", ".join(f"{k} {v*1000:.0f}ms" for k, v in longest))

    if args.preview:
        n = np()
        bl, br = bed(20)
        write_wav(out / "preview-bed.wav", bl, br)
        pl, pr = pad(20)
        write_wav(out / "preview-pad.wav", pl, pr)
        for nm, (l, r) in (("bed", (bl, br)), ("pad", (pl, pr))):
            rms = float(n.sqrt(n.mean(l ** 2)))
            print(f"   {nm}: peak {float(n.abs(l).max()):.3f}  "
                  f"rms {20 * math.log10(rms + 1e-12):.1f} dBFS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
