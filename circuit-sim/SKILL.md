---
name: circuit-sim
description: Simulate a circuit BEFORE component selection and board design, in two complementary passes — Falstad/CircuitJS1 (interactive, heuristic) to find the topology and build intuition, then ngspice (rigorous, scripted) for exact transient/AC responses, parametric sweeps, and data-driven part selection. ONE parametric SPICE deck is the source of truth; the Falstad netlist is GENERATED from it so the interactive toy and the rigorous sim never drift. Use for power converters, drivers, resonant tanks, filters, oscillators, analog front-ends — anything you'd otherwise guess at. Worked example: the plasma-art project sim/ (resonant half-bridge — AC resonance, MOSFET ZVS + loss, shared-load crosstalk, generated Falstad URLs, Makefile).
argument-hint: [circuit/topology to explore + the decision you need to make]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebFetch
---

The north star: **one parametric ngspice deck is the source of truth; everything else is generated
from it.** You simulate in two passes that answer different questions — Falstad to *decide what to
build*, ngspice to *prove it works and pick the parts* — and you do it BEFORE component selection and
board design, while changing a topology or a value is a one-line edit instead of a respin. The
Falstad netlist is emitted FROM the SPICE deck (same R/L/C values), so the interactive sim and the
rigorous sim can't drift apart.

## Two passes (use both, in this order)

| | Pass 1 — Falstad / CircuitJS1 | Pass 2 — ngspice |
|---|---|---|
| Question | "what topology? does this idea even work? what if I…?" | "exact transient/AC; which component; how much loss/stress?" |
| Mode | real-time, animated, drag a slider | scripted, headless, parametric, reproducible |
| Models | idealized (fast intuition) | real (VDMOS Coss/body-diode, vendor `.lib`) |
| Output | a feel, a topology, rough values | numbers: f₀, gain, ZVS, losses, margins → the part choice |
| Don't | trust it for loss/thermal/stress | explore blindly in it — feedback is too slow |

Reach for **LTspice** only when you want a specific vendor part's polished model + GUI; ngspice covers
it scriptably and runs headless (LTspice is GUI/Windows-first). Check tools once:
`which ngspice; python3 -c "import numpy,scipy,matplotlib"; which ffmpeg`.

## Pass 1 — Falstad for intuition (generate, never hand-place)

Hand-placing Falstad pixel coordinates is the error-prone part. **Generate the netlist from the SPICE
deck** so values stay in sync and "open it" is one command:

```python
# falstad_gen.py — parse a .cir, emit a CircuitJS netlist + an ONLINE share URL
import re, urllib.parse, webbrowser
SUF={'meg':1e6,'k':1e3,'m':1e-3,'u':1e-6,'n':1e-9,'p':1e-12,'f':1e-15}
def num(s,env):                                   # SI suffixes, {expr}, bare param refs
    s=s.strip().strip('{}')
    m=re.fullmatch(r'([0-9][0-9.eE+\-]*)\s*(meg|[a-z]?)',s,re.I)
    if m: v=float(m[1]); su=m[2].lower(); return v*(1 if su=='' else SUF.get(su,SUF.get('meg',1)) if su=='meg' else SUF.get(su,1))
    return float(eval(s,{'__builtins__':{}},dict(env)))
def parse(path):                                  # STRIP inline comments first (; $ and * lines)
    env,dev={},{}
    for raw in open(path):
        ln=raw.split(';')[0].split('$')[0].strip()
        if not ln or ln.startswith('*'): continue
        if ln.lower().startswith('.param'):
            for k,v in re.findall(r'(\w+)\s*=\s*(\{[^}]*\}|\S+)',ln[6:]): env[k]=num(v,env)
        elif re.match(r'^[RrCcLl]\w*\s',ln):
            t=ln.split();
            try: dev[t[0]]=num(t[-1],env)
            except: pass
    return env,dev
BASE="https://www.falstad.com/circuit/circuitjs.html"   # online; local: http://localhost:8000/circuitjs.html
def open_url(netlist_txt): webbrowser.open(BASE+"?cct="+urllib.parse.quote(netlist_txt))
```

- **Online by default** — `https://www.falstad.com/circuit/circuitjs.html?cct=<urlencoded netlist>`,
  no install. `?cct=` is the raw circuit text URL-encoded (`urllib.parse.quote`; spaces→%20,
  newlines→%0A). If a build rejects it, fall back to **Menu → File → Import From Text**.
