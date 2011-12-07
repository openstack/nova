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


class HelperBase(object):
    """
    The base for helper classes. This adds the XenAPI class attribute
    """
    XenAPI = None

    def __init__(self):
        return

    @classmethod
    def get_rec(cls, session, record_type, ref):
        try:
            return session.call_xenapi('%s.get_record' % record_type, ref)
        except cls.XenAPI.Failure, e:
            if e.details[0] != 'HANDLE_INVALID':
                raise

        return None

    @classmethod
    def get_all_refs_and_recs(cls, session, record_type):
        """Retrieve all refs and recs for a Xen record type.

        Handles race-conditions where the record may be deleted between
        the `get_all` call and the `get_record` call.
        """

        for ref in session.call_xenapi('%s.get_all' % record_type):
            rec = cls.get_rec(session, record_type, ref)
            # Check to make sure the record still exists. It may have
            # been deleted between the get_all call and get_record call
            if rec:
                yield ref, rec
