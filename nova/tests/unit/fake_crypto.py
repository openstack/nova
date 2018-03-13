# Copyright 2012 Nebula, Inc.
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


def get_x509_cert_and_fingerprint():
    fingerprint = "a1:6f:6d:ea:a6:36:d0:3a:c6:eb:b6:ee:07:94:3e:2a:90:98:2b:c9"
    certif = (
        "-----BEGIN CERTIFICATE-----\n"
        "MIIDIjCCAgqgAwIBAgIJAIE8EtWfZhhFMA0GCSqGSIb3DQEBCwUAMCQxIjAgBgNV\n"
        "BAMTGWNsb3VkYmFzZS1pbml0LXVzZXItMTM1NTkwHhcNMTUwMTI5MTgyMzE4WhcN\n"
        "MjUwMTI2MTgyMzE4WjAkMSIwIAYDVQQDExljbG91ZGJhc2UtaW5pdC11c2VyLTEz\n"
        "NTU5MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAv4lv95ofkXLIbALU\n"
        "UEb1f949TYNMUvMGNnLyLgGOY+D61TNG7RZn85cRg9GVJ7KDjSLN3e3LwH5rgv5q\n"
        "pU+nM/idSMhG0CQ1lZeExTsMEJVT3bG7LoU5uJ2fJSf5+hA0oih2M7/Kap5ggHgF\n"
        "h+h8MWvDC9Ih8x1aadkk/OEmJsTrziYm0C/V/FXPHEuXfZn8uDNKZ/tbyfI6hwEj\n"
        "nLz5Zjgg29n6tIPYMrnLNDHScCwtNZOcnixmWzsxCt1bxsAEA/y9gXUT7xWUf52t\n"
        "2+DGQbLYxo0PHjnPf3YnFXNavfTt+4c7ZdHhOQ6ZA8FGQ2LJHDHM1r2/8lK4ld2V\n"
        "qgNTcQIDAQABo1cwVTATBgNVHSUEDDAKBggrBgEFBQcDAjA+BgNVHREENzA1oDMG\n"
        "CisGAQQBgjcUAgOgJQwjY2xvdWRiYXNlLWluaXQtdXNlci0xMzU1OUBsb2NhbGhv\n"
        "c3QwDQYJKoZIhvcNAQELBQADggEBAHHX/ZUOMR0ZggQnfXuXLIHWlffVxxLOV/bE\n"
        "7JC/dtedHqi9iw6sRT5R6G1pJo0xKWr2yJVDH6nC7pfxCFkby0WgVuTjiu6iNRg2\n"
        "4zNJd8TGrTU+Mst+PPJFgsxrAY6vjwiaUtvZ/k8PsphHXu4ON+oLurtVDVgog7Vm\n"
        "fQCShx434OeJj1u8pb7o2WyYS5nDVrHBhlCAqVf2JPKu9zY+i9gOG2kimJwH7fJD\n"
        "xXpMIwAQ+flwlHR7OrE0L8TNcWwKPRAY4EPcXrT+cWo1k6aTqZDSK54ygW2iWtni\n"
        "ZBcstxwcB4GIwnp1DrPW9L2gw5eLe1Sl6wdz443TW8K/KPV9rWQ=\n"
        "-----END CERTIFICATE-----\n")
    return certif, fingerprint


def get_ssh_public_key():
    public_key = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDx8nkQv/zgGg"
                  "B4rMYmIf+6A4l6Rr+o/6lHBQdW5aYd44bd8JttDCE/F/pNRr0l"
                  "RE+PiqSPO8nDPHw0010JeMH9gYgnnFlyY3/OcJ02RhIPyyxYpv"
                  "9FhY+2YiUkpwFOcLImyrxEsYXpD/0d3ac30bNH6Sw9JD9UZHYc"
                  "pSxsIbECHw== Generated-by-Nova")
    return public_key
