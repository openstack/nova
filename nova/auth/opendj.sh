#!/usr/bin/env bash
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
# LDAP INSTALL SCRIPT -  IS IDEMPOTENT, does not scrub users

apt-get install -y ldap-utils python-ldap openjdk-6-jre

if [ ! -d "/usr/opendj" ]
then
    # TODO(rlane): Wikimedia Foundation is the current package maintainer.
    # After the package is included in Ubuntu's channel, change this.
    wget http://apt.wikimedia.org/wikimedia/pool/main/o/opendj/opendj_2.4.0-7_amd64.deb
    dpkg -i opendj_2.4.0-7_amd64.deb
fi

abspath=`dirname "$(cd "${0%/*}" 2>/dev/null; echo "$PWD"/"${0##*/}")"`
schemapath='/var/opendj/instance/config/schema'
cp $abspath/openssh-lpk_sun.schema $schemapath/97-openssh-lpk_sun.ldif
cp $abspath/nova_sun.schema $schemapath/98-nova_sun.ldif
chown opendj:opendj $schemapath/98-nova_sun.ldif

cat >/etc/ldap/ldap.conf <<LDAP_CONF_EOF
# LDAP Client Settings
URI ldap://localhost
BASE dc=example,dc=com
BINDDN cn=Directory Manager
SIZELIMIT  0
TIMELIMIT  0
LDAP_CONF_EOF

cat >/etc/ldap/base.ldif <<BASE_LDIF_EOF
# This is the root of the directory tree
dn: dc=example,dc=com
description: Example.Com, your trusted non-existent corporation.
dc: example
o: Example.Com
objectClass: top
objectClass: dcObject
objectClass: organization

# Subtree for users
dn: ou=Users,dc=example,dc=com
ou: Users
description: Users
objectClass: organizationalUnit

# Subtree for groups
dn: ou=Groups,dc=example,dc=com
ou: Groups
description: Groups
objectClass: organizationalUnit

# Subtree for system accounts
dn: ou=System,dc=example,dc=com
ou: System
description: Special accounts used by software applications.
objectClass: organizationalUnit

# Special Account for Authentication:
dn: uid=authenticate,ou=System,dc=example,dc=com
uid: authenticate
ou: System
description: Special account for authenticating users
userPassword: {MD5}TLnIqASP0CKUR3/LGkEZGg==
objectClass: account
objectClass: simpleSecurityObject

# create the sysadmin entry

dn: cn=developers,ou=Groups,dc=example,dc=com
objectclass: groupOfNames
cn: developers
description: IT admin group
member: uid=admin,ou=Users,dc=example,dc=com

dn: cn=sysadmins,ou=Groups,dc=example,dc=com
objectclass: groupOfNames
cn: sysadmins
description: IT admin group
member: uid=admin,ou=Users,dc=example,dc=com

dn: cn=netadmins,ou=Groups,dc=example,dc=com
objectclass: groupOfNames
cn: netadmins
description: Network admin group
member: uid=admin,ou=Users,dc=example,dc=com

dn: cn=cloudadmins,ou=Groups,dc=example,dc=com
objectclass: groupOfNames
cn: cloudadmins
description: Cloud admin group
member: uid=admin,ou=Users,dc=example,dc=com

dn: cn=itsec,ou=Groups,dc=example,dc=com
objectclass: groupOfNames
cn: itsec
description: IT security users group
member: uid=admin,ou=Users,dc=example,dc=com
BASE_LDIF_EOF

/etc/init.d/opendj stop
su - opendj -c '/usr/opendj/setup -i -b "dc=example,dc=com" -l /etc/ldap/base.ldif -S -w changeme -O -n --noPropertiesFile'
/etc/init.d/opendj start
