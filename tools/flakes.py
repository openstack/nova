"""
 wrapper for pyflakes to ignore gettext based warning:
     "undefined name '_'"

 From https://bugs.launchpad.net/pyflakes/+bug/844592
"""
import __builtin__
import os
import sys

from pyflakes.scripts.pyflakes import main

if __name__ == "__main__":
    names = os.environ.get('PYFLAKES_BUILTINS', '_')
    names = [x.strip() for x in names.split(',')]
    for x in names:
        if not hasattr(__builtin__, x):
            setattr(__builtin__, x, True)

    del names, os, __builtin__

    sys.exit(main())
