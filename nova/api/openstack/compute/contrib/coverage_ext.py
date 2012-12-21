# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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
#    under the License

# See: http://wiki.openstack.org/Nova/CoverageExtension for more information
# and usage explanation for this API extension

import os
import re
import sys
import telnetlib
import tempfile

from coverage import coverage
from webob import exc

from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova import db
from nova.network import api as network_api
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'coverage_ext')


class CoverageController(object):
    """The Coverage report API controller for the OpenStack API"""
    def __init__(self):
        self.data_path = tempfile.mkdtemp(prefix='nova-coverage_')
        data_out = os.path.join(self.data_path, '.nova-coverage')
        self.coverInst = coverage(data_file=data_out)
        self.compute_api = compute_api.API()
        self.network_api = network_api.API()
        self.services = []
        self.combine = False
        super(CoverageController, self).__init__()

    def _find_services(self, req):
        """Returns a list of services"""
        context = req.environ['nova.context']
        services = db.service_get_all(context, False)
        hosts = []
        for serv in services:
            hosts.append({"service": serv["topic"], "host": serv["host"]})
        return hosts

    def _find_ports(self, req, hosts):
        """Return a list of backdoor ports for all services in the list"""
        context = req.environ['nova.context']

        apicommands = {
            "compute": self.compute_api.get_backdoor_port,
            "network": self.network_api.get_backdoor_port,
        }
        ports = []
        temp = {}
        #TODO(mtreinish): Figure out how to bind the backdoor socket to 0.0.0.0
        # Currently this will only work if the host is resolved as loopback on
        # the same host as api-server
        for host in hosts:
            if host['service'] in apicommands:
                get_port_fn = apicommands[host['service']]
                _host = host
                _host['port'] = get_port_fn(context, host['host'])
                #NOTE(mtreinish): if the port is None then it wasn't set in
                # the configuration file for this service. However, that
                # doesn't necessarily mean that we don't have backdoor ports
                # for all the services. So, skip the telnet connection for
                # this service.
                if _host['port']:
                    ports.append(_host)
                else:
                    LOG.warning(_("Can't connect to service: %s, no port"
                                  "specified\n"), host['service'])
            else:
                LOG.debug(_("No backdoor API command for service: %s\n"), host)
        return ports

    def _start_coverage_telnet(self, tn, service):
        tn.write('import sys\n')
        tn.write('from coverage import coverage\n')
        if self.combine:
            data_file = os.path.join(self.data_path,
                                    '.nova-coverage.%s' % str(service))
            tn.write("coverInst = coverage(data_file='%s')\n)" % data_file)
        else:
            tn.write('coverInst = coverage()\n')
        tn.write('coverInst.skipModules = sys.modules.keys()\n')
        tn.write("coverInst.start()\n")
        tn.write("print 'finished'\n")
        tn.expect([re.compile('finished')])

    def _start_coverage(self, req, body):
        '''Begin recording coverage information.'''
        LOG.debug("Coverage begin")
        body = body['start']
        self.combine = False
        if 'combine' in body.keys():
            self.combine = bool(body['combine'])
        self.coverInst.skipModules = sys.modules.keys()
        self.coverInst.start()
        hosts = self._find_services(req)
        ports = self._find_ports(req, hosts)
        self.services = []
        for service in ports:
            service['telnet'] = telnetlib.Telnet(service['host'],
                                                 service['port'])
            self.services.append(service)
            self._start_coverage_telnet(service['telnet'], service['service'])

    def _stop_coverage_telnet(self, tn):
        tn.write("coverInst.stop()\n")
        tn.write("coverInst.save()\n")
        tn.write("print 'finished'\n")
        tn.expect([re.compile('finished')])

    def _check_coverage(self):
        try:
            self.coverInst.stop()
            self.coverInst.save()
        except AssertionError:
            return True
        return False

    def _stop_coverage(self, req):
        for service in self.services:
            self._stop_coverage_telnet(service['telnet'])
        if self._check_coverage():
            msg = ("Coverage not running")
            raise exc.HTTPNotFound(explanation=msg)

    def _report_coverage_telnet(self, tn, path, xml=False):
        if xml:
            execute = str("coverInst.xml_report(outfile='%s')\n" % path)
            tn.write(execute)
            tn.write("print 'finished'\n")
            tn.expect([re.compile('finished')])
        else:
            execute = str("output = open('%s', 'w')\n" % path)
            tn.write(execute)
            tn.write("coverInst.report(file=output)\n")
            tn.write("output.close()\n")
            tn.write("print 'finished'\n")
            tn.expect([re.compile('finished')])
        tn.close()

    def _report_coverage(self, req, body):
        self._stop_coverage(req)
        xml = False
        path = None

        body = body['report']
        if 'file' in body.keys():
            path = body['file']
            if path != os.path.basename(path):
                msg = ("Invalid path")
                raise exc.HTTPBadRequest(explanation=msg)
            path = os.path.join(self.data_path, path)
        else:
            msg = ("No path given for report file")
            raise exc.HTTPBadRequest(explanation=msg)

        if 'xml' in body.keys():
            xml = body['xml']

        if self.combine:
            self.coverInst.combine()
            if xml:
                self.coverInst.xml_report(outfile=path)
            else:
                output = open(path, 'w')
                self.coverInst.report(file=output)
                output.close()
            for service in self.services:
                service['telnet'].close()
        else:
            if xml:
                apipath = path + '.api'
                self.coverInst.xml_report(outfile=apipath)
                for service in self.services:
                    self._report_coverage_telnet(service['telnet'],
                                              path + '.%s'
                                              % service['service'],
                                              xml=True)
            else:
                output = open(path + '.api', 'w')
                self.coverInst.report(file=output)
                for service in self.services:
                    self._report_coverage_telnet(service['telnet'],
                                            path + '.%s' % service['service'])
                output.close()
        return {'path': path}

    def action(self, req, body):
        _actions = {
                'start': self._start_coverage,
                'stop': self._stop_coverage,
                'report': self._report_coverage,
        }
        authorize(req.environ['nova.context'])
        for action, data in body.iteritems():
            if action == 'stop':
                return _actions[action](req)
            elif action == 'report' or action == 'start':
                return _actions[action](req, body)
            else:
                msg = _("Coverage doesn't have %s action") % action
                raise exc.HTTPBadRequest(explanation=msg)
        raise exc.HTTPBadRequest(explanation=_("Invalid request body"))


class Coverage_ext(extensions.ExtensionDescriptor):
    """Enable Nova Coverage"""

    name = "Coverage"
    alias = "os-coverage"
    namespace = ("http://docs.openstack.org/compute/ext/"
                  "coverage/api/v2")
    updated = "2012-10-15T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('os-coverage',
                                        controller=CoverageController(),
                                        collection_actions={"action": "POST"})
        resources.append(res)
        return resources
