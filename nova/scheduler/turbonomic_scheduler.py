# Copyright (c) 2014 Rackspace Hosting
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
Turbonomic Scheduler implementation
--------------------------------
Our scheduler works as a replacement for the default filter_scheduler

For integrating this scheduler to get Placement recommendations,
the following entries must be added in the /etc/nova/nova.conf file
under the [scheduler] section
------------------------------------------------------------
scheduler_driver = nova.scheduler.turbonomic_scheduler.TurbonomicScheduler
turbonomic_address = <Turbonomic_Address>  - mandatory
turbonomic_target_address = <Turbonomic_Target_Address> - mandatory
turbonomic_username = <Turbonomic_UserName> - optional, defaults to administrator
turbonomic_password = <Turbonomic_Password> - optional, defaults to administrator
turbonomic_protocol = <Turbonomic_Protocol> - optional, defaults to https
turbonomic_timeout = <Turbonomic_Timeout> - optional, defaults to 60 seconds
turbonomic_verify_ssl = <Verify_ssl_certificate> - optional, defaults to False
------------------------------------------------------------
NOTE: 1) 'driver' might already be configured to the default scheduler
       Needs to be replaced if that's the case

      2) Add turbonomic_driver to <Python 2.7>/site-packages/nova-16.1.0-py2.7.egg-info/entry_points.txt:
      turbonomic_scheduler = nova.scheduler.turbonomic_scheduler:TurbonomicScheduler

      3) driver should be enabled across all regions.

      4) In order to force NOVA deploy a new VM on a specific host, run the following command:
        nova boot --flavor <FLAVOR_ID> --image <IMG_UUID> --nic net-id=<NIC_ID> --availability-zone <AVAILABILITY_ZONE>:<HOST_NAME> <VM_NAME>

      5) This script should be placed to /lib/python2.7/site-packages/nova/scheduler

      6) This script is designed for OpenStack Pike

    At the time of writing features 4 wwas unavailable in OpenStack UI and could be used only from CLI.

