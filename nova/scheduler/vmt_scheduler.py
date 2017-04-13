# Copyright (c) 2014 OpenStack Foundation
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

"""
VMTurbo Scheduler implementation
--------------------------------
Our scheduler works as a replacement for the default filter_scheduler

For integrating this scheduler to get Placement recommendations,
the following entries must be added in the /etc/nova/nova.conf file
under the [DEFAULT] section
------------------------------------------------------------
scheduler_driver = nova.scheduler.vmt_scheduler.VMTScheduler
vmturbo_rest_uri = <VMTurbo_IPAddress>
vmturbo_username = <VMTurbo_UserName>
vmturbo_password = <VMTurbo_Password>
------------------------------------------------------------
NOTE: 'scheduler_driver' might already be configured to the default scheduler
       Needs to be replaced if thats the case
"""

import random

from oslo_config import cfg
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.i18n import _
from nova import rpc
from nova.scheduler import driver
from nova.scheduler import scheduler_options


""" Imports for calls to VMTurbo """
import requests
import datetime
import time

import sys

ext_opts = [
    cfg.StrOpt('vmturbo_rest_uri',
                    default='URI',
                    help='VMTurbo Server URL'),
    cfg.StrOpt('vmturbo_username',
                    default='VMT_USER',
                    help='VMTurbo Server Username'),
    cfg.StrOpt('vmturbo_password',
                    default='VMT_PWD',
                    help='VMTurbo Server Username'),
]
CONF = nova.conf.CONF
CONF.register_opts(ext_opts)
LOG = logging.getLogger(__name__)

