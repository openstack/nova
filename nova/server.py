# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Base functionality for nova daemons - gradually being replaced with twistd.py.
"""

import daemon
from daemon import pidlockfile
import logging
import logging.handlers
import os
import signal
import sys
import time

from nova import flags


FLAGS = flags.FLAGS
flags.DEFINE_bool('daemonize', False, 'daemonize this process')
# NOTE(termie): right now I am defaulting to using syslog when we daemonize
#               it may be better to do something else -shrug-
# NOTE(Devin): I think we should let each process have its own log file
#              and put it in /var/logs/nova/(appname).log
#              This makes debugging much easier and cuts down on sys log
#              clutter.
flags.DEFINE_bool('use_syslog', True, 'output to syslog when daemonizing')
flags.DEFINE_string('logfile', None, 'log file to output to')
flags.DEFINE_string('logdir',  None, 'directory to keep log files in '
                                     '(will be prepended to $logfile)')
flags.DEFINE_string('pidfile', None, 'pid file to output to')
flags.DEFINE_string('working_directory', './', 'working directory...')
flags.DEFINE_integer('uid', os.getuid(), 'uid under which to run')
flags.DEFINE_integer('gid', os.getgid(), 'gid under which to run')


def stop(pidfile):
    """
    Stop the daemon
    """
    # Get the pid from the pidfile
    try:
        pid = int(open(pidfile, 'r').read().strip())
    except IOError:
        message = "pidfile %s does not exist. Daemon not running?\n"
        sys.stderr.write(message % pidfile)
        return

    # Try killing the daemon process
    try:
        while 1:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.1)
    except OSError, err:
        err = str(err)
        if err.find("No such process") > 0:
            if os.path.exists(pidfile):
                os.remove(pidfile)
        else:
            print str(err)
            sys.exit(1)


def serve(name, main):
    """Controller for server"""
    argv = FLAGS(sys.argv)

    if not FLAGS.pidfile:
        FLAGS.pidfile = '%s.pid' % name

    logging.debug("Full set of FLAGS: \n\n\n")
    for flag in FLAGS:
        logging.debug("%s : %s", flag, FLAGS.get(flag, None))

    action = 'start'
    if len(argv) > 1:
        action = argv.pop()

    if action == 'stop':
        stop(FLAGS.pidfile)
        sys.exit()
    elif action == 'restart':
        stop(FLAGS.pidfile)
    elif action == 'start':
        pass
    else:
        print 'usage: %s [options] [start|stop|restart]' % argv[0]
        sys.exit(1)
    daemonize(argv, name, main)


def daemonize(args, name, main):
    """Does the work of daemonizing the process"""
    logging.getLogger('amqplib').setLevel(logging.WARN)
    files_to_keep = []
    if FLAGS.daemonize:
        logger = logging.getLogger()
        formatter = logging.Formatter(
                name + '(%(name)s): %(levelname)s %(message)s')
        if FLAGS.use_syslog and not FLAGS.logfile:
            syslog = logging.handlers.SysLogHandler(address='/dev/log')
            syslog.setFormatter(formatter)
            logger.addHandler(syslog)
            files_to_keep.append(syslog.socket)
        else:
            if not FLAGS.logfile:
                FLAGS.logfile = '%s.log' % name
            if FLAGS.logdir:
                FLAGS.logfile = os.path.join(FLAGS.logdir, FLAGS.logfile)
            logfile = logging.FileHandler(FLAGS.logfile)
            logfile.setFormatter(formatter)
            logger.addHandler(logfile)
            files_to_keep.append(logfile.stream)
        stdin, stdout, stderr = None, None, None
    else:
        stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr

    if FLAGS.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    with daemon.DaemonContext(
            detach_process=FLAGS.daemonize,
            working_directory=FLAGS.working_directory,
            pidfile=pidlockfile.TimeoutPIDLockFile(FLAGS.pidfile,
                                                   acquire_timeout=1,
                                                   threaded=False),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            uid=FLAGS.uid,
            gid=FLAGS.gid,
            files_preserve=files_to_keep):
        main(args)
