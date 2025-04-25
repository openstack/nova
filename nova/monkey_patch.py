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

MONKEY_PATCHED = False


def is_patched():
    return MONKEY_PATCHED


def _monkey_patch():
    if is_patched():
        return
    # NOTE(mdbooth): Anything imported here will not be monkey patched. It is
    # important to take care not to import anything here which requires monkey
    # patching.
    # NOTE(artom) eventlet processes environment variables at import-time.
    # as such any eventlet configuration should happen here if needed.
    import eventlet
    import sys

    # Note any modules with known monkey-patching issues which have been
    # imported before monkey patching.
    # urllib3: https://bugs.launchpad.net/nova/+bug/1808951
    # oslo_context.context: https://bugs.launchpad.net/nova/+bug/1773102
    problems = (set(['urllib3', 'oslo_context.context']) &
                set(sys.modules.keys()))

    eventlet.monkey_patch()

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


def patch():
    # NOTE(mdbooth): This workaround is required to avoid breaking sphinx. See
    # separate comment in doc/source/conf.py. It may also be useful for other
    # non-nova utilities. Ideally the requirement for this workaround will be
    # removed as soon as possible, so do not rely on, or extend it.
    if (os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', '').lower()
        not in ('1', 'true', 'yes')):
        _monkey_patch()
        global MONKEY_PATCHED
        MONKEY_PATCHED = True
