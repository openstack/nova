#!/bin/bash
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

# This gets zipped and run on the cloudpipe-managed OpenVPN server
NAME=$1
SUBJ=$2

mkdir -p projects/$NAME
cd projects/$NAME

# generate a server priv key
openssl genrsa -out server.key 2048

# generate a server CSR
openssl req -new -key server.key -out server.csr -batch -subj "$SUBJ"

novauid=`getent passwd nova | awk -F: '{print $3}'`
if [ ! -z "${novauid}" ] && [ "`id -u`" != "${novauid}" ]; then
    sudo chown -R nova:nogroup .
fi
