import time
import traceback
import mcu
import chelper

def mdf_mcu_command(kind, command, response=None, use_oid=False):
    def deco(func):
        func._mdf_mcu = {
            "kind": kind,
            "command": command,
            "response": response,
            "use_oid": use_oid,
            "handle": None,
        }
        return func
    return deco


class MDFLive:
    def __init__(self, tools):
        self.tools = tools
        self.printer = tools.printer
        self.gcode = tools.gcode
        self.mcu = self.printer.lookup_object("mcu leveling_mcu")
        self._trigger_dispatch = None
        
        self.mcu.register_response(
            self._handle_mdf_trigger,
            "mdf_trigger")

        self._register_commands()

    def _iter_commands(self):
        for attr in sorted(dir(self)):
            if attr.startswith("cmd_MDF_"):
                yield attr[4:], getattr(self, attr)

    def _unregister_commands(self):
        for name, _func in self._iter_commands():
            self.gcode.register_command(name, None)

    def _get_probe_oid(self):
        probe = self.printer.lookup_object("mdf_loadcell_probe_real")
        mcu_probe = probe.get_mcu_load_cell_probe()
        return mcu_probe.get_oid()

    def _get_mcu_handle(self, meta):
        if meta["handle"] is not None:
            return meta["handle"]

        kwargs = {}
        if meta["use_oid"]:
            kwargs["oid"] = self._get_probe_oid()

        if meta["kind"] == "query":
            meta["handle"] = self.mcu.lookup_query_command(
                meta["command"],
                meta["response"],
                **kwargs
            )
        elif meta["kind"] == "command":
            meta["handle"] = self.mcu.lookup_command(
                meta["command"]
            )
        else:
            raise Exception("Unknown MDF MCU command kind: %s" % meta["kind"])

        return meta["handle"]

    def _safe_command(self, name, func):
        def wrapper(gcmd):
            try:
                meta = getattr(func, "_mdf_mcu", None)
                if meta is None:
                    return func(gcmd)

                mcu_cmd = self._get_mcu_handle(meta)
                return func(gcmd, mcu_cmd)

            except Exception:
                gcmd.respond_info(
                    "%s failed, Klipper kept alive:\n%s"
                    % (name, traceback.format_exc())
                )
        return wrapper

    def _register_commands(self):
        self._unregister_commands()
        for name, func in self._iter_commands():
            self.gcode.register_command(
                name,
                self._safe_command(name, func)
            )

    def unload(self):
        self._unregister_commands()

    def _handle_mdf_trigger(self, params):
        reasons = {
            1: "DF",
            2: "SAFE",
        }

        reason = reasons.get(params["reason"], str(params["reason"]))

        self.gcode.respond_info(
            "MDF TRIGGER reason=%s raw=%d df=%d d0=%d"
            % (
                reason,
                params["raw"],
                params["df"],
                params["d0"],
            )
        )

    @mdf_mcu_command(
        "query",
        "mdf_ping",
        "mdf_pong value=%u"
    )
    def cmd_MDF_PING(self, gcmd, mcu_cmd):
        params = mcu_cmd.send([])
        gcmd.respond_info("MDF MCU pong value=%d" % params["value"])

    @mdf_mcu_command(
        "query",
        "mdf_force_query oid=%c",
        "mdf_force_state oid=%c raw=%i",
        use_oid=True
    )
    def cmd_MDF_FORCE(self, gcmd, mcu_cmd):
        oid = self._get_probe_oid()
        params = mcu_cmd.send([oid])
        raw = params["raw"]
        gcmd.respond_info("MDF raw oid=%d raw=%d" % (params["oid"], raw))

    @mdf_mcu_command(
        "command",
        "mdf_config oid=%c sample_ticks=%u df_threshold=%i safe_threshold=%i"
    )
    def cmd_MDF_CONFIG(self, gcmd, mcu_cmd):
        oid = self._get_probe_oid()

        dz = gcmd.get_float("DZ", 0.02)
        speed = gcmd.get_float("SPEED", 0.5)
        df = gcmd.get_int("DF", 1000)
        safe = gcmd.get_int("SAFE", 5000)

        dt = dz / speed
        sample_ticks = int(dt * 72000000)

        mcu_cmd.send([oid, sample_ticks, df, safe])

        gcmd.respond_info(
            "MDF configured: dz=%.4f speed=%.4f dt=%.4f ticks=%d df=%d safe=%d"
            % (dz, speed, dt, sample_ticks, df, safe)
        )

    @mdf_mcu_command(
        "command",
        "mdf_start"
    )
    def cmd_MDF_START(self, gcmd, mcu_cmd):
        mcu_cmd.send([])
        gcmd.respond_info("MDF started")

    @mdf_mcu_command(
        "command",
        "mdf_stop"
    )
    def cmd_MDF_STOP(self, gcmd, mcu_cmd):
        mcu_cmd.send([])
        gcmd.respond_info("MDF stopped")

    @mdf_mcu_command(
        "query",
        "mdf_status_query",
        "mdf_status active=%c triggered=%c reason=%c raw0=%i raw=%i df=%i d0=%i"
    )
    def cmd_MDF_STATUS(self, gcmd, mcu_cmd):
        params = mcu_cmd.send([])

        reasons = {
            0: "NONE",
            1: "DF",
            2: "SAFE",
        }

        gcmd.respond_info(
            "MDF status active=%d triggered=%d reason=%s raw0=%d raw=%d df=%d d0=%d"
            % (
                params["active"],
                params["triggered"],
                reasons.get(params["reason"], str(params["reason"])),
                params["raw0"],
                params["raw"],
                params["df"],
                params["d0"],
            )
        )

    def cmd_MDF_RAW_LOOP(self, gcmd):
        count = gcmd.get_int("COUNT", 50)
        delay = gcmd.get_float("DELAY", 0.05)

        oid = self._get_probe_oid()
        meta = self.cmd_MDF_FORCE._mdf_mcu
        mcu_cmd = self._get_mcu_handle(meta)

        last_raw = None
        for i in range(count):
            params = mcu_cmd.send([oid])
            raw = params["raw"]
            delta = 0 if last_raw is None else raw - last_raw
            last_raw = raw

            gcmd.respond_info(
                "i=%03d raw=%d d_raw=%d" % (i, raw, delta)
            )

            time.sleep(delay)

    def cmd_MDF_DF_TEST(self, gcmd):
        count = gcmd.get_int("COUNT", 500)
        dz = gcmd.get_float("DZ", 0.02)
        speed = gcmd.get_float("SPEED", 0.5)
        df_threshold = gcmd.get_int("DF_THRESHOLD", 1000)
        safe_threshold = gcmd.get_int("SAFE_THRESHOLD", 5000)

        oid = self._get_probe_oid()
        meta = self.cmd_MDF_FORCE._mdf_mcu
        mcu_cmd = self._get_mcu_handle(meta)

        delay = dz / speed
        raw0 = None
        last_raw = None

        gcmd.respond_info(
            "MDF_DF_TEST dz=%.3f speed=%.3f dt=%.3f df=%d safe=%d"
            % (dz, speed, delay, df_threshold, safe_threshold)
        )

        for i in range(count):
            params = mcu_cmd.send([oid])
            raw = params["raw"]

            if raw0 is None:
                raw0 = raw

            if last_raw is not None:
                df = raw - last_raw
                d0 = raw - raw0
                df_hit = abs(df) >= df_threshold
                safe_hit = abs(d0) >= safe_threshold

                if df_hit or safe_hit:
                    gcmd.respond_info(
                        "i=%03d raw=%d df=%d d0=%d hit=%s"
                        % (
                            i,
                            raw,
                            df,
                            d0,
                            "DF" if df_hit else "SAFE"
                        )
                    )

            last_raw = raw
            time.sleep(delay)


def load(tools):
    return MDFLive(tools)
