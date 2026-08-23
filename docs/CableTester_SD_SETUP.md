# CableTester: SD card and bench box setup

How to go from a blank microSD card to a working cable tester in an Apache 2800
case. Written for a **Raspberry Pi 4 Model B** driving a **7 inch 1024x600 HDMI
touchscreen**, with a USB-serial adapter for the cable under test.

> **Read `CLAUDE.md` first if you are picking this project up.** It carries the
> rules this project works by, including the one that governs this document:
> nothing here is verified on hardware until someone has run it on hardware.

---

## 0. What this box is, and the one rule that follows

The tester is a bench instrument. It grades a DB9 RS-232 cable by driving it at
speed and counting errors, so **anything that disturbs timing produces a wrong
answer that looks like a bad cable**. That single fact drives most of the
choices below: the power supply, the separate panel supply, the screen blanking
setting, and the undervoltage check in `cabletester-mode status`.

An underpowered Pi and a marginal cable look identical on this screen. Rule out
the Pi first.

---

## 1. Parts

| Part | What to use | Why it matters |
|------|-------------|----------------|
| Board | Raspberry Pi 4 Model B | 64-bit, has WiFi. A Pi 2 is 32-bit only and will not boot the image below. |
| Card | 32 GB or larger, **A1 or A2 rated**, real brand | The image needs 6.2 GB. Pick on the A rating, not the speed class: A1/A2 describe random IOPS, which is what a Pi actually does. U3 and V30 are sequential write ratings for cameras and buy nothing here. Cheap or unrated cards are the most common cause of a Pi that corrupts under power cycling. |
| Power, Pi | 5V 3A USB-C, ideally the official supply | A phone charger boots the Pi and then browns out under load. See section 0. |
| Power, panel | The panel's **own** supply | Do not run the panel off the Pi's USB. It is the largest load you could hang on that rail. |
| Panel | 7 inch 1024x600 IPS, HDMI video plus USB touch | **Verified:** picture needs no configuration, and touch works with nothing installed. Controller is WCH `1a86:e5e3`, claimed by `hid-multitouch`. Touch is a **separate USB cable**; HDMI is video only. |
| Serial | USB-serial adapter (FTDI, Prolific, CH340) | Appears as `/dev/ttyUSB0`. The UI shows VID:PID so you can tell a genuine FTDI (`0403:6001`) from a clone. |
| Keyboard | Small wireless keyboard in the case lid | The UI has three fields a tech must type into. See section 7. |
| Loopback plug | Per the README wiring table | The instrument tests a cable against this, not against a live device. |

> **Never wire an RS-232 cable to the GPIO header.** The header is 3.3 V logic,
> not RS-232 line levels, and a real cable will destroy the Pi. USB adapter only.

---

## 2. Write the card

