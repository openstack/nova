# Copyright (c) 2011 Citrix Systems, Inc.
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

"""This modules stubs out functions in oslo_concurrency.processutils."""

import re

from oslo_concurrency import processutils
from oslo_log import log as logging

from nova import utils

LOG = logging.getLogger(__name__)

_fake_execute_repliers = []
_fake_execute_log = []


def fake_execute_get_log():
    return _fake_execute_log


def fake_execute_clear_log():
    global _fake_execute_log
    _fake_execute_log = []


def fake_execute_set_repliers(repliers):
    """Allows the client to configure replies to commands."""
    global _fake_execute_repliers
    _fake_execute_repliers = repliers


def fake_execute_default_reply_handler(*ignore_args, **ignore_kwargs):
    """A reply handler for commands that haven't been added to the reply list.

    Returns empty strings for stdout and stderr.

    """
    return '', ''


def fake_execute(*cmd_parts, **kwargs):
    """This function stubs out execute.

    It optionally executes a preconfigured function to return expected data.

    """
    global _fake_execute_repliers

    process_input = kwargs.get('process_input', None)
    check_exit_code = kwargs.get('check_exit_code', 0)
    delay_on_retry = kwargs.get('delay_on_retry', True)
    attempts = kwargs.get('attempts', 1)
    run_as_root = kwargs.get('run_as_root', False)
    cmd_str = ' '.join(str(part) for part in cmd_parts)

    LOG.debug("Faking execution of cmd (subprocess): %s", cmd_str)
    _fake_execute_log.append(cmd_str)

    reply_handler = fake_execute_default_reply_handler

    for fake_replier in _fake_execute_repliers:
        if re.match(fake_replier[0], cmd_str):
            reply_handler = fake_replier[1]
            LOG.debug('Faked command matched %s', fake_replier[0])
            break

    if isinstance(reply_handler, str):
        # If the reply handler is a string, return it as stdout
        reply = reply_handler, ''
    else:
        try:
            # Alternative is a function, so call it
            reply = reply_handler(cmd_parts,
                                  process_input=process_input,
                                  delay_on_retry=delay_on_retry,
                                  attempts=attempts,
                                  run_as_root=run_as_root,
                                  check_exit_code=check_exit_code)
        except processutils.ProcessExecutionError as e:
            LOG.debug('Faked command raised an exception %s', e)
            raise

    LOG.debug("Reply to faked command is stdout='%(stdout)s' "
        "stderr='%(stderr)s'", {'stdout': reply[0], 'stderr': reply[1]})

    # Replicate the sleep call in the real function
    utils.cooperative_yield()
    return reply


def stub_out_processutils_execute(test):
    fake_execute_set_repliers([])
    fake_execute_clear_log()
    test.stub_out('oslo_concurrency.processutils.execute', fake_execute)
