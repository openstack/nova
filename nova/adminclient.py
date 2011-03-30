# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Nova User API client library.
"""

import base64
import boto
import boto.exception
import httplib
import re
import string

from boto.ec2.regioninfo import RegionInfo


DEFAULT_CLC_URL = 'http://127.0.0.1:8773'
DEFAULT_REGION = 'nova'


class UserInfo(object):
    """
    Information about a Nova user, as parsed through SAX.

    **Fields Include**

    * username
    * accesskey
    * secretkey
    * file (optional) containing zip of X509 cert & rc file

    """

    def __init__(self, connection=None, username=None, endpoint=None):
        self.connection = connection
        self.username = username
        self.endpoint = endpoint

    def __repr__(self):
        return 'UserInfo:%s' % self.username

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'username':
            self.username = str(value)
        elif name == 'file':
            self.file = base64.b64decode(str(value))
        elif name == 'accesskey':
            self.accesskey = str(value)
        elif name == 'secretkey':
            self.secretkey = str(value)


class UserRole(object):
    """
    Information about a Nova user's role, as parsed through SAX.

    **Fields include**

    * role

    """

    def __init__(self, connection=None):
        self.connection = connection
        self.role = None

    def __repr__(self):
        return 'UserRole:%s' % self.role

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'role':
            self.role = value
        else:
            setattr(self, name, str(value))


class ProjectInfo(object):
    """
    Information about a Nova project, as parsed through SAX.

    **Fields include**

    * projectname
    * description
    * projectManagerId
    * memberIds

    """

    def __init__(self, connection=None):
        self.connection = connection
        self.projectname = None
        self.description = None
        self.projectManagerId = None
        self.memberIds = []

    def __repr__(self):
        return 'ProjectInfo:%s' % self.projectname

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'projectname':
            self.projectname = value
        elif name == 'description':
            self.description = value
        elif name == 'projectManagerId':
            self.projectManagerId = value
        elif name == 'memberId':
            self.memberIds.append(value)
        else:
            setattr(self, name, str(value))


class ProjectMember(object):
    """
    Information about a Nova project member, as parsed through SAX.

    **Fields include**

    * memberId

    """

    def __init__(self, connection=None):
        self.connection = connection
        self.memberId = None

    def __repr__(self):
        return 'ProjectMember:%s' % self.memberId

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'member':
            self.memberId = value
        else:
            setattr(self, name, str(value))


class HostInfo(object):
    """
    Information about a Nova Host, as parsed through SAX.

    **Fields Include**

    * Hostname
    * Compute service status
    * Volume service status
    * Instance count
    * Volume count
    """

    def __init__(self, connection=None):
        self.connection = connection
        self.hostname = None
        self.compute = None
        self.volume = None
        self.instance_count = 0
        self.volume_count = 0

    def __repr__(self):
        return 'Host:%s' % self.hostname

    # this is needed by the sax parser, so ignore the ugly name
    def startElement(self, name, attrs, connection):
        return None

    # this is needed by the sax parser, so ignore the ugly name
    def endElement(self, name, value, connection):
        fixed_name = string.lower(re.sub(r'([A-Z])', r'_\1', name))
        setattr(self, fixed_name, value)


class Vpn(object):
    """
    Information about a Vpn, as parsed through SAX

    **Fields Include**

    * instance_id
    * project_id
    * public_ip
    * public_port
    * created_at
    * internal_ip
    * state
    """

    def __init__(self, connection=None):
        self.connection = connection
        self.instance_id = None
        self.project_id = None

    def __repr__(self):
        return 'Vpn:%s:%s' % (self.project_id, self.instance_id)

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        fixed_name = string.lower(re.sub(r'([A-Z])', r'_\1', name))
        setattr(self, fixed_name, value)


class InstanceType(object):
    """
    Information about a Nova instance type, as parsed through SAX.

    **Fields include**

    * name
    * vcpus
    * disk_gb
    * memory_mb
    * flavor_id

    """

    def __init__(self, connection=None):
        self.connection = connection
        self.name = None
        self.vcpus = None
        self.disk_gb = None
        self.memory_mb = None
        self.flavor_id = None

    def __repr__(self):
        return 'InstanceType:%s' % self.name

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == "memoryMb":
            self.memory_mb = str(value)
        elif name == "flavorId":
            self.flavor_id = str(value)
        elif name == "diskGb":
            self.disk_gb = str(value)
        else:
            setattr(self, name, str(value))


class NovaAdminClient(object):

    def __init__(
            self,
            clc_url=DEFAULT_CLC_URL,
            region=DEFAULT_REGION,
            access_key=None,
            secret_key=None,
            **kwargs):
        parts = self.split_clc_url(clc_url)

        self.clc_url = clc_url
        self.region = region
        self.access = access_key
        self.secret = secret_key
        self.apiconn = boto.connect_ec2(aws_access_key_id=access_key,
                                        aws_secret_access_key=secret_key,
                                        is_secure=parts['is_secure'],
                                        region=RegionInfo(None,
                                                          region,
                                                          parts['ip']),
                                        port=parts['port'],
                                        path='/services/Admin',
                                        **kwargs)
        self.apiconn.APIVersion = 'nova'

    def connection_for(self, username, project, clc_url=None, region=None,
                       **kwargs):
        """Returns a boto ec2 connection for the given username."""
        if not clc_url:
            clc_url = self.clc_url
        if not region:
            region = self.region
        parts = self.split_clc_url(clc_url)
        user = self.get_user(username)
        access_key = '%s:%s' % (user.accesskey, project)
        return boto.connect_ec2(aws_access_key_id=access_key,
                                aws_secret_access_key=user.secretkey,
                                is_secure=parts['is_secure'],
                                region=RegionInfo(None,
                                                  self.region,
                                                  parts['ip']),
                                port=parts['port'],
                                path='/services/Cloud',
                                **kwargs)

    def split_clc_url(self, clc_url):
        """Splits a cloud controller endpoint url."""
        parts = httplib.urlsplit(clc_url)
        is_secure = parts.scheme == 'https'
        ip, port = parts.netloc.split(':')
        return {'ip': ip, 'port': int(port), 'is_secure': is_secure}

    def get_users(self):
        """Grabs the list of all users."""
        return self.apiconn.get_list('DescribeUsers', {}, [('item', UserInfo)])

    def get_user(self, name):
        """Grab a single user by name."""
        user = self.apiconn.get_object('DescribeUser',
                                       {'Name': name},
                                       UserInfo)
        if user.username != None:
            return user

    def has_user(self, username):
        """Determine if user exists."""
        return self.get_user(username) != None

    def create_user(self, username):
        """Creates a new user, returning the userinfo object with
        access/secret."""
        return self.apiconn.get_object('RegisterUser', {'Name': username},
                                       UserInfo)

    def delete_user(self, username):
        """Deletes a user."""
        return self.apiconn.get_object('DeregisterUser', {'Name': username},
                                       UserInfo)

    def get_roles(self, project_roles=True):
        """Returns a list of available roles."""
        return self.apiconn.get_list('DescribeRoles',
                                     {'ProjectRoles': project_roles},
                                     [('item', UserRole)])

    def get_user_roles(self, user, project=None):
        """Returns a list of roles for the given user.

        Omitting project will return any global roles that the user has.
        Specifying project will return only project specific roles.

        """
        params = {'User': user}
        if project:
            params['Project'] = project
        return self.apiconn.get_list('DescribeUserRoles',
                                     params,
                                     [('item', UserRole)])

    def add_user_role(self, user, role, project=None):
        """Add a role to a user either globally or for a specific project."""
        return self.modify_user_role(user, role, project=project,
                                     operation='add')

    def remove_user_role(self, user, role, project=None):
        """Remove a role from a user either globally or for a specific
        project."""
        return self.modify_user_role(user, role, project=project,
                                     operation='remove')

    def modify_user_role(self, user, role, project=None, operation='add',
                         **kwargs):
        """Add or remove a role for a user and project."""
        params = {'User': user,
                  'Role': role,
                  'Project': project,
                  'Operation': operation}
        return self.apiconn.get_status('ModifyUserRole', params)

    def get_projects(self, user=None):
        """Returns a list of all projects."""
        if user:
            params = {'User': user}
        else:
            params = {}
        return self.apiconn.get_list('DescribeProjects',
                                     params,
                                     [('item', ProjectInfo)])

    def get_project(self, name):
        """Returns a single project with the specified name."""
        project = self.apiconn.get_object('DescribeProject',
                                          {'Name': name},
                                          ProjectInfo)

        if project.projectname != None:
            return project

    def create_project(self, projectname, manager_user, description=None,
                       member_users=None):
        """Creates a new project."""
        params = {'Name': projectname,
                  'ManagerUser': manager_user,
                  'Description': description,
                  'MemberUsers': member_users}
        return self.apiconn.get_object('RegisterProject', params, ProjectInfo)

    def modify_project(self, projectname, manager_user=None, description=None):
        """Modifies an existing project."""
        params = {'Name': projectname,
                  'ManagerUser': manager_user,
                  'Description': description}
        return self.apiconn.get_status('ModifyProject', params)

    def delete_project(self, projectname):
        """Permanently deletes the specified project."""
        return self.apiconn.get_object('DeregisterProject',
                                       {'Name': projectname},
                                       ProjectInfo)

    def get_project_members(self, name):
        """Returns a list of members of a project."""
        return self.apiconn.get_list('DescribeProjectMembers',
                                     {'Name': name},
                                     [('item', ProjectMember)])

    def add_project_member(self, user, project):
        """Adds a user to a project."""
        return self.modify_project_member(user, project, operation='add')

    def remove_project_member(self, user, project):
        """Removes a user from a project."""
        return self.modify_project_member(user, project, operation='remove')

    def modify_project_member(self, user, project, operation='add'):
        """Adds or removes a user from a project."""
        params = {'User': user,
                  'Project': project,
                  'Operation': operation}
        return self.apiconn.get_status('ModifyProjectMember', params)

    def get_zip(self, user, project):
        """Returns the content of a zip file containing novarc and access
        credentials."""
        params = {'Name': user, 'Project': project}
        zip = self.apiconn.get_object('GenerateX509ForUser', params, UserInfo)
        return zip.file

    def start_vpn(self, project):
        """
        Starts the vpn for a user
        """
        return self.apiconn.get_object('StartVpn', {'Project': project}, Vpn)

    def get_vpns(self):
        """Return a list of vpn with project name"""
        return self.apiconn.get_list('DescribeVpns', {}, [('item', Vpn)])

    def get_hosts(self):
        return self.apiconn.get_list('DescribeHosts', {}, [('item', HostInfo)])

    def get_instance_types(self):
        """Grabs the list of all users."""
        return self.apiconn.get_list('DescribeInstanceTypes', {},
                                     [('item', InstanceType)])
