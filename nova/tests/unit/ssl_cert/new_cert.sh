#!/usr/bin/env bash

openssl req  -new -out certificate.csr -key privatekey.key \
             -config certificate.cnf
openssl x509 -extfile certificate.cnf -extensions x509_ext \
             -req -sha512 -days 3650 -set_serial 1 \
             -CA ca.crt -CAkey ca.key \
             -in certificate.csr -out certificate.crt

if [ "$1" == "--dump" ] ; then
    openssl req -in certificate.csr -text -noout > /tmp/csr.txt
    openssl x509 -in ca.crt -text -noout > /tmp/ca.txt
    openssl x509 -in certificate.crt -text -noout > /tmp/certificate.txt
fi
rm certificate.csr
