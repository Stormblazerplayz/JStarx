"""Command-line entry points for the JStarx system services."""
import json
import sys


def _print(res):
    print(json.dumps(res, indent=2, default=str))


def update():
    from . import updater
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    fn = {"check": updater.check, "apply": updater.apply, "rollback": updater.rollback, "auto": updater.auto}.get(cmd)
    if not fn:
        sys.exit("usage: jstarx-update check|apply|rollback|auto")
    res = fn(sys.argv[2]) if cmd == "apply" and len(sys.argv) > 2 else fn()
    _print(res)
    sys.exit(0 if res.get("state") != "error" else 1)


def repair():
    from . import repair as r
    cmd = sys.argv[1] if len(sys.argv) > 1 else "quick"
    fn = {"quick": r.quick, "deep": r.deep, "factory": r.factory, "shell-failed": r.shell_failed}.get(cmd)
    if not fn:
        sys.exit("usage: jstarx-repair quick|deep|factory|shell-failed")
    _print(fn())


def boot_ok():
    from . import boot
    _print(boot.mark_ok(sys.argv[1] if len(sys.argv) > 1 else "system up"))


def power():
    from . import power as p
    cmd = sys.argv[1] if len(sys.argv) > 1 else "get"
    if cmd == "restore":
        _print(p.restore())
    elif cmd in p.PROFILES:
        _print(p.set_profile(cmd))
    else:
        _print(p.get())


def starxd():
    from . import starxd as s
    s.main()


def starai():
    from . import starai as s
    s.main()


def spark_serve():
    from . import spark
    spark.serve()
