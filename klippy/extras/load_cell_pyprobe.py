class LoadCellPyProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command(
            "LOAD_CELL_PYPROBE_DEV",
            self.cmd_LOAD_CELL_PYPROBE_DEV,
            desc="Development load cell probe"
        )

    def cmd_LOAD_CELL_PYPROBE_DEV(self, gcmd):
        path = "/usr/data/printer_data/config/load_cell_pyprobe_impl.py"

        env = {
            "printer": self.printer,
            "gcmd": gcmd,
        }

        try:
            with open(path, "r") as f:
                code = compile(f.read(), path, "exec")

            exec(code, env)

        except Exception as e:
            import traceback

            gcmd.respond_info("PYPROBE ERROR: %s" % (e,))
            gcmd.respond_info(traceback.format_exc())

def load_config(config):
    return LoadCellPyProbe(config)
