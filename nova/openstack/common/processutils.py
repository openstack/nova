# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation
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
System-level utilities and helper functions.
"""

import logging
import random
import shlex

from eventlet.green import subprocess
from eventlet import greenthread

from nova.openstack.common.gettextutils import _


LOG = logging.getLogger(__name__)


class UnknownArgumentError(Exception):
    def __init__(self, message=None):
        super(UnknownArgumentError, self).__init__(message)


class ProcessExecutionError(Exception):
    def __init__(self, stdout=None, stderr=None, exit_code=None, cmd=None,
                 description=None):
        if description is None:
            description = "Unexpected error while running command."
        if exit_code is None:
            exit_code = '-'
        message = ("%s\nCommand: %s\nExit code: %s\nStdout: %r\nStderr: %r"
                   % (description, cmd, exit_code, stdout, stderr))
        super(ProcessExecutionError, self).__init__(message)


def execute(*cmd, **kwargs):
    """
    Helper method to shell out and execute a command through subprocess with
    optional retry.

    :param cmd:             Passed to subprocess.Popen.
    :type cmd:              string
    :param process_input:   Send to opened process.
    :type proces_input:     string
    :param check_exit_code: Defaults to 0. Will raise
                            :class:`ProcessExecutionError`
                            if the command exits without returning this value
                            as a returncode
    :type check_exit_code:  int
    :param delay_on_retry:  True | False. Defaults to True. If set to True,
                            wait a short amount of time before retrying.
    :type delay_on_retry:   boolean
    :param attempts:        How many times to retry cmd.
    :type attempts:         int
    :param run_as_root:     True | False. Defaults to False. If set to True,
                            the command is prefixed by the command specified
                            in the root_helper kwarg.
    :type run_as_root:      boolean
    :param root_helper:     command to prefix all cmd's with
    :type root_helper:      string
    :returns:               (stdout, stderr) from process execution
    :raises:                :class:`UnknownArgumentError` on
                            receiving unknown arguments
    :raises:                :class:`ProcessExecutionError`
    """

    process_input = kwargs.pop('process_input', None)
    check_exit_code = kwargs.pop('check_exit_code', 0)
    delay_on_retry = kwargs.pop('delay_on_retry', True)
    attempts = kwargs.pop('attempts', 1)
    run_as_root = kwargs.pop('run_as_root', False)
    root_helper = kwargs.pop('root_helper', '')
    if len(kwargs):
        raise UnknownArgumentError(_('Got unknown keyword args '
                                     'to utils.execute: %r') % kwargs)
    if run_as_root:
        cmd = shlex.split(root_helper) + list(cmd)
    cmd = map(str, cmd)

    while attempts > 0:
        attempts -= 1
        try:
            LOG.debug(_('Running cmd (subprocess): %s'), ' '.join(cmd))
            _PIPE = subprocess.PIPE  # pylint: disable=E1101
            obj = subprocess.Popen(cmd,
                                   stdin=_PIPE,
                                   stdout=_PIPE,
                                   stderr=_PIPE,
                                   close_fds=True)
            result = None
            if process_input is not None:
                result = obj.communicate(process_input)
            else:
                result = obj.communicate()
            obj.stdin.close()  # pylint: disable=E1101
            _returncode = obj.returncode  # pylint: disable=E1101
            if _returncode:
                LOG.debug(_('Result was %s') % _returncode)
                if (isinstance(check_exit_code, int) and
                    not isinstance(check_exit_code, bool) and
                        _returncode != check_exit_code):
                    (stdout, stderr) = result
                    raise ProcessExecutionError(exit_code=_returncode,
                                                stdout=stdout,
                                                stderr=stderr,
                                                cmd=' '.join(cmd))
            return result
        except ProcessExecutionError:
            if not attempts:
                raise
            else:
                LOG.debug(_('%r failed. Retrying.'), cmd)
                if delay_on_retry:
                    greenthread.sleep(random.randint(20, 200) / 100.0)
        finally:
            # NOTE(termie): this appears to be necessary to let the subprocess
            #               call clean something up in between calls, without
            #               it two execute calls in a row hangs the second one
            greenthread.sleep(0)
