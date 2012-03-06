# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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
Tests for NetApp volume driver

"""

import BaseHTTPServer
import httplib
import StringIO

from lxml import etree

from nova import log as logging
from nova import test
from nova.volume import netapp

LOG = logging.getLogger("nova.volume.driver")


WSDL_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"
    xmlns:na="http://www.netapp.com/management/v1"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema" name="NetAppDfm"
    targetNamespace="http://www.netapp.com/management/v1">"""

WSDL_TYPES = """<types>
<xsd:schema attributeFormDefault="unqualified" elementFormDefault="qualified"
    targetNamespace="http://www.netapp.com/management/v1">
<xsd:element name="ApiProxy">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Request" type="na:Request"/>
            <xsd:element name="Target" type="xsd:string"/>
            <xsd:element minOccurs="0" name="Timeout" type="xsd:integer"/>
            <xsd:element minOccurs="0" name="Username" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="ApiProxyResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Response" type="na:Response"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditBegin">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetNameOrId" type="na:ObjNameOrId"/>
            <xsd:element minOccurs="0" name="Force" type="xsd:boolean"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditBeginResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditCommit">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="AssumeConfirmation"
                type="xsd:boolean"/>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditCommitResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="IsProvisioningFailure"
                type="xsd:boolean"/>
            <xsd:element minOccurs="0" name="JobIds" type="na:ArrayOfJobInfo"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditRollback">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditRollbackResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Datasets" type="na:ArrayOfDatasetInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ObjectNameOrId"
                type="na:ObjNameOrId"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetMembers"
                type="na:ArrayOfDatasetMemberInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetNameOrId" type="na:ObjNameOrId"/>
            <xsd:element minOccurs="0" name="IncludeExportsInfo"
                type="xsd:boolean"/>
            <xsd:element minOccurs="0" name="IncludeIndirect"
                type="xsd:boolean"/>
            <xsd:element minOccurs="0" name="MemberType" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetProvisionMember">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="EditLockId" type="xsd:integer"/>
            <xsd:element name="ProvisionMemberRequestInfo"
                type="na:ProvisionMemberRequestInfo"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetProvisionMemberResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetRemoveMember">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetMemberParameters"
                type="na:ArrayOfDatasetMemberParameter"/>
            <xsd:element minOccurs="0" name="Destroy" type="xsd:boolean"/>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetRemoveMemberResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="ProgressEvents"
                type="na:ArrayOfDpJobProgressEventInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="JobId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DfmAbout">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="IncludeDirectorySizeInfo"
                type="xsd:boolean"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DfmAboutResult">
    <xsd:complexType>
        <xsd:all/>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="HostListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Hosts" type="na:ArrayOfHostInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ObjectNameOrId"
                type="na:ObjNameOrId"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="LunListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Luns" type="na:ArrayOfLunInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ObjectNameOrId"
                type="na:ObjNameOrId"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="StorageServiceDatasetProvision">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="AssumeConfirmation"
                type="xsd:boolean"/>
            <xsd:element name="DatasetName" type="na:ObjName"/>
            <xsd:element name="StorageServiceNameOrId" type="na:ObjNameOrId"/>
            <xsd:element minOccurs="0" name="StorageSetDetails"
                type="na:ArrayOfStorageSetInfo"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="StorageServiceDatasetProvisionResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ConformanceAlerts"
                type="na:ArrayOfConformanceAlert"/>
            <xsd:element name="DatasetId" type="na:ObjId"/>
            <xsd:element minOccurs="0" name="DryRunResults"
                type="na:ArrayOfDryRunResult"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:complexType name="ArrayOfDatasetInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DatasetInfo"
            type="na:DatasetInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDatasetMemberInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DatasetMemberInfo"
            type="na:DatasetMemberInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDatasetMemberParameter">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DatasetMemberParameter"
            type="na:DatasetMemberParameter"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDpJobProgressEventInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DpJobProgressEventInfo"
            type="na:DpJobProgressEventInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfHostInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="HostInfo" type="na:HostInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfJobInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="JobInfo" type="na:JobInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfLunInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="LunInfo" type="na:LunInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfStorageSetInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="StorageSetInfo"
            type="na:StorageSetInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="DatasetExportInfo">
    <xsd:all>
        <xsd:element minOccurs="0" name="DatasetExportProtocol"
            type="na:DatasetExportProtocol"/>
        <xsd:element minOccurs="0" name="DatasetLunMappingInfo"
            type="na:DatasetLunMappingInfo"/>
    </xsd:all>
</xsd:complexType>
<xsd:simpleType name="DatasetExportProtocol">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:complexType name="DatasetInfo">
    <xsd:all>
        <xsd:element name="DatasetId" type="na:ObjId"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DatasetLunMappingInfo">
    <xsd:all>
        <xsd:element name="IgroupOsType" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DatasetMemberInfo">
    <xsd:all>
        <xsd:element name="MemberId" type="na:ObjId"/>
        <xsd:element name="MemberName" type="na:ObjName"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DatasetMemberParameter">
    <xsd:all>
        <xsd:element name="ObjectNameOrId" type="na:ObjNameOrId"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DpJobProgressEventInfo">
    <xsd:all>
        <xsd:element name="EventStatus" type="na:ObjStatus"/>
        <xsd:element name="EventType" type="xsd:string"/>
        <xsd:element minOccurs="0" name="ProgressLunInfo"
            type="na:ProgressLunInfo"/>
    </xsd:all>
</xsd:complexType>
<xsd:simpleType name="DpPolicyNodeName">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:simpleType name="HostId">
    <xsd:restriction base="xsd:integer"/>
</xsd:simpleType>
<xsd:complexType name="HostInfo">
    <xsd:all>
        <xsd:element name="HostAddress" type="xsd:string"/>
        <xsd:element name="HostId" type="na:HostId"/>
        <xsd:element name="HostName" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="JobInfo">
    <xsd:all>
        <xsd:element name="JobId" type="xsd:integer"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="LunInfo">
    <xsd:all>
        <xsd:element name="HostId" type="na:ObjId"/>
        <xsd:element name="LunPath" type="na:ObjName"/>
    </xsd:all>
</xsd:complexType>
<xsd:simpleType name="ObjId">
    <xsd:restriction base="xsd:integer"/>
</xsd:simpleType>
<xsd:simpleType name="ObjName">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:simpleType name="ObjNameOrId">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:simpleType name="ObjStatus">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:complexType name="ProgressLunInfo">
    <xsd:all>
        <xsd:element name="LunPathId" type="na:ObjId"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="ProvisionMemberRequestInfo">
    <xsd:all>
        <xsd:element minOccurs="0" name="Description" type="xsd:string"/>
        <xsd:element minOccurs="0" name="MaximumSnapshotSpace"
            type="xsd:integer"/>
        <xsd:element name="Name" type="xsd:string"/>
        <xsd:element name="Size" type="xsd:integer"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="Request">
    <xsd:all>
        <xsd:element minOccurs="0" name="Args">
            <xsd:complexType>
                <xsd:sequence>
                    <xsd:any maxOccurs="unbounded" minOccurs="0"/>
                </xsd:sequence>
            </xsd:complexType>
        </xsd:element>
        <xsd:element name="Name" type="xsd:string">
        </xsd:element>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="Response">
    <xsd:all>
        <xsd:element minOccurs="0" name="Errno" type="xsd:integer"/>
        <xsd:element minOccurs="0" name="Reason" type="xsd:string"/>
        <xsd:element minOccurs="0" name="Results">
            <xsd:complexType>
                <xsd:sequence>
                    <xsd:any maxOccurs="unbounded" minOccurs="0"/>
                </xsd:sequence>
            </xsd:complexType>
        </xsd:element>
        <xsd:element name="Status" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="StorageSetInfo">
    <xsd:all>
        <xsd:element minOccurs="0" name="DatasetExportInfo"
            type="na:DatasetExportInfo"/>
        <xsd:element minOccurs="0" name="DpNodeName"
            type="na:DpPolicyNodeName"/>
        <xsd:element minOccurs="0" name="ServerNameOrId"
            type="na:ObjNameOrId"/>
    </xsd:all>
</xsd:complexType>
</xsd:schema></types>"""

