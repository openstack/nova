# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# Copyright 2019 Red Hat, Inc.
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

"""Enable eventlet monkey patching."""

import os


def _monkey_patch():
    # See https://bugs.launchpad.net/nova/+bug/1164822
    # TODO(mdbooth): This feature was deprecated and removed in eventlet at
    # some point but brought back in version 0.21.0, presumably because some
    # users still required it to work round issues. However, there have been a
    # number of greendns fixes in eventlet since then. Specifically, it looks
    # as though the originally reported IPv6 issue may have been fixed in
    # version 0.24.0. We should remove this when we can confirm that the
    # original issue is fixed.
    # NOTE(artom) eventlet processes environment variables at import-time. We
    # therefore set this here, before importing eventlet, in order to correctly
    # disable greendns.
    os.environ['EVENTLET_NO_GREENDNS'] = 'yes'

    # NOTE(mdbooth): Anything imported here will not be monkey patched. It is
    # important to take care not to import anything here which requires monkey
    # patching.
    import eventlet
    import sys

    # NOTE(mdbooth): Imports only sys (2019-01-30). Other modules imported at
    # runtime on execution of debugger.init().
    from nova import debugger

    # Note any modules with known monkey-patching issues which have been
    # imported before monkey patching.
    # urllib3: https://bugs.launchpad.net/nova/+bug/1808951
    # oslo_context.context: https://bugs.launchpad.net/nova/+bug/1773102
    problems = (set(['urllib3', 'oslo_context.context']) &
                set(sys.modules.keys()))

    if debugger.enabled():
        # turn off thread patching to enable the remote debugger
        eventlet.monkey_patch(thread=False)
    elif os.name == 'nt':
        # for nova-compute running on Windows(Hyper-v)
        # pipes don't support non-blocking I/O
        eventlet.monkey_patch(os=False)
    else:
        eventlet.monkey_patch()

    # Monkey patch the original current_thread to use the up-to-date _active
    # global variable. See https://bugs.launchpad.net/bugs/1863021 and
    # https://github.com/eventlet/eventlet/issues/592
    import __original_module_threading as orig_threading
    import threading
    orig_threading.current_thread.__globals__['_active'] = threading._active

    # NOTE(mdbooth): Log here instead of earlier to avoid loading oslo logging
    # before monkey patching.
    # NOTE(mdbooth): Ideally we would raise an exception here, as this is
    # likely to cause problems when executing nova code. However, some non-nova
    # tools load nova only to extract metadata and do not execute it. Two
    # examples are oslopolicy-policy-generator and sphinx, both of which can
    # fail if we assert here. It is not ideal that these utilities are monkey
    # patching at all, but we should not break them.
    # TODO(mdbooth): If there is any way to reliably determine if we are being
    # loaded in that kind of context without breaking existing callers, we
    # should do it and bypass monkey patching here entirely.
    if problems:
        from oslo_log import log as logging

        LOG = logging.getLogger(__name__)
        LOG.warning("Modules with known eventlet monkey patching issues were "
                    "imported prior to eventlet monkey patching: %s. This "
                    "warning can usually be ignored if the caller is only "
                    "importing and not executing nova code.",
                    ', '.join(problems))


# NOTE(mdbooth): This workaround is required to avoid breaking sphinx. See
# separate comment in doc/source/conf.py. It may also be useful for other
# non-nova utilities. Ideally the requirement for this workaround will be
# removed as soon as possible, so do not rely on, or extend it.
if (os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', '').lower()
        not in ('1', 'true', 'yes')):
    _monkey_patch()
