# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

import abc
import itertools

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_vmware import api
from oslo_vmware import exceptions as vexc
from oslo_vmware import vim
from oslo_vmware.vim_util import get_moref_value

import nova.conf

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class StableMoRefProxy(metaclass=abc.ABCMeta):
    """Abstract base class which acts as a proxy
    for Managed-Object-References (MoRef).
    Those references are usually "stable", meaning
    they don't change over the life-time of the object.
    But usually doesn't mean always. In that case, we
    need to fetch the reference again via some search method,
    which uses a guaranteed stable identifier (names, uuids, ...)
    """

    def __init__(self, ref):
        self.moref = ref

    @property
    def __class__(self):
        # Suds accesses the __class__.__name__ attribute
        # of the object to determine the xml-tag of the object
        # so we have to fake it
        return self.moref.__class__

    @abc.abstractmethod
    def fetch_moref(self, session):
        """Updates the moref field or raises
        same exception the initial search would have
        """

    def __getattr__(self, name):
        return getattr(self.moref, name)

    def __repr__(self):
        return "StableMoRefProxy({!r})".format(self.moref)


class MoRef(StableMoRefProxy):
    """MoRef takes a closure to resolve the reference of a managed object
    That closure is called again, in case we get a ManagedObjectNotFound
    exception on said reference.
    """

    def __init__(self, closure, ref=None):
        self._closure = closure
        ref = ref or self._closure()
        super().__init__(ref)

    def fetch_moref(self, _):
        self.moref = self._closure()

    def __repr__(self):
        return "MoRef({!r})".format(self.moref)


class VMwareAPISession(api.VMwareAPISession):
    """Sets up a session with the VC/ESX host and handles all
    the calls made to the host.
    """

    def __init__(self, host_ip=CONF.vmware.host_ip,
                 host_port=CONF.vmware.host_port,
                 username=CONF.vmware.host_username,
                 password=CONF.vmware.host_password,
                 retry_count=CONF.vmware.api_retry_count,
                 scheme="https",
                 cacert=CONF.vmware.ca_file,
                 insecure=CONF.vmware.insecure,
                 pool_size=CONF.vmware.connection_pool_size):
        super(VMwareAPISession, self).__init__(
                host=host_ip,
                port=host_port,
                server_username=username,
                server_password=password,
                api_retry_count=retry_count,
                task_poll_interval=CONF.vmware.task_poll_interval,
                scheme=scheme,
                create_session=True,
                cacert=cacert,
                insecure=insecure,
                pool_size=pool_size)

    @staticmethod
    def _is_vim_object(module):
        """Check if the module is a VIM Object instance."""
        return isinstance(module, vim.Vim)

    def _call_method(self, module, method, *args, **kwargs):
        """Calls a method within the module specified with
        args provided.
        """
        try:
            if not self._is_vim_object(module):
                return self.invoke_api(module, method, self.vim, *args,
                                       **kwargs)
            return self.invoke_api(module, method, *args, **kwargs)
        except vexc.ManagedObjectNotFoundException as monfe:
            with excutils.save_and_reraise_exception() as ctxt:
                moref = monfe.details.get("obj") if monfe.details else None
                for arg in itertools.chain(args, kwargs.values()):
                    if not isinstance(arg, StableMoRefProxy):
                        continue
                    moref_arg = get_moref_value(arg.moref)
                    if moref != moref_arg:
                        continue
                    # We have found the argument with the moref
                    # causing the exception and we can try to recover it
                    arg.fetch_moref(self)
                    if not arg.moref:
                        # We didn't recover the reference
                        ctxt.reraise = True
                        break
                    moref_arg = get_moref_value(arg.moref)
                    if moref != moref_arg:
                        # We actually recovered, so do not raise `monfe`
                        LOG.info("Replaced moref %s with %s",
                                 moref, moref_arg)
                        ctxt.reraise = False
        # We only end up here when we have recovered a moref by changing
        # the stored value of an argument to a different value,
        # so let's try again (and recover again if it happens more than once)
        return self._call_method(module, method, *args, **kwargs)

    def _wait_for_task(self, task_ref):
        """Return a Deferred that will give the result of the given task.
        The task is polled until it completes.
        """
        return self.wait_for_task(task_ref)
