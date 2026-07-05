# PRTouch Z wrapper.
#
# This module intentionally does not modify the Creality PRTouch wrapper.
# It calls the existing run_G28_Z() primitive, then bakes a fixed Z offset
# into the kinematic Z position. This keeps Fluidd's G-code offset clean.

class PRTouchZWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.prtouch_object = config.get("prtouch_object", "prtouch")
        self.default_offset = config.getfloat("z_offset", 0.0)

        self.gcode.register_command(
            "Z_PRTOUCH",
            self.cmd_Z_PRTOUCH,
            desc=self.cmd_Z_PRTOUCH_help,
        )

    cmd_Z_PRTOUCH_help = (
        "Run Creality PRTouch Z routine and bake fixed offset into kinematic Z"
    )

    def _lookup_creality_prtouch(self, gcmd):
        obj = self.printer.lookup_object(self.prtouch_object)

        # In some configs this may already be the Creality wrapper.
        if hasattr(obj, "run_G28_Z"):
            return obj

        # Usually [prtouch] is Klipper's PrinterProbe wrapper and the real
        # Creality PRTouch object is stored as its MCU probe.
        mcu_probe = getattr(obj, "mcu_probe", None)
        if mcu_probe is not None and hasattr(mcu_probe, "run_G28_Z"):
            return mcu_probe

        raise gcmd.error(
            "Z_PRTOUCH: object '%s' has no run_G28_Z() and no mcu_probe.run_G28_Z()"
            % (self.prtouch_object,)
        )

    def cmd_Z_PRTOUCH(self, gcmd):
        accurate = bool(gcmd.get_int("ACCURATE", 1, minval=0, maxval=1))
        offset = gcmd.get_float("OFFSET", self.default_offset)

        prtouch = self._lookup_creality_prtouch(gcmd)
        toolhead = self.printer.lookup_object("toolhead")

        # Match Creality command behaviour: make sure axes are considered ready.
        if hasattr(prtouch, "ck_g28ed"):
            prtouch.ck_g28ed()

        ok = prtouch.run_G28_Z(accurate)
        if not ok:
            raise gcmd.error("Z_PRTOUCH: Creality run_G28_Z failed")

        # run_G28_Z sets the Z zero internally and then leaves the toolhead raised.
        # Shift the current kinematic Z by -offset so positive OFFSET means farther from bed.
        pos = list(toolhead.get_position())
        current_z = float(pos[2])
        corrected_z = current_z - offset
        pos[2] = corrected_z
        toolhead.set_position(pos, homing_axes=[2])

        gcmd.respond_info(
            "Z_PRTOUCH: accurate=%d offset=%.4f current_z=%.4f corrected_z=%.4f"
            % (1 if accurate else 0, offset, current_z, corrected_z)
        )


def load_config(config):
    return PRTouchZWrapper(config)
