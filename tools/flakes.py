"""
 wrapper for pyflakes to ignore gettext based warning:
     "undefined name '_'"

 Synced in from openstack-common
"""
import sys

import pyflakes.checker
from pyflakes.scripts import pyflakes

if __name__ == "__main__":
    orig_builtins = set(pyflakes.checker._MAGIC_GLOBALS)
    pyflakes.checker._MAGIC_GLOBALS = orig_builtins | set(['_'])
    sys.exit(pyflakes.main())
