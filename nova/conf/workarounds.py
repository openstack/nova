# Copyright 2016 OpenStack Foundation
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

""" The workarounds_opts group is for very specific reasons.

If you're:

 - Working around an issue in a system tool (e.g. libvirt or qemu) where the
   fix is in flight/discussed in that community.
 - The tool can be/is fixed in some distributions and rather than patch the
   code those distributions can trivially set a config option to get the
   "correct" behavior.

Then this is a good place for your workaround.

.. warning::

  Please use with care! Document the BugID that your workaround is paired with.
"""

from oslo_config import cfg

disable_rootwrap = cfg.BoolOpt(
    'disable_rootwrap',
    default=False,
    help='This option allows a fallback to sudo for performance '
         'reasons. For example see '
         'https://bugs.launchpad.net/nova/+bug/1415106')

disable_libvirt_livesnapshot = cfg.BoolOpt(
    'disable_libvirt_livesnapshot',
    default=True,
    help='When using libvirt 1.2.2 live snapshots fail '
         'intermittently under load.  This config option provides '
         'a mechanism to enable live snapshot while this is '
                     'resolved.  See '
                     'https://bugs.launchpad.net/nova/+bug/1334398')

handle_virt_lifecycle_events = cfg.BoolOpt(
    'handle_virt_lifecycle_events',
    default=True,
    help="Whether or not to handle events raised from the compute "
         "driver's 'emit_event' method. These are lifecycle "
         "events raised from compute drivers that implement the "
         "method. An example of a lifecycle event is an instance "
         "starting or stopping. If the instance is going through "
         "task state changes due to an API operation, like "
         "resize, the events are ignored. However, this is an "
         "advanced feature which allows the hypervisor to signal "
         "to the compute service that an unexpected state change "
         "has occurred in an instance and the instance can be "
         "shutdown automatically - which can inherently race in "
         "reboot operations or when the compute service or host "
         "is rebooted, either planned or due to an unexpected "
         "outage. Care should be taken when using this and "
         "sync_power_state_interval is negative since then if any "
         "instances are out of sync between the hypervisor and "
         "the Nova database they will have to be synchronized "
         "manually. See https://bugs.launchpad.net/bugs/1444630")

ALL_OPTS = [disable_rootwrap,
            disable_libvirt_livesnapshot,
            handle_virt_lifecycle_events]


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group='workarounds')


def list_opts():
    return {'workarounds': ALL_OPTS}