- **Local only if offline**: clone `pfalstad/circuitjs1`, `./test.sh 8000` (or `gradle compileGwt
  makeSite` then serve `site/`), and point BASE at `http://localhost:8000/circuitjs.html`.
- **Element dump quick-ref** (grid coords, multiples of ~16):
  ```
  $ <flags> <dt> <speed> <iters> <curspeed> <voltrange> <gmin>   header
  w x1 y1 x2 y2 0                  wire        g x1 y1 x2 y2 0                 ground
  r .. 0 <R>   c .. 0 <C> 0   l .. 0 <L> 0                                    R / C / L
  v x1 y1 x2 y2 0 <wf> <freq> <Vamp> <bias> <phaseRad> <duty>   source  (wf: 0 DC, 1 AC, 2 square)
  d x1 y1 x2 y2 2 default          diode (anode->cathode)
  T x1 y1 x2 y2 0 <Lpri> <ratio> 0 0 <k>   transformer (primary = left column, secondary = right)
  f x1 y1 x2 y2 0 <Vt> <beta>     n-MOSFET (gate post auto-placed — verify after import)
  ```
- **What it's for:** sweep frequency live (right-click source → Edit, or add a slider) and watch
  resonance balloon; see current dots / node-voltage colors; try a topology variant in seconds.
- **MOSFET caveat:** Falstad's MOSFET gate-post geometry + floating-gate phase are version-sensitive,
  so an auto-generated half-bridge usually needs the gate leads nudged onto the FET gates after
  import. Add explicit **body diodes + Coss caps** so soft-switching is visible. Passive netlists
  (R/L/C + transformer + source) generate cleanly and import without fuss.

## Pass 2 — ngspice for rigor

**One deck, everything parametrized.** `.param` every value; derive dependents with `{expr}`.

**Resonance / transfer function (AC = first-harmonic approx):** drive with a 1 V AC source.
```spice
.param L=47u C=0.22u
Vac in 0 AC 1
Cs in a {C}
L1  a out {L}
Rl  out 0 1k
.control
ac dec 400 1k 3Meg
wrdata ac.dat vdb(out) vm(out)
meas ac fpk MAX_AT vm(out)     ; f0 ; vm peak = step-up
.endc
.end
```
AC is *linear* — it's the first-harmonic picture of your real square drive. Use **transient** for the
true waveform (PULSE source, run long enough to reach steady state, modest `.options reltol=2e-3`).

**MOSFET-level (the part that needs care):**
- Use the **VDMOS** model — it bakes in **Coss + body diode**, which an ideal switch hides and which
  *are* the soft-switching mechanism: `.model PWRMOS VDMOS(Vto=3.5 Kp=18 Rd=0.04 Cgdmax=1.2n
  Cgdmin=0.05n Cgs=1.2n Cjo=0.45n Rb=0.02 BV=100 Is=2e-12)`.
- ngspice's `i(Mxxx)` for MOSFETs is unreliable — insert **0 V sense sources in each drain** and read
  `i(VsenseH)` / `i(VsenseL)`.
- **ZVS lives ABOVE series resonance** (inductive load): operate there. Check that `v(sw)` reaches the
  opposite rail *during the deadtime* before the incoming gate rises, and that drain current dips
  negative (body-diode conduction) at turn-on.

**Parametric sweep = the product.** Either `.step param C list 0.1u 0.22u 0.47u`, or a Python loop
re-invoking `ngspice -b` with overridden params; extract the figure of merit per value and **pick the
component off the curve**. This is data-driven part selection — the whole reason to simulate first.

**Python analysis (reusable):**
```python
import numpy as np
d = np.loadtxt("ac.dat")            # wrdata: columns are x,y,x,y,...  (each vector preceded by its x)
f, vm = d[:,0], d[:,3]; f0 = f[np.argmax(vm)]
# steady-state averages (transient is adaptive-step -> resample before any FFT):
def avg(x,t,lo,hi):
    m=(t>=lo)&(t<=hi); return np.trapezoid(x[m],t[m])/(t[m][-1]-t[m][0])   # numpy 2.x: trapezoid
P_fet = avg((Vbus - v_sw)*i_H, t, 1.4e-3, 1.6e-3)                          # mean(Vds*Id) = loss
```
matplotlib `Agg` → PNG; for an end-to-end "see it work" demo, drive the *real engine/firmware logic*
through the *measured* transfer curve and render an mp4 (ffmpeg).

## Component selection (the payoff)