**Image:** [raspberrypi.com/software/operating-systems](https://www.raspberrypi.com/software/operating-systems/)
→ **Raspberry Pi OS (64-bit)** → the plain **"Raspberry Pi OS"** entry, the one
described as *a port of Debian Trixie with the Raspberry Pi Desktop*.

- **Not "Full".** That adds LibreOffice and friends. A bench instrument opens
  one application; everything else is surface to patch.
- **Not "Lite".** No desktop means no Chromium kiosk.
- **64-bit**, because this is a Pi 4.

**Writer:** use **Raspberry Pi Imager**, not Etcher. Etcher writes the image
correctly but cannot pre-seed the settings below, which means doing the
first-run wizard by hand on the panel and enabling SSH yourself.

In Imager: *Choose device* `Raspberry Pi 4` → *Choose OS* → `Raspberry Pi OS
(other)` → `Raspberry Pi OS (64-bit)` → *Choose storage* → **Next** → **Edit
Settings**.

| Setting | Value |
|---------|-------|
| Hostname | `cabletester` (reachable as `cabletester.local`) |
| Username / password | Your choice. **The setup script reads this from the account it runs as, so nothing needs to match a hardcoded name.** |
| Wireless LAN | Your **desk** WiFi, not the bench. Country `US`. |
| Locale / timezone | Yours |
| Services → Enable SSH | **Yes**, password authentication |

**Let the verify pass finish.** Pulling the card when the write bar reaches 100%
skips the read-back that catches a bad or counterfeit card.

---

## 3. First boot

Connect the panel to the **micro-HDMI port nearest the USB-C power jack**
(that port is `HDMI-A-1`, which matters if you have to force a mode later).
Plug in the panel's USB touch cable, the keyboard, and the panel's own power.
Power the Pi last.

Expect a minute or so on first boot while the filesystem expands.

> **Touch runs over its own USB cable. HDMI carries video only.** This is the
> trap on this panel and it cost a round of debugging: the desktop appeared
> normally on the screen while touch did nothing, because only HDMI and the
> panel's power were connected. The panel has a separate socket, usually marked
> `Touch`, and some of these panels have two similar sockets where the other is
> power only. If touch does nothing, look at that cable before anything else.

**Verified on the kit, 8/23/2026:** the panel produced a correct desktop
picture with **no configuration at all**, and touch worked as soon as its USB
cable was connected, with nothing installed. The controller enumerates as:

```
idVendor=1a86  idProduct=e5e3
Product: USB2IIC_CTP_CONTROL     Manufacturer: wch.cn
hid-multitouch 0003:1A86:E5E3.0008: input,hidraw2
```

`1a86` is WCH and the part is a USB to I2C capacitive-touch bridge. The kernel
binds `hid-multitouch` to it on its own, so "driver free" is accurate. If touch
ever stops working, `dmesg | tail -20` after replugging the cable should show
that device appearing; if it does not, the fault is the cable, the socket or
the panel, not the software.

**The `video=` line below was not needed.** It is kept for the case where a
different panel or a different cable behaves worse.

### If the panel comes up wrong

Wrong resolution, black bars, or no picture at all. The fix is **not** the
`hdmi_cvt` and `hdmi_group` lines in older forum posts: those are legacy
firmware options, and current Raspberry Pi OS boots the KMS display driver,
which ignores them. Editing them wastes an evening and changes nothing.

Force the mode with a kernel parameter instead. Edit `/boot/firmware/cmdline.txt`
(it is **one single line**, add this to the end of it, space separated, do not
add a newline):

```
video=HDMI-A-1:1024x600M@60D
```

Then `sudo reboot`. If you are doing this on your laptop before first boot, the
file is on the small FAT partition of the card, visible as `bootfs`.

---

## 3b. Networking, and the trap that will cost you an hour

**Check IPv4 explicitly before assuming the network works.** On the kit, WiFi
associated, SSH worked, and the desktop showed a healthy connection, while the
Pi had **no IPv4 address at all**. It had taken an IPv6 unique local address by
SLAAC and nothing else.

That combination is genuinely misleading:

- `nmcli device status` says **`connected`**, because NetworkManager counts
  getting *one* address family as success.
- SSH works, because mDNS resolves `cabletester.local` to the IPv6 address.
- But `ping -4` says `Network is unreachable`, DNS fails (resolvers are IPv4),
  and there is **no internet**, because an `fd00::/8` address is private and not
  routable. So `apt` and `pip` both fail.
- And `run.py` binds `0.0.0.0`, which is IPv4 only, so nothing on the network
  can reach the tester even though the kiosk works fine on the panel.

Test it properly, in this order:

```bash
ip -4 addr show wlan0          # must print an inet line. No output is the bug.
ping -c2 -4 1.1.1.1            # routing off-subnet
curl -sS -m 10 -o /dev/null -w "internet: %{http_code}\n" https://deb.debian.org/
```

**A static address is the right answer for this box**, and not only as a
workaround for a router that will not hand out a lease. The URL a tech types
should never move. Set it with `sudo nmtui` (menu driven, far less to mistype
than the `nmcli` equivalent): *Edit a connection*, pick the WiFi, set **IPv4
CONFIGURATION** to **Manual**, then fill in an address outside the DHCP pool, the
gateway, and DNS. **Saving is not enough: deactivate and reactivate the
connection**, or the new address does not take.

On the kit this is `192.168.1.240/24`, gateway `192.168.1.1`. Those numbers are
specific to JP's desk network and mean nothing at another site. The bench has no
network at all, so the address only matters where the box is worked on.

If DHCP is failing and you just need internet once to install, **plug in an
ethernet cable or tether an Android phone over USB.** Both bypass wireless DHCP
entirely and take under a minute.

---

## 4. Get the code onto the Pi

**With a network on the Pi, clone it.** This is what was used on the kit and it
is the least fiddly:

```bash
git clone -b BRANCH https://github.com/JP-Jackson/CableTester ~/cabletester
cd ~/cabletester
ls deploy/
```

You should see `setup-pi.sh`, `cabletester-mode`, `kiosk.sh`, `vendor-fonts.sh`
and the two `.service` files. Substitute the branch you want, or drop `-b BRANCH`
for the default.

**Without a network on the Pi**, copy it from a USB stick:

```bash
cp -r /media/$USER/<STICK>/CableTester ~/cabletester
cd ~/cabletester
```

Copy it to the Pi's own disk either way. `setup-pi.sh` refuses to run from
`/media` or `/mnt`, because installing the service with its working directory on
a USB stick produces a tester that dies the moment the stick comes out.

If the copy came from a Windows machine, delete the virtualenv that travelled
with it. It contains Windows binaries and is useless here:

```bash
rm -rf ~/cabletester/.venv ~/cabletester/__pycache__ ~/cabletester/tester/__pycache__
```

---

## 5. Run the setup

```bash
./deploy/setup-pi.sh
```

One run, about five minutes. It is **safe to re-run**, and re-running it is the
supported way to apply a code update. It does:

- Installs `python3-venv`, `curl`, `git`, Chromium and an on-screen keyboard.
- Adds you to the `dialout` group, so the tester can open serial ports.
- Builds `.venv` and installs `pyserial` and `Flask`.
- Installs and starts **`cabletester.service`**, the tester server.
- Installs **`cabletester-kiosk.service`** (a user unit) and the autostart entry.
- Installs **`cabletester-mode`** to `/usr/local/bin`.
- Sets desktop autologin, disables screen blanking, confirms SSH is on.
- Reports whether this Pi has recorded undervoltage.

Then:

```bash
sudo reboot
```

It comes back into the kiosk. The `dialout` group membership also needs this
reboot before serial ports will open.

---

## 6. The two modes

This is the part worth understanding, because it is not what most people expect.

**Kiosk and your SSH access are not two modes. They run at the same time.**

| | What it does | When |
|---|---|---|
| `cabletester.service` | The tester server. **This is the instrument.** | Always. Both modes. |
| `cabletester-kiosk.service` | Chromium full screen on the panel. | Default on every boot. |
| SSH over WiFi | Your way in. | Always. Invisible to the tech. |

A tech opens the case, powers up, and meets one full-screen application. No
desktop, no taskbar, no login prompt, no screen blanking.

You SSH in from your laptop whenever you want and work without touching what
the panel shows. The server also binds `0.0.0.0`, so `http://cabletester.local:5000/`
from a phone shows the same live test.

The only thing that is actually a "mode" is what **this panel** displays:

```bash
cabletester-mode status     # what is running, plus ports and power
cabletester-mode desk       # drop the panel to the normal desktop
cabletester-mode kiosk      # lock it back to the tester
cabletester-mode restart    # reload the kiosk after a UI change
cabletester-mode logs       # follow the kiosk's output
```

The choice **survives a reboot**. `desk` stays `desk` until you set it back.

Dropping to the desktop never stops the server and never interrupts a sweep in
progress.

### What `status` tells you

```
saved mode:     kiosk
kiosk:          active
tester server:  active
serial ports:   /dev/ttyUSB0
power:          throttled=0x0
```

`power:` is there on purpose. Anything other than `throttled=0x0` means this Pi
has browned out or thermally throttled, and **on this instrument that looks
exactly like a marginal cable**. Check it before you believe a bad result.

---

## 7. Typing on a touchscreen

The UI has three places a person has to type: the **cable ID** field, the
**payload seconds** box, and the **profile name** prompt when saving a learned
profile. A bare touchscreen cannot fill any of them.

`setup-pi.sh` installs an on-screen keyboard. **Do not assume it pops up on its
own.** Auto-showing a keyboard when a web page field takes focus is not reliable
with Chromium on Linux under either display stack, and this has not been tested
on the panel yet. Keep the **small wireless keyboard in the case lid** and treat
it as the dependable path until someone confirms otherwise on real hardware.

If tapping a field never produces a keyboard and that becomes annoying, the
robust fix is an on-screen keyboard **inside the web app**, which works
regardless of the display stack. That is a change to the tester itself, not to
this deployment, and it has not been discussed or scoped.

---

## 8. Offline operation

The bench has no network. The tester needs none:

- **Fonts and icons are local**, in `static/fonts/`. Barlow, Barlow Condensed
  and a four-glyph Tabler subset, 178 KB in total. There is no CDN link left in
  the templates, so the UI looks identical on and off the network.
- The server, the serial layer and the scoring never touch the network.
- WiFi is configured for **your desk**. Out of range it simply does not
  associate, and nothing else changes.

Regenerate the fonts with `./deploy/vendor-fonts.sh` on a networked machine if a
weight or an icon is ever added. Do not add a CDN `<link>` back.

---

## 9. Updating the tester later

Copy the new code over the old, on a stick, then:

```bash
cd ~/cabletester
git pull
sudo systemctl restart cabletester     # Python changes need this
cabletester-mode restart               # UI changes need this
```

**Re-run `./deploy/setup-pi.sh` as well** whenever the dependencies changed, a
new file appeared in `deploy/`, or anything under `/etc` or `/usr/local` is
involved. It is idempotent and takes a few seconds on a second run.

`cabletester-mode` is symlinked from the repo rather than copied, so a plain
pull does update it. `kiosk.sh` and the templates likewise run from the repo.
The systemd unit files are copies, so those genuinely do need the script.

No reboot needed unless the dependencies changed.

---

## 10. If something is wrong

| Symptom | Look here first |
|---------|-----------------|
| Kiosk shows an error page at boot | The server lost a race. `systemctl status cabletester`. `kiosk.sh` already waits up to 60 s for it. |
| No serial ports in the dropdown | Adapter unplugged, or the `dialout` group has not taken effect yet. Reboot once after setup. |
| Panel blanks mid-test | `sudo raspi-config` → Display Options → Screen Blanking → No. Do not add `xset` calls; they do nothing under Wayland. |
| Known-good cable fails high baud rates | **Check `cabletester-mode status` power line before suspecting the cable.** Then `LINE_SETTLE_S` in `tester/serial_tests.py`, per DOC §11. |
| Kiosk will not start over SSH | It needs the session environment. Use `cabletester-mode kiosk`, which imports it, not `systemctl --user start` directly. |
| Chromium shows a "didn't shut down cleanly" bubble | `kiosk.sh` clears this at every start. If you see it, the kiosk is not what launched Chromium. |
| "Choose password for new keyring" on the panel | Chromium reaching for the desktop keyring on a box that has none. `kiosk.sh` passes `--password-store=basic` to stop it. If you see it, that copy of `kiosk.sh` predates the fix: pull and `cabletester-mode restart`. |
| `CABLETESTER_URL=... cabletester-mode restart` seems ignored | It is. A shell variable cannot reach a service systemd starts. Use `cabletester-mode url <URL>`, which writes a state file `kiosk.sh` reads, and `cabletester-mode url --reset` to undo. |
| Pi will not power on with a braided USB-C cable | Known early Pi 4 rev 1.1 e-marker issue. Use a plain cable or the official supply. |

---

## 11. What is and is not verified

Per the project's hardware reality rule, this section is the honest ledger. Move
items up as the bench proves them, and record what was learned in DOC §10.

### Verified on the kit, 8/23/2026

- **`setup-pi.sh` runs clean on a fresh image, first attempt, no edits.** Every
  step reported success on Trixie on a Pi 4: packages, venv, the systemd unit,
  the kiosk files, autologin, screen blanking, SSH. Afterwards
  `systemctl is-active cabletester` returned `active`, the page returned
  **200**, and `static/fonts/fonts.css` returned **200**, which is the check
  that proves the vendored fonts are being served locally rather than reached
  for over a network.
- **The kiosk comes up on boot, unattended.** After `sudo reboot` the panel
  showed the tester full screen with no intervention. This is the whole
  deployment working end to end: image, install, service, autologin, autostart,
  kiosk.
- **`cabletester-mode status` works** and reports the mode, the server, the
  serial ports and the power state.
- **The desktop is labwc on Wayland.** Confirmed indirectly but reliably: the
  installer tries the Wayland on-screen keyboards first and `wvkbd` was the one
  available and installed. This is why `kiosk.sh` must not use `xset`.
- **Board: Raspberry Pi 4 Model B Rev 1.2, 4 GB.** Rev 1.2 is past the early
  USB-C e-marker fault, so that warning does not apply to this board.
- **OS: Debian 13 Trixie**, from the 64-bit desktop image.
- **The panel needs no display configuration.** Correct picture, straight out of
  the box, no `video=` line and no `config.txt` edits.
- **Touch works with nothing installed.** WCH `1a86:e5e3`, bound by
  `hid-multitouch`. See section 3.
- **The two-port ethernet method links at gigabit.** A patch cable from the
  Pi's `eth0` to a USB adapter on `eth1` negotiated `1000Mb/s`, `Link
  detected: yes`. Two real PHYs talking to each other over the cable under
  test, which is better than a loopback plug: no fixture to build, real
  bidirectional traffic, and it sidesteps the fact that a patch cable has a
  plug at both ends while the tester has jacks. The USB adapter is
  `00:e0:4c:2e:83:c8`, a Realtek part on the `r8152` driver.
- **`ethtool --cable-test` is NOT supported** on the Pi's own PHY:
  "PHY driver does not support cable testing". So no time-domain
  reflectometry and no distance-to-fault. Pair-level diagnosis has to come
  from the speed ladder instead, which works because 10 and 100 use only
  pairs 1-2 and 3-6 while gigabit needs all four.
- **Power reads `throttled=0x0`** on the supply in use at the time of the check.
  This is a snapshot, not a guarantee: re-check it under load with the panel,
  the adapter and a sweep all running, which is when a weak supply actually
  fails.

### Not verified

- **Whether forcing a link speed takes on both ethernet chips.** The first
  attempt only forced one end, because the other command died on a shell
  placeholder, and it printed link state without printing the negotiated
  speed. Link came up at all three rungs, which proves nothing: with one end
  forced and the other autonegotiating, parallel detection brings the link up
  anyway, usually at half duplex. Re-run with `deploy/eth-probe.sh`.
- **Whether the link honestly goes down with the cable unplugged.** This is
  the confound that matters most. A test that passes on no cable is worse than
  no test. `eth-probe.sh` says to run it both ways for exactly this reason.
- **Whether the on-screen keyboard appears on field focus at all.** Section 7.
  The physical keyboard remains the dependable path.
- **Whether `LINE_SETTLE_S = 120 ms` holds** through a USB-serial adapter on a
  Pi 4. It was guessed without hardware, and DOC §14 is the plan for finding out.
- **The `cabletester-mode desk` / `kiosk` switch.** Installed, and `status`
  reports correctly, but the panel has not actually been switched back and forth
  yet, and the saved mode has not been proven to survive a power cycle.

### Known open problems on this kit

- **The clock is the remaining open problem.** See below.
- **The clock is wrong and will stay wrong at the bench.** A Pi 4 has no
  real-time clock. It restores an approximate time at boot and only corrects
  once NTP reaches a network. The bench has no network. Every `learned_at`,
  `exported_at` and `printed_at` this box writes will therefore be wrong, and a
  printed report carries its date to whoever staples it to a cable. A DS3231 RTC
  module on the GPIO header is the usual answer. **This is JP's decision and is
  not yet made.** See DOC §12.
