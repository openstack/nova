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
# LDAP INSTALL SCRIPT - SHOULD BE IDEMPOTENT, but it SCRUBS all USERS

apt-get install -y slapd ldap-utils python-ldap

abspath=`dirname "$(cd "${0%/*}" 2>/dev/null; echo "$PWD"/"${0##*/}")"`
cp $abspath/openssh-lpk_openldap.schema /etc/ldap/schema/openssh-lpk_openldap.schema
cp $abspath/nova_openldap.schema /etc/ldap/schema/nova.schema

mv /etc/ldap/slapd.conf /etc/ldap/slapd.conf.orig
cat >/etc/ldap/slapd.conf <<SLAPD_CONF_EOF
# slapd.conf - Configuration file for LDAP SLAPD
##########
# Basics #
##########
include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/inetorgperson.schema
include /etc/ldap/schema/nova.schema
pidfile /var/run/slapd/slapd.pid
argsfile /var/run/slapd/slapd.args
loglevel none
modulepath /usr/lib/ldap
# modulepath /usr/local/libexec/openldap
moduleload back_hdb
##########################
# Database Configuration #
##########################
database hdb
suffix "dc=example,dc=com"
rootdn "cn=Manager,dc=example,dc=com"
rootpw changeme
directory /var/lib/ldap
# directory /usr/local/var/openldap-data
index objectClass,cn eq
########
# ACLs #
########
access to attrs=userPassword
       by anonymous auth
       by self write
       by * none
access to *
       by self write
       by * none
SLAPD_CONF_EOF

mv /etc/ldap/ldap.conf /etc/ldap/ldap.conf.orig

cat >/etc/ldap/ldap.conf <<LDAP_CONF_EOF
# LDAP Client Settings
URI ldap://localhost
BASE dc=example,dc=com
BINDDN cn=Manager,dc=example,dc=com
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

/etc/init.d/slapd stop
rm -rf /var/lib/ldap/*
rm -rf /etc/ldap/slapd.d/*
slaptest -f /etc/ldap/slapd.conf -F /etc/ldap/slapd.d
cp /usr/share/slapd/DB_CONFIG /var/lib/ldap/DB_CONFIG
slapadd -v -l /etc/ldap/base.ldif
chown -R openldap:openldap /etc/ldap/slapd.d
chown -R openldap:openldap /var/lib/ldap
/etc/init.d/slapd start
