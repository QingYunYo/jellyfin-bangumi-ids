"""Allow `python3 -m jellyfin_bangumi_ids <command>` from a checkout."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
