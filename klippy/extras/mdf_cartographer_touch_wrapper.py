# MDF Cartographer touch wrapper
#
# Run CARTOGRAPHER_TOUCH_HOME with camera stop/start protected by a real
# Python try/finally. If Cartographer touch fails, restart the camera anyway
# and then re-raise the original error so Klipper still reports the failure.

class MDFCartographerTouchWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.gcode.register_command(
            "MDF_CARTOGRAPHER_TOUCH_HOME",
            self.cmd_MDF_CARTOGRAPHER_TOUCH_HOME,
            desc=self.cmd_MDF_CARTOGRAPHER_TOUCH_HOME_help,
        )

    def _run(self, script):
        self.gcode.run_script_from_command(script)

    def _macro_var(self, macro_name, var_name, default=None):
        obj = self.printer.lookup_object("gcode_macro %s" % (macro_name,), None)
        if obj is None:
            return default
        variables = getattr(obj, "variables", {})
        return variables.get(var_name, default)

    def _as_bool(self, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() not in ("", "0", "false", "no", "off", "none")

    cmd_MDF_CARTOGRAPHER_TOUCH_HOME_help = (
        "Run CARTOGRAPHER_TOUCH_HOME and always restart camera on failure"
    )

    def cmd_MDF_CARTOGRAPHER_TOUCH_HOME(self, gcmd):
        stop_start_camera = gcmd.get_int("STOP_START_CAMERA", 1)
        camera_started = self._as_bool(self._macro_var("START_CAMERA", "started", True))

        camera_stopped = False
        touch_error = None
        restore_error = None

        if stop_start_camera and camera_started:
            self._run(
                "SET_GCODE_VARIABLE MACRO=_START_PRINT_TOUCH_STATE "
                "VARIABLE=camera_stopped VALUE=True"
            )
            self._run("STOP_CAMERA")
            camera_stopped = True

        try:
            self._run("CARTOGRAPHER_TOUCH_HOME")
        except Exception as e:
            touch_error = e
        finally:
            if camera_stopped:
                try:
                    self._run(
                        "SET_GCODE_VARIABLE MACRO=_START_PRINT_TOUCH_STATE "
                        "VARIABLE=camera_stopped VALUE=False"
                    )
                    self._run("START_CAMERA")
                except Exception as e:
                    restore_error = e
                    gcmd.respond_info(
                        "MDF_CARTOGRAPHER_TOUCH_HOME: camera restore failed: %s" % (e,)
                    )

        if touch_error is not None:
            raise touch_error
        if restore_error is not None:
            raise restore_error


def load_config(config):
    return MDFCartographerTouchWrapper(config)
