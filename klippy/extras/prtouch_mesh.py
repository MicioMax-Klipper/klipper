# PRTouch full bed mesh calibration helper.
#
# This module intentionally lives outside Creality's prtouch_v2_wrapper.py.
# It reuses the Creality probing pipeline (run_to_next/run_G29_Z/bed_mesh_post_proc)
# and feeds the results back into Klipper's BedMeshCalibrate finalizer.

import logging


class PRTouchMesh:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.prtouch_object = config.get("prtouch_object", "prtouch")
        self.gcode = self.printer.lookup_object("gcode")
        self.gcode.register_command(
            "PRTOUCH_MESH_CALIBRATE",
            self.cmd_PRTOUCH_MESH_CALIBRATE,
            desc=self.cmd_PRTOUCH_MESH_CALIBRATE_help,
        )

    def _lookup_prtouch(self):
        probe_obj = self.printer.lookup_object(self.prtouch_object)
        # [prtouch_v2 prtouch] registers a probe.PrinterProbe object.
        # The real Creality wrapper is its mcu_probe member.
        prtouch = getattr(probe_obj, "mcu_probe", probe_obj)
        return probe_obj, prtouch

    def _get_offsets(self, probe_obj):
        if hasattr(probe_obj, "get_offsets"):
            return probe_obj.get_offsets()
        return (0.0, 0.0, 0.0)

    cmd_PRTOUCH_MESH_CALIBRATE_help = "Calibrate full bed mesh using Creality PRTouch pipeline"

    def cmd_PRTOUCH_MESH_CALIBRATE(self, gcmd):
        bed_mesh = self.printer.lookup_object("bed_mesh")
        bmc = bed_mesh.bmc
        probe_obj, prtouch = self._lookup_prtouch()
        offsets = self._get_offsets(probe_obj)

        # Creality's bed_mesh_post_proc expects this legacy shortcut.
        if not hasattr(bmc, "probe_helper"):
            bmc.probe_helper = bmc.probe_mgr.probe_helper

        profile_name = gcmd.get("PROFILE", "default")
        if not profile_name.strip():
            raise gcmd.error("Value for parameter 'PROFILE' must be specified")

        gcmd.respond_info(
            "PRTouch mesh: profile=%s probe_object=%s offsets=(%.3f, %.3f, %.3f)"
            % (profile_name, self.prtouch_object, offsets[0], offsets[1], offsets[2])
        )

        # Match BedMeshCalibrate.cmd_BED_MESH_CALIBRATE setup.
        bmc._profile_name = profile_name
        bed_mesh.set_mesh(None)
        try:
            bmc.update_config(gcmd)
        except Exception as e:
            raise gcmd.error(str(e))

        points = list(bmc.probe_mgr.get_std_path())
        if not points:
            raise gcmd.error("PRTouch mesh: no generated probe points")

        helper = bmc.probe_helper
        helper.results = []
        helper.probe_offsets = offsets

        prtouch.ck_g28ed()
        prtouch.g29_cnt = 0
        prtouch.jump_probe_ready = False

        x_off, y_off, _z_off = offsets
        total = len(points)

        gcmd.respond_info("PRTouch mesh: probing %d points" % total)

        try:
            for idx, pt in enumerate(points):
                # BedMesh points are probe points. Move the toolhead to the
                # corresponding nozzle/tool position, respecting XY offsets.
                nextpos = [pt[0] - x_off, pt[1] - y_off, 0.0]
                gcmd.respond_info(
                    "PRTouch mesh: point %d/%d x=%.2f y=%.2f"
                    % (idx + 1, total, nextpos[0], nextpos[1])
                )

                prtouch.run_to_next(nextpos, True)
                res = prtouch.run_G29_Z()
                if res is False or not getattr(prtouch, "run_step_prtouch_flag", True):
                    raise gcmd.error("PRTouch mesh: probing failed at point %d/%d" % (idx + 1, total))

                # Mimic Klipper ProbeSessionHelper behaviour: append each
                # returned probed position. On the final point, Creality's
                # run_G29_Z() has already called bed_mesh_post_proc(), which
                # corrects helper.results and then returns the final point.
                helper.results.append(res[:3])

            results = list(helper.results)
            if len(results) != total:
                raise gcmd.error(
                    "PRTouch mesh: invalid result count %d, expected %d"
                    % (len(results), total)
                )

            bmc.probe_finalize(offsets, results)
            gcmd.respond_info("PRTouch mesh: complete")
        finally:
            prtouch.g29_cnt = 0
            helper.results = []


def load_config(config):
    return PRTouchMesh(config)
