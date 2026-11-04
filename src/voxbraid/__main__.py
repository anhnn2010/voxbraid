"""Enable ``python -m voxbraid`` as well as the console command."""

from voxbraid.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
