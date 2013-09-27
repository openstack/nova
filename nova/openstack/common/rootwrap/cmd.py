# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Root wrapper for OpenStack services

   Filters which commands a service is allowed to run as another user.

   To use this with nova, you should set the following in
   nova.conf:
   rootwrap_config=/etc/nova/rootwrap.conf

   You also need to let the nova user run nova-rootwrap
   as root in sudoers:
   nova ALL = (root) NOPASSWD: /usr/bin/nova-rootwrap
                                   /etc/nova/rootwrap.conf *

   Service packaging should deploy .filters files only on nodes where
   they are needed, to avoid allowing more than is necessary.
"""

from __future__ import print_function

import ConfigParser
import logging
import os
import pwd
import signal
import subprocess
import sys


RC_UNAUTHORIZED = 99
RC_NOCOMMAND = 98
RC_BADCONFIG = 97
RC_NOEXECFOUND = 96


def _subprocess_setup():
    # Python installs a SIGPIPE handler by default. This is usually not what
    # non-Python subprocesses expect.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def _exit_error(execname, message, errorcode, log=True):
    print("%s: %s" % (execname, message), file=sys.stderr)
    if log:
        logging.error(message)
    sys.exit(errorcode)


def _getlogin():
    try:
        return os.getlogin()
    except OSError:
        return (os.getenv('USER') or
                os.getenv('USERNAME') or
                os.getenv('LOGNAME'))


def main():
    # Split arguments, require at least a command
    execname = sys.argv.pop(0)
    if len(sys.argv) < 2:
        _exit_error(execname, "No command specified", RC_NOCOMMAND, log=False)

    configfile = sys.argv.pop(0)
    userargs = sys.argv[:]

    # Add ../ to sys.path to allow running from branch
    possible_topdir = os.path.normpath(os.path.join(os.path.abspath(execname),
                                                    os.pardir, os.pardir))
    if os.path.exists(os.path.join(possible_topdir, "nova", "__init__.py")):
        sys.path.insert(0, possible_topdir)

    from nova.openstack.common.rootwrap import wrapper

    # Load configuration
    try:
        rawconfig = ConfigParser.RawConfigParser()
        rawconfig.read(configfile)
        config = wrapper.RootwrapConfig(rawconfig)
    except ValueError as exc:
        msg = "Incorrect value in %s: %s" % (configfile, exc.message)
        _exit_error(execname, msg, RC_BADCONFIG, log=False)
    except ConfigParser.Error:
        _exit_error(execname, "Incorrect configuration file: %s" % configfile,
                    RC_BADCONFIG, log=False)

    if config.use_syslog:
        wrapper.setup_syslog(execname,
                             config.syslog_log_facility,
                             config.syslog_log_level)

    # Execute command if it matches any of the loaded filters
    filters = wrapper.load_filters(config.filters_path)
    try:
        filtermatch = wrapper.match_filter(filters, userargs,
                                           exec_dirs=config.exec_dirs)
        if filtermatch:
            command = filtermatch.get_command(userargs,
                                              exec_dirs=config.exec_dirs)
            if config.use_syslog:
                logging.info("(%s > %s) Executing %s (filter match = %s)" % (
                    _getlogin(), pwd.getpwuid(os.getuid())[0],
                    command, filtermatch.name))

            obj = subprocess.Popen(command,
                                   stdin=sys.stdin,
                                   stdout=sys.stdout,
                                   stderr=sys.stderr,
                                   preexec_fn=_subprocess_setup,
                                   env=filtermatch.get_environment(userargs))
            obj.wait()
            sys.exit(obj.returncode)

    except wrapper.FilterMatchNotExecutable as exc:
        msg = ("Executable not found: %s (filter match = %s)"
               % (exc.match.exec_path, exc.match.name))
        _exit_error(execname, msg, RC_NOEXECFOUND, log=config.use_syslog)

    except wrapper.NoFilterMatched:
        msg = ("Unauthorized command: %s (no filter matched)"
               % ' '.join(userargs))
        _exit_error(execname, msg, RC_UNAUTHORIZED, log=config.use_syslog)
