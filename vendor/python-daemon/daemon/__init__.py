# -*- coding: utf-8 -*-

# daemon/__init__.py
# Part of python-daemon, an implementation of PEP 3143.
#
# Copyright © 2009–2010 Ben Finney <ben+python@benfinney.id.au>
# Copyright © 2006 Robert Niederreiter
#
# This is free software: you may copy, modify, and/or distribute this work
# under the terms of the Python Software Foundation License, version 2 or
# later as published by the Python Software Foundation.
# No warranty expressed or implied. See the file LICENSE.PSF-2 for details.

""" Library to implement a well-behaved Unix daemon process.

    This library implements the well-behaved daemon specification of
    :pep:`3143`, "Standard daemon process library".

    A well-behaved Unix daemon process is tricky to get right, but the
    required steps are much the same for every daemon program. A
    `DaemonContext` instance holds the behaviour and configured
    process environment for the program; use the instance as a context
    manager to enter a daemon state.

    Simple example of usage::

        import daemon

        from spam import do_main_program

        with daemon.DaemonContext():
            do_main_program()

    Customisation of the steps to become a daemon is available by
    setting options on the `DaemonContext` instance; see the
    documentation for that class for each option.

    """

import version
from daemon import DaemonContext


_version = version.version
_copyright = version.copyright
_license = version.license
_url = "http://pypi.python.org/pypi/python-daemon/"
