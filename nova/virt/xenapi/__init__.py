# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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
:mod:`xenapi` -- Nova support for XenServer and XCP through XenAPI
==================================================================
"""


def load_sdk(flags):
    """
    This method is used for loading the XenAPI SDK (fake or real)
    """
    xenapi_module = \
        flags.xenapi_use_fake_session and 'nova.virt.xenapi.fake' or 'XenAPI'
    from_list = \
        flags.xenapi_use_fake_session and ['fake'] or []

    return __import__(xenapi_module, globals(), locals(), from_list, -1)


class HelperBase():
    """
    The class that wraps the helper methods together.
    """
    XenAPI = None

    def __init__(self):
        return

    @classmethod
    def late_import(cls, FLAGS):
        """
        Load XenAPI module in for helper class
        """
        if cls.XenAPI is None:
            cls.XenAPI = load_sdk(FLAGS)