WSDL_TRAILER = """<service name="DfmService">
<port binding="na:DfmBinding" name="DfmPort">
<soap:address location="https://HOST_NAME:8488/apis/soap/v1"/>
</port></service></definitions>"""

RESPONSE_PREFIX = """<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:na="http://www.netapp.com/management/v1"><env:Header/><env:Body>"""

RESPONSE_SUFFIX = """</env:Body></env:Envelope>"""

APIS = ['ApiProxy', 'DatasetListInfoIterStart', 'DatasetListInfoIterNext',
    'DatasetListInfoIterEnd', 'DatasetEditBegin', 'DatasetEditCommit',
    'DatasetProvisionMember', 'DatasetRemoveMember', 'DfmAbout',
    'DpJobProgressEventListIterStart', 'DpJobProgressEventListIterNext',
    'DpJobProgressEventListIterEnd', 'DatasetMemberListInfoIterStart',
    'DatasetMemberListInfoIterNext', 'DatasetMemberListInfoIterEnd',
    'HostListInfoIterStart', 'HostListInfoIterNext', 'HostListInfoIterEnd',
    'LunListInfoIterStart', 'LunListInfoIterNext', 'LunListInfoIterEnd',
    'StorageServiceDatasetProvision']

iter_count = 0
iter_table = {}


class FakeDfmServerHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that fakes enough stuff to allow the driver to run"""

    def do_GET(s):
        """Respond to a GET request."""
        if '/dfm.wsdl' != s.path:
            s.send_response(404)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "application/wsdl+xml")
        s.end_headers()
        out = s.wfile
        out.write(WSDL_HEADER)
        out.write(WSDL_TYPES)
        for api in APIS:
            out.write('<message name="%sRequest">' % api)
            out.write('<part element="na:%s" name="parameters"/>' % api)
            out.write('</message>')
            out.write('<message name="%sResponse">' % api)
            out.write('<part element="na:%sResult" name="results"/>' % api)
            out.write('</message>')
        out.write('<portType name="DfmInterface">')
        for api in APIS:
            out.write('<operation name="%s">' % api)
            out.write('<input message="na:%sRequest"/>' % api)
            out.write('<output message="na:%sResponse"/>' % api)
            out.write('</operation>')
        out.write('</portType>')
        out.write('<binding name="DfmBinding" type="na:DfmInterface">')
        out.write('<soap:binding style="document" ' +
            'transport="http://schemas.xmlsoap.org/soap/http"/>')
        for api in APIS:
            out.write('<operation name="%s">' % api)
            out.write('<soap:operation soapAction="urn:%s"/>' % api)
            out.write('<input><soap:body use="literal"/></input>')
            out.write('<output><soap:body use="literal"/></output>')
            out.write('</operation>')
        out.write('</binding>')
        out.write(WSDL_TRAILER)
        return

    def do_POST(s):
        """Respond to a POST request."""
        if '/apis/soap/v1' != s.path:
            s.send_response(404)
            s.end_headers
            return
        request_xml = s.rfile.read(int(s.headers['Content-Length']))
        ntap_ns = 'http://www.netapp.com/management/v1'
        nsmap = {'env': 'http://schemas.xmlsoap.org/soap/envelope/',
            'na': ntap_ns}
        root = etree.fromstring(request_xml)

        body = root.xpath('/env:Envelope/env:Body', namespaces=nsmap)[0]
        request = body.getchildren()[0]
        tag = request.tag
        if not tag.startswith('{' + ntap_ns + '}'):
            s.send_response(500)
            s.end_headers
            return
        api = tag[(2 + len(ntap_ns)):]
        global iter_count
        global iter_table
        if 'DatasetListInfoIterStart' == api:
            body = """<na:DatasetListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>dataset</na:Tag>
                </na:DatasetListInfoIterStartResult>"""
        elif 'DatasetListInfoIterNext' == api:
            body = """<na:DatasetListInfoIterNextResult>
                    <na:Datasets>
                        <na:DatasetInfo>
                            <na:DatasetId>0</na:DatasetId>
                        </na:DatasetInfo>
                    </na:Datasets>
                    <na:Records>1</na:Records>
                </na:DatasetListInfoIterNextResult>"""
        elif 'DatasetListInfoIterEnd' == api:
            body = """<na:DatasetListInfoIterEndResult/>"""
        elif 'DatasetEditBegin' == api:
            body = """<na:DatasetEditBeginResult>
                    <na:EditLockId>0</na:EditLockId>
                </na:DatasetEditBeginResult>"""
        elif 'DatasetEditCommit' == api:
            body = """<na:DatasetEditCommitResult>
                    <na:IsProvisioningFailure>false</na:IsProvisioningFailure>
                    <na:JobIds>
                        <na:JobInfo>
                            <na:JobId>0</na:JobId>
                        </na:JobInfo>
                    </na:JobIds>
                </na:DatasetEditCommitResult>"""
        elif 'DatasetProvisionMember' == api:
            body = """<na:DatasetProvisionMemberResult/>"""
        elif 'DatasetRemoveMember' == api:
            body = """<na:DatasetRemoveMemberResult/>"""
        elif 'DfmAbout' == api:
            body = """<na:DfmAboutResult/>"""
        elif 'DpJobProgressEventListIterStart' == api:
            iter_name = 'dpjobprogress_%s' % iter_count
            iter_count = iter_count + 1
            iter_table[iter_name] = 0
            body = """<na:DpJobProgressEventListIterStartResult>
                    <na:Records>2</na:Records>
                    <na:Tag>%s</na:Tag>
                </na:DpJobProgressEventListIterStartResult>""" % iter_name
        elif 'DpJobProgressEventListIterNext' == api:
            tags = body.xpath('na:DpJobProgressEventListIterNext/na:Tag',
                              namespaces=nsmap)
            iter_name = tags[0].text
            if iter_table[iter_name]:
                body = """<na:DpJobProgressEventListIterNextResult/>"""
            else:
                iter_table[iter_name] = 1
                body = """<na:DpJobProgressEventListIterNextResult>
                        <na:ProgressEvents>
                            <na:DpJobProgressEventInfo>
                                <na:EventStatus>normal</na:EventStatus>
                                <na:EventType>lun-create</na:EventType>
                                <na:ProgressLunInfo>
                                    <na:LunPathId>0</na:LunPathId>
                                 </na:ProgressLunInfo>
                            </na:DpJobProgressEventInfo>
                            <na:DpJobProgressEventInfo>
                                <na:EventStatus>normal</na:EventStatus>
                                <na:EventType>job-end</na:EventType>
                            </na:DpJobProgressEventInfo>
                        </na:ProgressEvents>
                        <na:Records>2</na:Records>
                    </na:DpJobProgressEventListIterNextResult>"""
        elif 'DpJobProgressEventListIterEnd' == api:
            body = """<na:DpJobProgressEventListIterEndResult/>"""
        elif 'DatasetMemberListInfoIterStart' == api:
            body = """<na:DatasetMemberListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>dataset-member</na:Tag>
                </na:DatasetMemberListInfoIterStartResult>"""
        elif 'DatasetMemberListInfoIterNext' == api:
            name = 'filer:/OpenStack_testproj/volume-00000001/volume-00000001'
            body = """<na:DatasetMemberListInfoIterNextResult>
                    <na:DatasetMembers>
                        <na:DatasetMemberInfo>
                            <na:MemberId>0</na:MemberId>
                            <na:MemberName>%s</na:MemberName>
                        </na:DatasetMemberInfo>
                    </na:DatasetMembers>
                    <na:Records>1</na:Records>
                </na:DatasetMemberListInfoIterNextResult>""" % name
        elif 'DatasetMemberListInfoIterEnd' == api:
            body = """<na:DatasetMemberListInfoIterEndResult/>"""
        elif 'HostListInfoIterStart' == api:
            body = """<na:HostListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>host</na:Tag>
                </na:HostListInfoIterStartResult>"""
        elif 'HostListInfoIterNext' == api:
            body = """<na:HostListInfoIterNextResult>
                    <na:Hosts>
                        <na:HostInfo>
                            <na:HostAddress>1.2.3.4</na:HostAddress>
                            <na:HostId>0</na:HostId>
                            <na:HostName>filer</na:HostName>
                        </na:HostInfo>
                    </na:Hosts>
                    <na:Records>1</na:Records>
                </na:HostListInfoIterNextResult>"""
        elif 'HostListInfoIterEnd' == api:
            body = """<na:HostListInfoIterEndResult/>"""
        elif 'LunListInfoIterStart' == api:
            body = """<na:LunListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>lun</na:Tag>
                </na:LunListInfoIterStartResult>"""
        elif 'LunListInfoIterNext' == api:
            path = 'OpenStack_testproj/volume-00000001/volume-00000001'
            body = """<na:LunListInfoIterNextResult>
                    <na:Luns>
                        <na:LunInfo>
                            <na:HostId>0</na:HostId>
                            <na:LunPath>%s</na:LunPath>
                        </na:LunInfo>
                    </na:Luns>
                    <na:Records>1</na:Records>
                </na:LunListInfoIterNextResult>""" % path
        elif 'LunListInfoIterEnd' == api:
            body = """<na:LunListInfoIterEndResult/>"""
        elif 'ApiProxy' == api:
            names = body.xpath('na:ApiProxy/na:Request/na:Name',
                               namespaces=nsmap)
            proxy = names[0].text
            if 'igroup-list-info' == proxy:
                igroup = 'openstack-iqn.1993-08.org.debian:01:23456789'
                initiator = 'iqn.1993-08.org.debian:01:23456789'
                proxy_body = """<initiator-groups>
                        <initiator-group-info>
                            <initiator-group-name>%s</initiator-group-name>
                            <initiator-group-type>iscsi</initiator-group-type>
                       <initiator-group-os-type>linux</initiator-group-os-type>
                            <initiators>
                                <initiator-info>
                                    <initiator-name>%s</initiator-name>
                                </initiator-info>
                            </initiators>
                        </initiator-group-info>
                    </initiator-groups>""" % (igroup, initiator)
            elif 'igroup-create' == proxy:
                proxy_body = ''
            elif 'igroup-add' == proxy:
                proxy_body = ''
            elif 'lun-map-list-info' == proxy:
                proxy_body = '<initiator-groups/>'
            elif 'lun-map' == proxy:
                proxy_body = '<lun-id-assigned>0</lun-id-assigned>'
            elif 'lun-unmap' == proxy:
                proxy_body = ''
            elif 'iscsi-portal-list-info' == proxy:
                proxy_body = """<iscsi-portal-list-entries>
                        <iscsi-portal-list-entry-info>
                            <ip-address>1.2.3.4</ip-address>
                            <ip-port>3260</ip-port>
                            <tpgroup-tag>1000</tpgroup-tag>
                        </iscsi-portal-list-entry-info>
                    </iscsi-portal-list-entries>"""
            elif 'iscsi-node-get-name' == proxy:
                target = 'iqn.1992-08.com.netapp:sn.111111111'
                proxy_body = '<node-name>%s</node-name>' % target
            else:
                # Unknown proxy API
                s.send_response(500)
                s.end_headers
                return
            api = api + ':' + proxy
            proxy_header = '<na:ApiProxyResult><na:Response><na:Results>'
            proxy_trailer = """</na:Results><na:Status>passed</na:Status>
                </na:Response></na:ApiProxyResult>"""
            body = proxy_header + proxy_body + proxy_trailer
        else:
            # Unknown API
            s.send_response(500)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "text/xml; charset=utf-8")
        s.end_headers()
        s.wfile.write(RESPONSE_PREFIX)
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX)
        return


class FakeHttplibSocket(object):
    """A fake socket implementation for httplib.HTTPResponse"""
    def __init__(self, value):
        self._rbuffer = StringIO.StringIO(value)
        self._wbuffer = StringIO.StringIO('')
        oldclose = self._wbuffer.close

        def newclose():
            self.result = self._wbuffer.getvalue()
            oldclose()
        self._wbuffer.close = newclose

    def makefile(self, mode, _other):
        """Returns the socket's internal buffer"""
        if mode == 'r' or mode == 'rb':
            return self._rbuffer
        if mode == 'w' or mode == 'wb':
            return self._wbuffer


