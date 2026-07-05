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
        self.gcode.register_command(
            "PRTOUCH_SCREWS_CALCULATE_RAW",
            self.cmd_PRTOUCH_SCREWS_CALCULATE_RAW,
            desc=self.cmd_PRTOUCH_SCREWS_CALCULATE_RAW_help)

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

    def _interpolate_result_z(self, samples, x, y):
        # Samples are [x, y, z] probe results. A normal mesh is a complete
        # rectangular grid, but adaptive mesh may add a separate zero-reference
        # point or otherwise produce a sparse/non-rectangular point set.
        x = float(x)
        y = float(y)

        pts = [
            (round(float(p[0]), 6), round(float(p[1]), 6), float(p[2]))
            for p in samples
        ]
        zmap = {(px, py): pz for px, py, pz in pts}

        # First: exact/near-exact reference point, common with adaptive meshes
        # that add zero_reference_position as an extra probed point.
        nearest = None
        for px, py, pz in pts:
            d2 = (px - x) * (px - x) + (py - y) * (py - y)
            if nearest is None or d2 < nearest[0]:
                nearest = (d2, px, py, pz)
            if abs(px - x) <= 0.01 and abs(py - y) <= 0.01:
                return pz

        xs = sorted(set(px for px, _py, _pz in pts))
        ys = sorted(set(py for _px, py, _pz in pts))

        def bracket(vals, v):
            if v <= vals[0]:
                return vals[0], vals[0], 0.0
            if v >= vals[-1]:
                return vals[-1], vals[-1], 0.0
            for i in range(len(vals) - 1):
                if vals[i] <= v <= vals[i + 1]:
                    lo = vals[i]
                    hi = vals[i + 1]
                    t = 0.0 if hi == lo else (v - lo) / (hi - lo)
                    return lo, hi, t
            raise ValueError("value %.6f is outside interpolation range" % (v,))

        # Second: bilinear interpolation, but only if the four grid corners
        # really exist. Adaptive meshes may not have all combinations.
        try:
            x0, x1, tx = bracket(xs, x)
            y0, y1, ty = bracket(ys, y)
            keys = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
            if all(k in zmap for k in keys):
                z00 = zmap[(x0, y0)]
                z10 = zmap[(x1, y0)]
                z01 = zmap[(x0, y1)]
                z11 = zmap[(x1, y1)]

                z0 = z00 + (z10 - z00) * tx
                z1 = z01 + (z11 - z01) * tx
                return z0 + (z1 - z0) * ty
        except Exception:
            pass

        # Third: sparse adaptive fallback. Use nearest reference-like point,
        # but only if it is close enough to be plausibly the extra zero-ref
        # sample. This avoids normalizing an object-corner mesh from a far point.
        if nearest is not None:
            d2, px, py, pz = nearest
            dist = d2 ** 0.5
            if dist <= 10.0:
                return pz

        raise ValueError(
            "no usable zero_ref sample/interpolation for (%.3f, %.3f)" % (x, y)
        )

    def _parse_screw_point_param(self, gcmd, key, name_key, default_name):
        raw = gcmd.get(key, None)
        if raw is None:
            return None

        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 2:
            raise gcmd.error("PRTouch screws: %s must be X,Y, got '%s'" % (key, raw))

        try:
            x = float(parts[0])
            y = float(parts[1])
        except Exception:
            raise gcmd.error("PRTouch screws: invalid coordinate in %s='%s'" % (key, raw))

        name = gcmd.get(name_key, default_name)
        return (name, x, y)

    cmd_PRTOUCH_SCREWS_CALCULATE_RAW_help = "Probe screw points using Creality PRTouch, not native Klipper probe"

    def cmd_PRTOUCH_SCREWS_CALCULATE_RAW(self, gcmd):
        bed_mesh = self.printer.lookup_object("bed_mesh")
        probe_obj, prtouch = self._lookup_prtouch()
        offsets = self._get_offsets(probe_obj)

        screw_points = []
        for idx in range(1, 10):
            pt = self._parse_screw_point_param(
                gcmd, "S%d" % (idx,), "N%d" % (idx,), "screw%d" % (idx,)
            )
            if pt is not None:
                screw_points.append(pt)

        if len(screw_points) < 3:
            raise gcmd.error("PRTouch screws: need at least S1/S2/S3 point parameters")

        # This command only reports three raw PRTouch measurements; it does
        # not run BedMeshCalibrate finalization, so do not depend on
        # bmc.probe_helper being present on this Klipper build.
        helper = getattr(getattr(bed_mesh, "bmc", None), "probe_helper", None)
        if helper is not None:
            helper.results = []
            helper.probe_offsets = offsets

        prtouch.ck_g28ed()
        prtouch.g29_cnt = 0
        prtouch.jump_probe_ready = False

        x_off, y_off, _z_off = offsets
        total = len(screw_points)
        raw_returns = []

        try:
            gcmd.respond_info(
                "PRTouch screws: probing %d configured screw points"
                % (total,)
            )

            for idx, (name, sx, sy) in enumerate(screw_points):
                gcmd.respond_info(
                    "PRTouch screws: point %d/%d %s x=%.2f y=%.2f"
                    % (idx + 1, total, name, sx, sy)
                )

                nextpos = [sx - x_off, sy - y_off, 0.0]
                prtouch.run_to_next(nextpos, True)
                res = prtouch.run_G29_Z()

                if res is False or not getattr(prtouch, "run_step_prtouch_flag", True):
                    raise gcmd.error(
                        "PRTouch screws: probing failed at point %d/%d %s"
                        % (idx + 1, total, name)
                    )

                raw = list(res[:3])
                raw_returns.append((name, sx, sy, raw[0], raw[1], raw[2]))
                if helper is not None:
                    helper.results.append(res[:3])

            ref_name, _sx, _sy, _px, _py, ref_z = raw_returns[0]
            avg_z = sum(r[5] for r in raw_returns) / float(len(raw_returns))
            min_z = min(r[5] for r in raw_returns)
            max_z = max(r[5] for r in raw_returns)

            gcmd.respond_info(
                "PRTouch screws: raw trigger Z values; higher means nozzle touched with bed effectively higher"
            )
            gcmd.respond_info(
                "PRTouch screws: reference=%s spread=%.5f avg=%.5f"
                % (ref_name, max_z - min_z, avg_z)
            )

            for name, sx, sy, px, py, pz in raw_returns:
                gcmd.respond_info(
                    "PRTouch screws: %-18s target=(%.2f,%.2f) probed=(%.2f,%.2f) "
                    "z=%.5f delta_ref=%+.5f delta_avg=%+.5f"
                    % (name, sx, sy, px, py, pz, pz - ref_z, pz - avg_z)
                )

        finally:
            prtouch.g29_cnt = 0
            if helper is not None:
                helper.results = []


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

        # MDF_DEBUG_PRTOUCH_MESH: keep raw return values separate from
        # helper.results, because Creality bed_mesh_post_proc may mutate
        # helper.results during the final point.
        raw_returns = []

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

                # MDF_DEBUG_PRTOUCH_MESH: copy raw returned probe position
                # before appending it to helper.results.
                raw_returns.append(list(res[:3]))

                # Mimic Klipper ProbeSessionHelper behaviour: append each
                # returned probed position. On the final point, Creality's
                # run_G29_Z() has already called bed_mesh_post_proc(), which
                # corrects helper.results and then returns the final point.
                helper.results.append(res[:3])

            # Creality run_G29_Z()/bed_mesh_post_proc mutates helper.results.
            # Feed Klipper BedMeshCalibrate with the raw probe returns instead,
            # otherwise the mesh gets Creality's internal correction applied
            # before Klipper zero_reference_position/finalization.
            results = [list(r) for r in raw_returns]
            if len(results) != total:
                raise gcmd.error(
                    "PRTouch mesh: invalid raw result count %d, expected %d"
                    % (len(results), total)
                )

            # MDF_DEBUG_PRTOUCH_MESH
            zero_ref = None
            try:
                zero_ref = bmc.probe_mgr.get_zero_ref_pos()
            except Exception as e:
                gcmd.respond_info("PRTouch mesh debug: get_zero_ref_pos failed: %s" % (e,))

            gcmd.respond_info("PRTouch mesh debug: zero_ref=%s" % (zero_ref,))

            # Klipper's zero_reference_position does not produce calc_z(ref)=0
            # with this PRTouch pipeline, because Creality's G29 flow and
            # BedMeshCalibrate finalization have different sign/reference
            # assumptions. Normalize the raw results explicitly before
            # probe_finalize(), so the reference point is already zero.
            if zero_ref is not None:
                try:
                    ref_z = self._interpolate_result_z(results, zero_ref[0], zero_ref[1])
                except Exception as e:
                    raise gcmd.error("PRTouch mesh: zero_ref interpolation failed: %s" % (e,))
                gcmd.respond_info(
                    "PRTouch mesh debug: pre-normalizing raw results at zero_ref z=%.6f"
                    % (ref_z,)
                )
                for r in results:
                    r[2] -= ref_z
            gcmd.respond_info("PRTouch mesh debug: raw returns before helper mutation/finalize:")
            for i, r in enumerate(raw_returns):
                gcmd.respond_info(
                    "PRTouch mesh debug raw %02d: x=%.6f y=%.6f z=%.6f"
                    % (i + 1, r[0], r[1], r[2])
                )

            gcmd.respond_info("PRTouch mesh debug: helper.results mutated by Creality before probe_finalize:")
            for i, r in enumerate(helper.results):
                gcmd.respond_info(
                    "PRTouch mesh debug helper %02d: x=%.6f y=%.6f z=%.6f"
                    % (i + 1, r[0], r[1], r[2])
                )

            gcmd.respond_info("PRTouch mesh debug: results passed to Klipper probe_finalize:")
            for i, r in enumerate(results):
                gcmd.respond_info(
                    "PRTouch mesh debug final %02d: x=%.6f y=%.6f z=%.6f"
                    % (i + 1, r[0], r[1], r[2])
                )

            bmc.probe_finalize(offsets, results)

            mesh = bed_mesh.get_mesh()
            if mesh is None:
                gcmd.respond_info("PRTouch mesh debug: active mesh after finalize is None")
            else:
                try:
                    cz = mesh.calc_z(153.0, 153.0)
                    zmin, zmax = mesh.get_z_range()
                    zavg = mesh.get_z_average()
                    gcmd.respond_info(
                        "PRTouch mesh debug: active mesh calc_z(153,153)=%.6f range=(%.6f, %.6f) avg=%.6f"
                        % (cz, zmin, zmax, zavg)
                    )
                except Exception as e:
                    gcmd.respond_info("PRTouch mesh debug: active mesh inspect failed: %s" % (e,))

            gcmd.respond_info("PRTouch mesh: complete")
        finally:
            prtouch.g29_cnt = 0
            helper.results = []


def load_config(config):
    return PRTouchMesh(config)
