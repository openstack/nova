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

if [ -f "cacert.pem" ];
then
    echo "Not installing, it's already done."
else
    cp "$(dirname $0)/openssl.cnf.tmpl" openssl.cnf
    sed -i -e s/%USERNAME%/ROOT/g openssl.cnf
    mkdir -p certs crl newcerts private
    openssl req -new -x509 -extensions v3_ca -keyout private/cakey.pem -out cacert.pem -days 365 -config ./openssl.cnf -batch -nodes
    touch index.txt
    echo "10" > serial
    openssl ca -gencrl -config ./openssl.cnf -out crl.pem
fi