class FakeHTTPConnection(object):
    """A fake httplib.HTTPConnection for netapp tests

    Requests made via this connection actually get translated and routed into
    the fake Dfm handler above, we then turn the response into
    the httplib.HTTPResponse that the caller expects.
    """
    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, data=None, headers=None):
        if not headers:
            headers = {}
        req_str = '%s %s HTTP/1.1\r\n' % (method, path)
        for key, value in headers.iteritems():
            req_str += "%s: %s\r\n" % (key, value)
        if data:
            req_str += '\r\n%s' % data

        # NOTE(vish): normally the http transport normailizes from unicode
        sock = FakeHttplibSocket(req_str.decode("latin-1").encode("utf-8"))
        # NOTE(vish): stop the server from trying to look up address from
        #             the fake socket
        FakeDfmServerHandler.address_string = lambda x: '127.0.0.1'
        self.app = FakeDfmServerHandler(sock, '127.0.0.1:8088', None)

        self.sock = FakeHttplibSocket(sock.result)
        self.http_response = httplib.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result


class NetAppDriverTestCase(test.TestCase):
    """Test case for NetAppISCSIDriver"""
    STORAGE_SERVICE = 'Thin Provisioned Space for VMFS Datastores'
    PROJECT_ID = 'testproj'
    VOLUME_NAME = 'volume-00000001'
    VOLUME_SIZE = 2147483648L  # 2 GB
    INITIATOR = 'iqn.1993-08.org.debian:01:23456789'

    def setUp(self):
        super(NetAppDriverTestCase, self).setUp()
        driver = netapp.NetAppISCSIDriver()
        self.stubs.Set(httplib, 'HTTPConnection', FakeHTTPConnection)
        driver._create_client('http://localhost:8088/dfm.wsdl',
                              'root', 'password', 'localhost', 8088)
        driver._set_storage_service(self.STORAGE_SERVICE)
        self.driver = driver

    def test_connect(self):
        self.driver.check_for_setup_error()

    def test_create_destroy(self):
        self.driver._provision(self.VOLUME_NAME, None, self.PROJECT_ID,
                               self.VOLUME_SIZE)
        self.driver._remove_destroy(self.VOLUME_NAME, self.PROJECT_ID)

    def test_map_unmap(self):
        self.driver._provision(self.VOLUME_NAME, None, self.PROJECT_ID,
                               self.VOLUME_SIZE)
        volume = {'name': self.VOLUME_NAME, 'project_id': self.PROJECT_ID,
            'id': 0, 'provider_auth': None}
        updates = self.driver._get_export(volume)
        self.assertTrue(updates['provider_location'])
        volume['provider_location'] = updates['provider_location']
        connector = {'initiator': self.INITIATOR}
        connection_info = self.driver.initialize_connection(volume, connector)
        self.assertEqual(connection_info['driver_volume_type'], 'iscsi')
        properties = connection_info['data']
        self.driver.terminate_connection(volume, connector)
        self.driver._remove_destroy(self.VOLUME_NAME, self.PROJECT_ID)
