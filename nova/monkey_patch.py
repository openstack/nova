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
        return False

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

    return True


def patch():
    if (os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', '').lower()
        not in ('1', 'true', 'yes')):

        if _monkey_patch():
            global MONKEY_PATCHED
            MONKEY_PATCHED = True

            import oslo_service.backend as service
            service.init_backend(service.BackendType.EVENTLET)
            from oslo_log import log as logging
            LOG = logging.getLogger(__name__)
            LOG.info("Service is starting with Eventlet based service backend")
    else:
        # We asked not to monkey patch so we will run in native threading mode
        import oslo_service.backend as service
        # NOTE(gibi): This will raise if the backend is already initialized
        # with Eventlet
        service.init_backend(service.BackendType.THREADING)

        # NOTE(gibi): We were asked not to monkey patch. Let's enforce it by
        # removing the possibility to monkey_patch accidentally
        def poison(*args, **kwargs):
            raise RuntimeError(
                "The service is started with native threading via "
                "OS_NOVA_DISABLE_EVENTLET_PATCHING set to '%s', but then the "
                "service tried to call eventlet.monkey_patch(). This is a "
                "bug."
                % os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', ''))

        import eventlet
        eventlet.monkey_patch = poison
        eventlet.patcher.monkey_patch = poison

        from oslo_log import log as logging
        LOG = logging.getLogger(__name__)
        LOG.warning(
            "Service is starting with native threading. This is currently "
            "experimental. Do not use it in production.")
