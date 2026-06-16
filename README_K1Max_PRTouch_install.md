# K1 Max Creality PRTouch v2 host integration

Experimental Klipper host integration for a rooted Creality K1 Max using:

- Cartographer for bed mesh / bed mapping.
- Creality PRTouch v2 for final Z touch / Z home.
- Creality-style bed MCU firmware.
- Dedicated config/macros from the matching config repository.

This is alpha software. It worked on my modified K1 Max. It is not plug-and-play.

If you do not know how to backup and recover your printer, stop here.

## Matching repositories

Use the three matching branches:

- Host Klipper:
  - repo: https://github.com/MicioMax-Klipper/klipper.git
  - branch: mdf-prtouch-creality-host

- Config:
  - repo: https://github.com/MicioMax-Klipper/k1max-config.git
  - branch: mdf-prtouch-creality-config

- Bed firmware:
  - repo: https://github.com/MicioMax-Klipper/k1-klipper-firmware.git
  - branch: k1max-creality-prtouch-bed

## What this host branch adds

Important changes include:

- Creality PRTouch v2 host wrapper integration.
- ACCURATE_HOME_Z support for the final Creality-style Z touch.
- PRTOUCH_HOME_Z_COARSE for a fast coarse Z home used before nozzle cleaning.
- Compatibility fix for Klipper toolhead queue naming, move_queue / lookahead.
- Firmware binaries stored under fw/K1 for this experimental setup.

## Firmware files included in this repository

Known relevant files:

    fw/K1/bed0_110_G21-bed0_117_001.bin
    fw/K1/mcu0_120_G32-mcu0_117_001.bin

The original reference files are also kept in fw/K1.

Do not flash these on a different target unless you know exactly what you are
doing.

## Brutal install outline

This deliberately replaces the active Klipper tree. Backup first.

On the K1 Max:

    /etc/init.d/S55klipper_service stop

    cd /usr/data
    mv klipper klipper.backup.$(date +%Y%m%d_%H%M%S)

    git clone https://github.com/MicioMax-Klipper/klipper.git klipper
    cd /usr/data/klipper
    git checkout mdf-prtouch-creality-host

Then install the matching config repository. See the config README.

## MCU flasher

Flashing requires a working K1 MCU flasher setup. My fork is here:

    https://github.com/MicioMax-Klipper/k1_mcu_flasher.git

Read that README. RTFM. Do not ask me why your printer is bricked if you flash
random firmware on random hardware.

Typical install location:

    cd /usr/data
    git clone https://github.com/MicioMax-Klipper/k1_mcu_flasher.git
    cd k1_mcu_flasher

Use the flasher according to its own README.

## Flashing the experimental firmware

The helper commands below assume your system has the usual K1 flash helper
wrappers installed. If your helper names differ, use the flasher README and
adapt the commands.

Bed MCU:

    flash_bed_mcu /usr/data/klipper/fw/K1/bed0_110_G21-bed0_117_001.bin

Main MCU:

    flash_mcu /usr/data/klipper/fw/K1/mcu0_120_G32-mcu0_117_001.bin

After flashing, continue with the matching config repository and restart Klipper
as required by your installation.

## Known-good print sequence

The important part is the order:

1. heat bed and start hotend heating
2. nozzle prep / wipe
3. Cartographer bed mesh
4. Creality PRTouch final Z home
5. purge
6. print

The final PRTouch Z home must happen after the Cartographer mesh is created or
loaded.
