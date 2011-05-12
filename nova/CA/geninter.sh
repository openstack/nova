#!/bin/bash

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

# $1 is the id of the project and $2 is the subject of the cert
NAME=$1
SUBJ=$2
mkdir -p projects/$NAME
cd projects/$NAME
cp "$(dirname $0)/openssl.cnf.tmpl" openssl.cnf
sed -i -e s/%USERNAME%/$NAME/g openssl.cnf
mkdir -p certs crl newcerts private
openssl req -new -x509 -extensions v3_ca -keyout private/cakey.pem -out cacert.pem -days 365 -config ./openssl.cnf -batch -nodes
echo "10" > serial
touch index.txt
# NOTE(vish): Disabling intermediate ca's because we don't actually need them.
#             It makes more sense to have each project have its own root ca.
# openssl genrsa -out private/cakey.pem 1024 -config ./openssl.cnf -batch -nodes
# openssl req -new -sha256 -key private/cakey.pem -out ../../reqs/inter$NAME.csr -batch -subj "$SUBJ"
openssl ca -gencrl -config ./openssl.cnf -out crl.pem
if [ "`id -u`" != "`grep nova /etc/passwd | cut -d':' -f3`" ]; then
    sudo chown -R nova:nogroup .
fi
# cd ../../
# openssl ca -extensions v3_ca -days 365 -out INTER/$NAME/cacert.pem -in reqs/inter$NAME.csr -config openssl.cnf -batch