- Map each value to its effect analytically AND confirm in sim (e.g. `f0 = 1/(2π√(LC))` → table, then
  AC `.meas` to verify the loaded resonance).
- Drop a **vendor SPICE `.lib`/`.model`** (or VDMOS params from the datasheet: Qg, Coss, Rds(on), BV)
  into the deck and re-run the transient to compare **loss / peak stress / ZVS window / temperature**
  across *real* candidate parts before buying.
- Decide on numbers, not vibes: "IRF540N → 0.46 W, ZVS to 60 kHz" vs the alternative.

## Handoff to physics sim (keep them separate — for now)

A circuit rarely matters on its own — its output drives something physical (a coil's force, a
plasma's brightness, a motor's torque, a heater's power). **Don't co-simulate the full SPICE circuit
and the physics in lockstep yet** — it's a lot of machinery and usually unnecessary. Escalate only as
the coupling demands:

- **One-way handoff (default):** run the circuit sim, export the one result the physics cares about —
  a drive waveform (`wrdata` table), an operating point (V/I/freq), or a transfer curve — and feed it
  as a forcing function/input to the physics sim. (Worked example: engine frequency × the *measured*
  resonance curve → plasma glow.)
- **Lumped-ODE coupling (when the physics loads the circuit back):** if back-EMF / a moving gap /
  changing impedance feeds back, don't run SPICE inside the physics loop — integrate a *reduced*
  lumped circuit ODE (e.g. `i' = (V − iR)/L`) at the physics timestep. Cheap, stable, captures the
  dominant coupling.
- **Full co-sim (deferred):** SPICE-accurate circuit ⇄ physics in lockstep is the eventual goal;
  revisit only when one-way + lumped-ODE genuinely miss the behavior.

This skill is **standalone** — it ends at "the circuit's numbers/waveforms." Whatever consumes them
(a physics sim, firmware, a part-selection decision) is a separate step.

## Verify every run

- Loaded resonance/gain matches the analytic estimate (sanity gate).
- **Steady state reached before you average** — never measure the ring-up window.
- Losses/currents physical, no NaN, waveforms bounded.
- A known-physics check (energy balance, V·I sign, 50% duty ⇒ symmetric drive).
- Plots + the parametric/comparison figure regenerated; the Falstad URL actually opens the circuit.

## File layout & Makefile

```
sim/  *.cir (parametric decks)   falstad_gen.py (deck -> Falstad URL)   *_plot.py (analysis)   *.png/*.mp4
Makefile:  make sim | make demo | make falstad-gen | make falstad CCT=<name>   (online by default)
```
In the Makefile, **put comments on their own lines** — an inline `VAR ?= val  # note` folds the
trailing spaces into the value and corrupts filenames/URLs. Open online:
`make falstad CCT=foo` → `python3 -c "...webbrowser.open(BASE+'?cct='+quote(open('sim/foo.txt').read()))"`.

## Pitfalls (hard-won)

- **numpy 2.x removed `np.trapz`** → use `np.trapezoid`.
- **`i(Mxxx)` unreliable for MOSFETs** → 0 V sense sources in the drains.
- **Ideal switch hides ZVS** → use VDMOS (Coss + body diode); for Falstad add explicit Coss + diodes.
- **ZVS only above resonance** — at/below f₀ you hard-switch; dimming-by-detune-up keeps you inductive.
- **SPICE parse:** strip inline comments (`;`, `$`, `*`) before any `eval`; `meg`=1e6 but `m`=1e-3.
- **`wrdata` repeats the x-column** per vector → columns are `[x,y,x,y,…]`; ngspice timestep is
  adaptive, so **resample to a uniform grid before FFT**.
- **High-Q + light load → absurd sim step-up** (10s of kV from 36 V); add a realistic load/series R and
  operate off-resonance — the real tube/load lowers Q once struck.
- **Falstad `?cct=`** = raw URL-encoded text; MOSFET gate posts + gate *phase* are version-sensitive
  (nudge after import); passives import clean; Import-From-Text is the fallback.
- **Makefile inline-comment trailing space** silently corrupts `CCT`/`PAGE`/URL — comments on own lines.
- **Convergence on switching/high-Q:** tighten `.options`, give the transient enough cycles to settle,
  and average only over a late steady-state window.
- **AC is linear (FHA)** — great for resonance/gain shape, but it can't show ZVS, harmonics, or large-
  signal behavior; that's what the transient + VDMOS pass is for.
