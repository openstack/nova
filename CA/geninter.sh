#!/bin/bash

# Copyright [2010] [Anso Labs, LLC]
# 
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
# 
#        http://www.apache.org/licenses/LICENSE-2.0
# 
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


# ARG is the id of the user
export SUBJ=/C=US/ST=California/L=Mountain View/O=Anso Labs/OU=Nova Dev/CN=customer-intCA-$3
mkdir INTER/$1
cd INTER/$1
cp ../../openssl.cnf.tmpl openssl.cnf
sed -i -e s/%USERNAME%/$1/g openssl.cnf
mkdir certs crl newcerts private
echo "10" > serial
touch index.txt
openssl genrsa -out private/cakey.pem 1024 -config ./openssl.cnf -batch -nodes
openssl req -new -sha2 -key private/cakey.pem -out ../../reqs/inter$1.csr -batch -subj "$SUBJ"
cd ../../
openssl ca -extensions v3_ca -days 365 -out INTER/$1/cacert.pem -in reqs/inter$1.csr -config openssl.cnf -batch
