# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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

"""Setup privsep decorator."""

from oslo_privsep import priv_context

# NOTE(tonyb): DAC == Discriminatory Access Control.  Basically this context
#              can bypass permissions checks in the file-system.
dac_admin_pctxt = priv_context.PrivContext(
    'nova',
    cfg_section='nova_privileged',
    pypath=__name__ + '.dac_admin_pctxt',
    # NOTE(tonyb): These map to CAP_CHOWN, CAP_DAC_OVERRIDE,
    #              CAP_DAC_READ_SEARCH  and CAP_FOWNER.  Some do not have
    #              symbolic names in oslo.privsep yet.  See capabilites(7)
    #              for more information
    capabilities=[0, 1, 2, 3],
)
