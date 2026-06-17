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
import sys

MONKEY_PATCHED = False


def _config_file_args(argv):
    """Return only --config-file and --config-dir args from argv.

    oslo_config only needs these to locate config files. Subcommand tokens
    (e.g. "api_db sync" for nova-manage) and test-runner arguments are unknown
    to a bare ConfigOpts instance and would cause argparse to call sys.exit(2).
    """
    result = []
    it = iter(argv)
    for arg in it:
        if arg in ('--config-file', '--config-dir'):
            result.append(arg)
            try:
                result.append(next(it))
            except StopIteration:
                pass
        elif (arg.startswith('--config-file=') or
              arg.startswith('--config-dir=')):
            result.append(arg)
    return result


def _get_concurrency_from_config():
    # NOTE(ksambor): We intentionally define the concurrency_backend option
    # inline here rather than importing it from nova.conf.base. This is a
    # narrow, early parse whose sole purpose is to read concurrency_backend
    # before any other imports occur, so that eventlet monkey patching can be
    # applied (or suppressed) at the very first opportunity. Importing
    # nova.conf.base would pull in oslo_service.opts which transitively imports
    # eventlet, defeating the purpose of this early-parse. The normal, full
    # config parsing (including the canonical option registration in
    # nova.conf.base) will happen later in the service startup process.
    from oslo_config import cfg

    concurrency_backend_opt = cfg.StrOpt(  # noqa: N342
        'concurrency_backend',
        default='auto',
        choices=['auto', 'threading', 'eventlet'],
    )
    conf = cfg.ConfigOpts()
    conf.register_opt(concurrency_backend_opt)
    conf(_config_file_args(sys.argv[1:]))
    return conf.concurrency_backend


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
    import eventlet  # noqa

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


def patch(backend='eventlet'):
    """Apply eventlet monkey patching according to environment.

    :param backend: Defines the default backend if not explicitly set via
        the environment. If 'eventlet', then monkey patch if environment
        variable is not defined. If 'threading', then do not monkey patch if
        environment variable is not defined. Any other value results in a
        ValueError. If the environment variable is defined this parameter
        is ignored.
    """
    if backend not in ('eventlet', 'threading'):
        raise ValueError(
            "the backend can only be 'eventlet' or 'threading'")

    env = os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', '').lower()
    if env == '':
        cfg_val = _get_concurrency_from_config()
        if cfg_val == 'threading':
            should_patch = False
        elif cfg_val == 'eventlet':
            should_patch = True
        else:
            # 'auto' or unrecognised: apply the per-binary deployment
            # default passed in via the ``backend`` parameter.
            should_patch = (backend == 'eventlet')
    elif env in ('1', 'true', 'yes'):
        should_patch = False
    else:
        should_patch = True

    if should_patch:
        if _monkey_patch():
            global MONKEY_PATCHED
            MONKEY_PATCHED = True

            import oslo_service.backend as service
            service.init_backend(service.BackendType.EVENTLET)
            from oslo_log import log as logging
            LOG = logging.getLogger(__name__)
            LOG.info("Service is starting with Eventlet based service backend")
            LOG.warning(
                "Eventlet based concurrency mode is deprecated and will be "
                "removed in a future release, not earlier than 2027.2. "
                "Please migrate to native threading mode. See the concurrency "
                "guide for details: "
                "https://docs.openstack.org/nova/latest/admin/concurrency"
                ".html")
    else:
        # NOTE(gibi): We were asked not to monkey patch. Let's enforce it by
        # removing the possibility to monkey_patch accidentally
        poison_eventlet()

        # We asked not to monkey patch so we will run in native threading mode
        import oslo_service.backend as service
        # NOTE(gibi): This will raise if the backend is already initialized
        # with Eventlet
        service.init_backend(service.BackendType.THREADING)

        from oslo_log import log as logging
        LOG = logging.getLogger(__name__)
        LOG.info("Service is starting with native threading.")


def poison_eventlet():
    if 'eventlet' in sys.modules:
        # We are too late, something imported eventlet already. Give up.
        raise RuntimeError(
            "The service is started with native threading via "
            "OS_NOVA_DISABLE_EVENTLET_PATCHING set to '%s', but eventlet "
            "library imported early preventing the service to forbid that "
            "import. This is a bug."
            % os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', ''))

    class PoisonEventletImport:
        def find_spec(self, fullname, path, target=None):
            if fullname.startswith('eventlet'):
                raise ImportError(
                    "The service started in native threading mode so it "
                    "should not import eventlet")

    sys.meta_path.insert(0, PoisonEventletImport())
