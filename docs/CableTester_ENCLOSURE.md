# CableTester: the kit

The physical build. A Raspberry Pi 4, a 7 inch touchscreen and captive test
adapters in a Harbor Freight Apache 2800, with a 3D printed deck carrying
panel-mount connectors.

> **Nothing here is built yet.** This is the design and the reasoning behind
> it, recorded so decisions are not remade from scratch. Measure before you
> print: every dimension below needs confirming against the parts in your hand.

---

## 1. Decisions made

| | |
|---|---|
| **Use posture** | **Lid open on a bench, closed only to carry.** |
| **Power** | Mains normally. Leave room for a battery pack later. |
| **Panel connectors** | DB9 female, two RJ45, power inlet, one USB-A service port |
| **Screen** | In the base on the deck, not in the lid |

**Lid-open operation is the decision that matters most**, and it solves a
problem the case would otherwise create. The Apache 2800 is gasketed and
sealed, which is its whole point and is directly at odds with a Pi 4 and a
backlit panel running continuously. A Pi 4 throttles at 80 C, and **thermal
throttling produces exactly the failure this instrument exists to avoid**:
timing errors and link instability that are indistinguishable, on screen, from
a marginal cable. Running with the lid open means convection does the work and
no fan, no vents and no lost waterproof rating are needed.

**Screen in the base, not the lid.** A lid-mounted screen looks better and puts
the HDMI and USB runs across the hinge, which is the highest-wear point in the
whole build and the first thing that will fail. Deck-mounted keeps every cable
static.

---

## 2. Fitting it

**Measure your case and your panel before printing anything.** The Apache 2800
interior is roughly 13 x 9 x 4 inches, and the 7 inch panel is roughly 165 x
100 mm with an active area near 154 x 86 mm, but both vary and neither number
should be trusted from this document.

The width is comfortable: a 6.5 inch panel across a 13 inch case leaves half
the deck for connectors and the electronics. **Depth is the constraint**, at
roughly 4 inches for the panel plus standoffs plus whatever hangs underneath.

Suggested arrangement, in two printed parts rather than one:

- **A flat deck** spanning the base. The panel drops through a cutout from
  above; the Pi, both USB adapters and the wiring mount underneath.
- **A separate vertical fascia** along the front edge carrying the four
  connectors.

Two parts because panel-mount connectors need a vertical face, an L-shaped
single print is awkward to lay out, and a fascia can be revised without
reprinting the whole deck. Expect to revise it: connector cutouts are the
thing nobody gets right first time.

**Print it in PETG or ASA, not PLA.** A closed dark case in a truck cab or a
sunny shop reaches well past 55 C, which is where PLA begins to sag. A warped
deck that drops the panel is an expensive way to learn this.

---

## 3. The instrument problem the connectors create

This is the part worth thinking about before the plate is drawn, because it
changes what the tester measures.

**Every panel connector adds a mated pair and a pigtail to the signal path,
and they become part of every measurement.** The cable under test is no longer
the only thing between the two adapters: the tester's own internals are in
series with it.

- **RS-232 does not care.** At 115200 over a short internal run, the extra
  connector is invisible.
- **Gigabit ethernet cares.** Two more mated pairs and two internal pigtails
  are a real contribution to the loss budget, and the ladder's top rung is
  exactly where that shows up. A kit with poor internal cabling would fail
  good cables at 1000 Mb and blame them.

Two rules follow:

1. **Internal pigtails as short as will physically reach**, and use decent
   ones. This is not the place for the cheapest patch leads.
2. **Baseline the kit itself.** Test a known-good short cable through the
   panel connectors, record what the kit contributes, and keep that as the
   reference. If the kit cannot pass gigabit through its own connectors with a
   good cable, no result from it means anything. **Do this before the kit
   tests a single field cable.**

---

## 4. Build rules

- **Strain relief every panel connector.** A tech pulling a cable must load
  the fascia, not the Pi's USB socket. This is where builds like this fail,
  and the failure looks like an intermittent instrument.
- **Keep the SD card reachable** without pulling the deck. Otherwise every
  card swap is a disassembly, and the card is the part most likely to need
  swapping.
- **The USB-A service port is a hole in a sealed case.** Accepted
  deliberately: the ability to plug a keyboard in without opening the case is
  worth more than an IP rating on a box that runs with its lid open anyway.
- **Leave volume for a battery pack** even though the build is mains. Adding
  it later without a redesign is worth a little wasted space now.
- **Somewhere for the loose parts**: the loopback plug, the spare SD card, the
  wireless keyboard. Foam in the lid or a printed tray.

---

## 5. Open questions

- **Exact panel and case dimensions.** Measure and record them here.
- **RJ45 panel style:** keystone jacks, or shielded feed-through couplers?
  Feed-through is fewer terminations and fewer places to get the pinout wrong.
- **Whether the DB9 is wired straight through** to the captive USB-serial
  adapter, or whether the adapter's own shell is simply panel-mounted. The
  second is fewer connections and fewer things to get wrong, if it fits.
- **Where the loopback plug lives** so a tech cannot start a test without it.
