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
Helper methods for operations related to the management of volumes,
and storage repositories
"""

import logging

from twisted.internet import defer

from nova import utils


class VolumeHelper():
    def __init__(self, session):
        return

    @classmethod
    @utils.deferredToThread
    def create_iscsi_storage(self, session, target, port, target_iqn,
                             username, password, label, description):

        return VolumeHelper.create_iscsi_storage_blocking(session, target,
                                                          port,
                                                          target_iqn,
                                                          username,
                                                          password,
                                                          label,
                                                          description)

    @classmethod
    def create_iscsi_storage_blocking(self, session, target, port, target_iqn,
                                      username, password, label, description):

        sr_ref = session.get_xenapi().SR.get_by_name_label(label)
        if len(sr_ref) == 0:
            logging.debug('Introducing %s...' % label)
            try:
                sr_ref = session.get_xenapi().SR.create(
                    session.get_xenapi_host(),
                    {'target': target,
                     'port': port,
                     'targetIQN': target_iqn
                     # TODO: when/if chap authentication is used
                     #'chapuser': username,
                     #'chappassword': password
                     },
                    '0', label, description, 'iscsi', '', False, {})
                logging.debug('Introduced %s as %s.' % (label, sr_ref))
                return sr_ref
            except Exception, exc:
                logging.warn(exc)
                raise Exception('Unable to create Storage Repository')
        else:
            return sr_ref[0]

    @classmethod
    @defer.inlineCallbacks
    def find_sr_from_vbd(self, session, vbd_ref):
        vdi_ref = yield session.get_xenapi().VBD.get_VDI(vbd_ref)
        sr_ref = yield session.get_xenapi().VDI.get_SR(vdi_ref)
        defer.returnValue(sr_ref)

    @classmethod
    @utils.deferredToThread
    def destroy_iscsi_storage(self, session, sr_ref):
        VolumeHelper.destroy_iscsi_storage_blocking(session, sr_ref)

    @classmethod
    def destroy_iscsi_storage_blocking(self, session, sr_ref):
        logging.debug("Forgetting SR %s ... ", sr_ref)
        pbds = []
        try:
            pbds = session.get_xenapi().SR.get_PBDs(sr_ref)
        except Exception, exc:
            logging.warn('Ignoring exception %s when getting PBDs for %s',
                         exc, sr_ref)
        for pbd in pbds:
            try:
                session.get_xenapi().PBD.unplug(pbd)
            except Exception, exc:
                logging.warn('Ignoring exception %s when unplugging PBD %s',
                             exc, pbd)
        try:
            session.get_xenapi().SR.forget(sr_ref)
            logging.debug("Forgetting SR %s done.", sr_ref)
        except Exception, exc:
            logging.warn('Ignoring exception %s when forgetting SR %s',
                         exc, sr_ref)

    @classmethod
    @utils.deferredToThread
    def introduce_vdi(self, session, sr_ref):
        return VolumeHelper.introduce_vdi_blocking(session, sr_ref)

    @classmethod
    def introduce_vdi_blocking(self, session, sr_ref):
        try:
            vdis = session.get_xenapi().SR.get_VDIs(sr_ref)
        except Exception, exc:
            raise Exception('Unable to introduce VDI on SR %s' % sr_ref)
        try:
            vdi_rec = session.get_xenapi().VDI.get_record(vdis[0])
        except Exception, exc:
            raise Exception('Unable to get record of VDI %s on' % vdis[0])
        else:
            return session.get_xenapi().VDI.introduce(
                vdi_rec['uuid'],
                vdi_rec['name_label'],
                vdi_rec['name_description'],
                vdi_rec['SR'],
                vdi_rec['type'],
                vdi_rec['sharable'],
                vdi_rec['read_only'],
                vdi_rec['other_config'],
                vdi_rec['location'],
                vdi_rec['xenstore_data'],
                vdi_rec['sm_config'])
