"""
 wrapper for pyflakes to ignore gettext based warning:
     "undefined name '_'"

 Synced in from openstack-common
"""

__all__ = ['main']

import __builtin__ as builtins
import sys

import pyflakes.api
from pyflakes import checker


def main():
    checker.Checker.builtIns = (set(dir(builtins)) |
                                set(['_']) |
                                set(checker._MAGIC_GLOBALS))
    sys.exit(pyflakes.api.main())

if __name__ == "__main__":
    main()
