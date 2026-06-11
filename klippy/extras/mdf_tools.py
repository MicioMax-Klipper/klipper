import importlib.util
import traceback

LIVE_PATH = "/usr/data/printer_data/config/mdf_tools_live.py"

class MDFTools:

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")

        self.live = None

        self.gcode.register_command(
            "MDF_RELOAD",
            self.cmd_MDF_RELOAD,
            desc="Reload MDF live tools"
        )

        self._initial_load_live()

    def _load_live_module(self):
        spec = importlib.util.spec_from_file_location(
            "mdf_tools_live",
            LIVE_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _initial_load_live(self):
        try:
            mod = self._load_live_module()
            self.live = mod.load(self)
        except Exception:
            print(
                "MDF initial live load failed:\n%s"
                % traceback.format_exc()
            )
            
    def cmd_MDF_RELOAD(self, gcmd):
        old_live = self.live

        try:
            mod = self._load_live_module()
            new_live = mod.load(self)
        except Exception:
            gcmd.respond_info(
                "MDF_RELOAD failed, keeping previous live module:\n%s"
                % traceback.format_exc()
            )
            return

        self.live = new_live

        if old_live is not None and hasattr(old_live, "unload"):
            try:
                old_live.unload()
            except Exception:
                gcmd.respond_info(
                    "MDF old live unload failed, ignored:\n%s"
                    % traceback.format_exc()
                )

        # Important: old_live.unload() may unregister shared commands.
        # Re-register new live commands after unloading old live.
        if hasattr(new_live, "_register_commands"):
            new_live._register_commands()

        gcmd.respond_info("MDF live tools reloaded")


def load_config(config):
    return MDFTools(config)