"""


from oslo_config import cfg
import nova.conf
from oslo_log import log as logging
from nova.scheduler import filters
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova import exception
import requests
from requests import exceptions
import json
import uuid

ext_opts = [
    cfg.StrOpt('turbonomic_protocol', default='https', deprecated_group='scheduler', help='turbonomic Server protocol, http or https'),
    cfg.StrOpt('turbonomic_address', default='default-address', deprecated_group='scheduler',  help='turbonomic Server address'),
    cfg.StrOpt('turbonomic_target_address', default='default-address', deprecated_group='scheduler', help='OSP target address'),
    cfg.StrOpt('turbonomic_timeout', default='60', deprecated_group='scheduler', help='turbonomic request timeout'),
    cfg.StrOpt('turbonomic_username', default='administrator', deprecated_group='scheduler', help='turbonomic Server Username'),
    cfg.StrOpt('turbonomic_password', default='administrator', deprecated_group='scheduler', help='turbonomic Server Password'),
    cfg.StrOpt('turbonomic_verify_ssl', default='False', deprecated_group='scheduler', help='Verify SSL certificate'),
]

CONF = nova.conf.CONF
CONF.register_opts(ext_opts)
LOG = logging.getLogger(__name__)

class TurbonomicScheduler(filter_scheduler.FilterScheduler):

    def __init__(self, *args, **kwargs):
        super(TurbonomicScheduler, self).__init__(*args, **kwargs)
        self.turbonomic_rest_endpoint = CONF.turbonomic_protocol + "://" + CONF.turbonomic_address + "/vmturbo/rest/"
        self.turbonomic_target_address = CONF.turbonomic_target_address
        self.auth = (CONF.turbonomic_username, CONF.turbonomic_password)
        self.turbonomic_timeout = int(CONF.turbonomic_timeout)
        self.verify_ssl = ('true' == CONF.turbonomic_verify_ssl)
        self.j_session_id = None
        self.region = None

        LOG.info('Initialized: TurbonomicRestApiEndpoint {}, TurbonomicTargetAddress: {}, Username: {}, Timeout: {}, VerifySSL: {}'.format(
            self.turbonomic_rest_endpoint, self.turbonomic_target_address, self.auth[0], self.turbonomic_timeout, self.verify_ssl))

    def select_destinations(self, context, spec_obj, instance_uuids, alloc_reqs_by_rp_uuid, provider_summaries):
        if 'default-address' in self.turbonomic_rest_endpoint:
            LOG.error('Turbonomic address not specified')
            raise exception.NoValidHost(reason='Turbonomic address not specified')

        if self.turbonomic_target_address == 'default-address':
            LOG.error('Turbonomic target address not specified')
            raise exception.NoValidHost(reason='Turbonomic target address not specified')

        selected_hosts = self.create_placement(context, spec_obj)
        LOG.info('SELECTED_HOSTS: {}'.format(str(selected_hosts)))

        if len(selected_hosts) == 0:
            raise exception.NoValidHost(reason='No suitable host found')

        try:
            host_info = self.host_manager.get_all_host_states(context)
        except all:
            host_info = []

        dests = []
        for selected_host in selected_hosts:
            LOG.info('Processing SELECTED_HOST: {}'.format(selected_host))
            for host_item in host_info:
                if selected_host.lower() == host_item.host.lower():
                    LOG.info('Found SELECTED_HOST: {}'.format(str(host_item)))
                    dests.append(host_item)
                    break

        LOG.info('Destinations: {}'.format(str( dests )))
        return dests

    def get_dc_uuid(self, availability_zone):
        LOG.info('Searching for DC: target: {}, AZ: {}'.format(self.turbonomic_target_address, availability_zone))
        try:
            entities_resp = requests.get(self.turbonomic_rest_endpoint + 'search?types=DataCenter',
                                     cookies={'JSESSIONID': self.j_session_id}, verify=self.verify_ssl, timeout = self.turbonomic_timeout)

            entities = entities_resp.json()
            for ent in entities:
                dc_uuid = ent.get('uuid', '')
                dc_uuid_parts = dc_uuid.split(':')
                if len(dc_uuid_parts) == 5 and 'OSS' == dc_uuid_parts[0] and 'DC' == dc_uuid_parts[3] and \
                                self.turbonomic_target_address == dc_uuid_parts[1] and availability_zone == dc_uuid_parts[4]:
                    self.region = dc_uuid_parts[2]
                    return dc_uuid

            raise exception.NoValidHost(reason='Region not found for target {}, AZ: {}'.format(self.turbonomic_target_address,
                                                                                               availability_zone))

        except exceptions.ReadTimeout:
            LOG.info('DC search request timed out: {}'.format(self.turbonomic_rest_endpoint + 'search?types=DataCenter'))
            raise exception.NoValidHost(reason='DC search request timed out')

    def get_template_uuid(self, template_name):
        full_template_name = '{}:{}::TMP-{}'.format(self.turbonomic_target_address, self.region, template_name)
        try:
            templates_response = requests.get(self.turbonomic_rest_endpoint + 'templates', cookies={'JSESSIONID': self.j_session_id},
                                          verify = self.verify_ssl, timeout = self.turbonomic_timeout)

            templates = json.loads(templates_response.content)
            for template in templates:
                temp_name = template.get('displayName', '')
                if full_template_name == temp_name:
                    return template.get('uuid', '')

            raise exception.NoValidHost(reason='No template found for {}'.format(full_template_name))

        except exceptions.ReadTimeout:
            LOG.info('Template request timed out: {}'.format(self.turbonomic_rest_endpoint + 'templates'))
            raise exception.NoValidHost(reason='Template request timed out')

    def create_placement(self, context, spec_obj):
        LOG.info('CTX: {}'.format(str(context)))
        LOG.info('spec_obj: {}'.format(str(spec_obj)))

        selected_hosts = []
        if spec_obj.force_hosts is not None and len(spec_obj.force_hosts) > 0 and spec_obj.force_hosts[0] is not None:
            for force_host in spec_obj.force_hosts:
                selected_hosts.append(force_host)

            LOG.info('force_host = {}'.format(str(selected_hosts)))
            return selected_hosts

        if 'id' in spec_obj.image:
            deploymentProfile = spec_obj.image.id
        else:
            deploymentProfile = ""
        vmCount = spec_obj.num_instances
        scheduler_hint = ''
        isSchedulerHintPresent = False
        if spec_obj.scheduler_hints is not None:
            if 'group' in spec_obj.scheduler_hints:
                scheduler_hint = spec_obj.scheduler_hints['group']
                if scheduler_hint is not None:
                    isSchedulerHintPresent = True
                else:
                    scheduler_hint = ''

        reservationName = "OpenStack-Placement-Request-" + str(uuid.uuid4())
        self.login()
        if self.j_session_id is None:
            raise exception.NoValidHost(reason='Error authenticating as {}'.format(self.auth[0]))

        if spec_obj.availability_zone is None:
            raise exception.NoValidHost(reason='Availability zone not set')

        if context.remote_address is None:
            raise exception.NoValidHost(reason='Remote address not set')

        dc_uuid = self.get_dc_uuid(spec_obj.availability_zone)

        template_uuid = self.get_template_uuid(context.remote_address)

        LOG.info('Creating placement {}, DeploymentProfile: {}, SchedulerHint: {}, Template: {}, DC: {}'.format(
            reservationName, deploymentProfile, str(scheduler_hint), template_uuid, dc_uuid))

        if isSchedulerHintPresent:
            constraints = ''
            for i in range(0, len(scheduler_hint)):
                constraints += '"' + scheduler_hint[i] + '"'
                if i < len(scheduler_hint) - 1:
                    constraints += ','

            placement = '{"demandName": "' + reservationName + '", "action": "PLACEMENT", "parameters": [ ' \
                                                               '{"placementParameters": {"count": ' + str(
                vmCount) + ', "templateID": "' + template_uuid + '", "constraintIDs":["' + dc_uuid + '"]},' \
                                                                                                     '"deploymentParameters": {"deploymentProfileID": "' + deploymentProfile + '", "constraintIDs":[' + constraints + ']  }}]}'
        else:
            placement = '{"demandName": "' + reservationName + '", "action": "PLACEMENT", "parameters": [ ' \
                                                               '{"placementParameters": {"count": ' + str(
                vmCount) + ', "templateID": "' + template_uuid + '", "constraintIDs":["' + dc_uuid + '"]},' \
                                                                                                     '"deploymentParameters": {"deploymentProfileID": "' + deploymentProfile + '"}}]}'

        LOG.info('Placement json: {}'.format(placement))

        try:
            placement_response = requests.post(self.turbonomic_rest_endpoint + 'reservations', data=placement,
                                               cookies={'JSESSIONID': self.j_session_id},
                                               headers={'content-type': 'application/json'},
                                               verify=self.verify_ssl, timeout=self.turbonomic_timeout)

            if placement_response.status_code == 200:
                placement = placement_response.json()
                LOG.info('Placement resp: {}'.format(str(placement_response)))
                LOG.info('Placement obj: {}'.format(str(placement)))
                if placement['status'] == 'PLACEMENT_SUCCEEDED':
                    if 'demandEntities' in placement:
                        demandEntities = placement['demandEntities']
                        for demandEntity in demandEntities:
                            if 'placements' in demandEntity:
                                placements = demandEntity['placements']
                                if 'computeResources' in placements:
                                    computeResources = placements['computeResources']
                                    for cr in computeResources:
                                        if 'provider' in cr:
                                            provider = cr['provider']
                                            if provider['className'] == 'PhysicalMachine':
                                                selected_hosts.append(provider['displayName'])
                                else:
                                    print('No compute resource found in placements')
                            else:
                                print('No placement found')
                        else:
                            print('No demand entities found')
                    else:
                        print('Placement failed: {}'.format(str(placement)))
                else:
                    LOG.info('Placement failed: {}'.format(str(placement)))
            else:
                resp = placement_response.json()
                LOG.info('Error creating placement: {}'.format(str(resp)))
                exception.NoValidHost(reason=resp['message'])

            return selected_hosts

        except exceptions.ReadTimeout:
            LOG.info('Placement request timed out {}'.format(self.turbonomic_rest_endpoint + 'reservations'))
            raise exception.NoValidHost(reason='Placement request timed out')

    def login(self):
        LOG.info('Logging in to {}'.format(self.turbonomic_rest_endpoint + 'login'))
        try:
            auth_response = requests.post(self.turbonomic_rest_endpoint + "login", {'username': self.auth[0], 'password': self.auth[1]},
                                      verify = self.verify_ssl, timeout = self.turbonomic_timeout)

            if auth_response.status_code == 200:
                self.j_session_id = auth_response.cookies['JSESSIONID']
                LOG.info('Authenticated as {}'.format(self.auth[0]))
            else:
                LOG.info('Error authenticating as {}'.format(self.auth[0]))
                raise exception.NoValidHost(reason='Error authenticating as {}'.format(self.auth[0]))

        except exceptions.ReadTimeout:
            LOG.info('Login request timed out: {}, username: {} '.format(self.turbonomic_rest_endpoint + "login",
                                                                                    self.auth[0]))
            raise exception.NoValidHost(reason='Login request timed out')