class VMTScheduler(driver.Scheduler):
    """
    Implements Scheduler as a node selector based on
    VMTurbo's placement recommendations.
    """

    def __init__(self, *args, **kwargs):
        super(VMTScheduler, self).__init__(*args, **kwargs)
        self.vmt_url = 'http://' + CONF.vmturbo_rest_uri + "/vmturbo/api"
        self.auth = (CONF.vmturbo_username, CONF.vmturbo_password)
        self.selected_hosts = []
        self.placementFailed = False
        self.notifier = rpc.get_notifier('scheduler')

    def _schedule(self, context, spec_obj):
        """Create and run an instance or instances."""
        self.placementFailed = False
        self.reservationName = "Reservation"
        self.vmPrefix = "VMTReservation"#"From Response - Create Something"
        self.flavor_name = spec_obj.flavor.name
        self.deploymentProfile = spec_obj.image.id
        self.vmCount = spec_obj.num_instances#"From response"
        self.scheduler_hint = ''
        self.isSchedulerHintPresent = False
        self.forceHost = ''
        spec_obj.scheduler_hints
        if spec_obj.scheduler_hints is not None:
            if 'group' in spec_obj.scheduler_hints:
                self.scheduler_hint = spec_obj.scheduler_hints['group']
                if self.scheduler_hint is not None:
                    self.isSchedulerHintPresent = True
                else:
                    self.scheduler_hint = ''
            else:
                LOG.info('group not found in spec_obj.scheduler_hints')
        else:
            LOG.info('scheduler_hints not present')
        self.forceHost = spec_obj.force_hosts or []
        LOG.info(self.reservationName + " : " + self.vmPrefix + " : " + self.flavor_name + " : " + str(self.deploymentProfile)
        + " : " + str(self.vmCount) + " : " + self.vmt_url + " : " + self.auth[0] + " : " + self.auth[1] + " : " + str(self.scheduler_hint))
        self.selected_hosts[:] = []
        if not self.forceHost:
            try:
		self.templateName = self.getTemplateFromUuid(self.flavor_name, self.deploymentProfile)
		LOG.info("Retrieved template Name " + self.templateName)
		reservationUuid = self.requestPlacement(self.isSchedulerHintPresent)
                if "ERROR" != reservationUuid and "" != reservationUuid and reservationUuid is not None:
                    LOG.info("Template UUID " + self.templateName + " : Reservation UUID " + reservationUuid)
                    self.pollForStatus(context, reservationUuid)
                    self.deletePlacement(reservationUuid)
            except:
                e = sys.exc_info()[0]
                type, value, tb = sys.exc_info()
                LOG.info('ERROR when getting responses from VMTurbo ')
                LOG.info(value.message)
            LOG.info('Hosts fetched from VMTurbo')
            LOG.info(self.selected_hosts)

    def select_destinations(self, context, spec_obj):
        self.notifier.info(
            context, 'vmt_scheduler.select_destinations.start',
            dict(request_spec=spec_obj.to_legacy_request_spec_dict()))
        LOG.info("select_destinations overridden in VMTScheduler")
        self.schedule = False
        num_instances = spec_obj.num_instances
        self._schedule(context, spec_obj)
        if self.placementFailed:
            reason = _('There are not enough resources available.')
            raise exception.NoValidHost(reason=reason)
        dests = [dict(host=host.get('host'), nodename=host.get('nodename'),
                      limits=host.get('limits')) for host in self.selected_hosts]   
	self.notifier.info(
            context, 'scheduler.select_destinations.end',
            dict(request_spec=spec_obj.to_legacy_request_spec_dict()))
        return dests 

    """ VMTurbo Specific calls """
    """ These calls need to be made more generic so that other """
    """ external systems can be used for scheduling tasks """

    def requestPlacement(self, isSchedulerHintPresent):
        LOG.info("Creating reservation: " + self.reservationName + ". "
                       + "vmPrefix: " + self.vmPrefix + ". "
                       + "templateName: " + self.templateName + ". "
                       + "deploymentProfile: " + self.deploymentProfile + ". "
                       + "count: " + str(self.vmCount) + ". ")
        requests_data_dict = dict()
        requests_data_dict.update({ "vmPrefix" : self.vmPrefix })
        requests_data_dict.update({ "reservationName" : self.reservationName })
        requests_data_dict.update({ "templateName" : self.templateName })
        requests_data_dict.update({ "count" : str(self.vmCount) })
        requests_data_dict.update({ "deploymentProfile" : self.deploymentProfile })
        if isSchedulerHintPresent:
            requests_data_dict.update({ "segmentationUuid[]" : self.scheduler_hint })
        reservation_uuid = self.apiPost("/reservations", requests_data_dict)
        if reservation_uuid[0] == "":
            LOG.info("Reservation was not generated due to a possible misconfiguration.")
        return reservation_uuid[0]

    def getPlacementStatus(self, reservation_uuid):
        LOG.debug("Getting status for reservation: " + reservation_uuid)
        all_reservations_xml = self.apiGet("/reservations")
        for xml_line in all_reservations_xml:
            if self.parseField("uuid", xml_line) == reservation_uuid:
                status = self.parseField("status", xml_line)
                break
        else:
            LOG.info("Reservation was not found by uuid in all reservations xml.")
            status = ""
        return status

    def getTemplateFromUuid(self, flavor_name, service_uuid):
        LOG.info("VMTurbo:: Getting template uuid for serviceUuid: " + service_uuid)
        all_templates_xml = self.apiGet("/templates")
        LOG.info(all_templates_xml)
	for xml_line in all_templates_xml:
            if ((self.parseField("displayName", xml_line).endswith("::TMP-" + flavor_name))):
                if service_uuid is None:
                    templateUuid = self.parseField("uuid", xml_line)
                    tempDeploy = self.parseField("services", xml_line)
                    self.deploymentProfile = tempDeploy[0:36]
                    break
                else:
                    if service_uuid in self.parseField("services", xml_line):
                        templateUuid = self.parseField("uuid", xml_line)
                        break
        else:
            LOG.info("Reservation was not found by uuid in all reservations xml.")
            templateUuid = ""
        return templateUuid

    def pollForStatus(self, context, reservationUuid):
        statusRes = self.getPlacementStatus(reservationUuid)
        count = 0
        """ Setting the timeout to 5 mintues """
        while (statusRes == "LOADING" or statusRes == "UNFULFILLED"):
            ++count
            statusRes = self.getPlacementStatus(reservationUuid)
            time.sleep(2)
            if (count > 150):
                break
        if (statusRes == "PLACEMENT_SUCCEEDED"):
            LOG.info("Placement with uuid " + reservationUuid + " succeeded")
            self.populateResourceList(context, reservationUuid)
        elif (statusRes == "PLACEMENT_FAILED"):
            LOG.warn("Placement with uuid " + reservationUuid + " failed to be placed")
            self.selected_hosts = []
            self.placementFailed = True 
        else:
            LOG.warn("Placement with uuid " + reservationUuid + " could not be placed")
            self.selected_hosts = []

    def deletePlacement(self, reservation_uuid):
        LOG.info("Deleting reservation." + reservation_uuid)
        response = self.apiDelete("/reservations/" + reservation_uuid)
        time.sleep(10)
        if response[0] == "true":
            LOG.debug("Delete Response returned true")
        else:
            LOG.debug("Delete Response returned false")
        return

    def populateResourceList(self, context, reservation_uuid):
        LOG.debug("Parsing Reservation response")
        reservation_xml = self.apiGet("/reservations/" + reservation_uuid)
        for xml_line in reservation_xml:
            if "name" in xml_line:
                host = self.parseField("host", xml_line)
		elevated = context.elevated()
		host_info = self.host_manager.get_all_host_states(context)
		node = host
		for host_item in host_info:
		    hostname = host_item.host
		    nodename = host_item.nodename
		    if host == hostname:
			node = nodename
			break
                vmt_host = {"host" : host, "nodename" : node, "limits" : {}}
                self.selected_hosts.append(vmt_host)

    def parseField(self, xml_field, xml_line):
        xml_field += "=\""
        fieldLength = len(xml_field)
        fieldLocation = xml_line.find(xml_field) + fieldLength
        if fieldLocation != -1 + fieldLength:
            return xml_line[fieldLocation:fieldLocation + xml_line[fieldLocation:].find("\"")]
        else:
            return ""

    def getXmlFromResponse(self, response_from_api_call):
        return filter(None, response_from_api_call.split("\n"))

    def apiGet(self, getUrl):
        fullUrl = self.vmt_url + getUrl
        response = requests.get(fullUrl, auth=self.auth)
        return self.getXmlFromResponse(response.content)

    def apiDelete(self, deleteUrl):
        fullUrl = self.vmt_url + deleteUrl
        response = requests.delete(fullUrl, auth=self.auth)
        return self.getXmlFromResponse(response.content)

    def apiPost(self, postUrl, requests_data_dict):
        fullUrl = self.vmt_url + postUrl
        response = requests.post( fullUrl , data=requests_data_dict , auth=self.auth)
        return self.getXmlFromResponse(response.content)
