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


def ensure_ca_filesystem():
    pass


def fetch_ca(project_id=None):
    rootca = """-----BEGIN CERTIFICATE-----
MIICyzCCAjSgAwIBAgIJAIJ/UoFWKoOUMA0GCSqGSIb3DQEBBAUAME4xEjAQBgNV
BAoTCU5PVkEgUk9PVDEWMBQGA1UEBxMNTW91bnRhaW4gVmlldzETMBEGA1UECBMK
Q2FsaWZvcm5pYTELMAkGA1UEBhMCVVMwHhcNMTIxMDAyMTg1NzQ1WhcNMTMxMDAy
MTg1NzQ1WjBOMRIwEAYDVQQKEwlOT1ZBIFJPT1QxFjAUBgNVBAcTDU1vdW50YWlu
IFZpZXcxEzARBgNVBAgTCkNhbGlmb3JuaWExCzAJBgNVBAYTAlVTMIGfMA0GCSqG
SIb3DQEBAQUAA4GNADCBiQKBgQCg0Bn8WSqbJF3QNTZUxo1TzmFBxuqvhjZLKbnQ
IiShdVIWUK7RC8frq8FJI7dgJNmvkIBn9njABWDoZmurQRCzD65yCSbUc4R2ea5H
IK4wQIui0CJykvMBNjAe3bzztVVs8/ccDTsjtqq3F/KeQkKzQVfSWBrJSmYtG5tO
G+dOSwIDAQABo4GwMIGtMAwGA1UdEwQFMAMBAf8wHQYDVR0OBBYEFCljRfaNOsA/
9mHuq0io7Lt83FtaMH4GA1UdIwR3MHWAFCljRfaNOsA/9mHuq0io7Lt83FtaoVKk
UDBOMRIwEAYDVQQKEwlOT1ZBIFJPT1QxFjAUBgNVBAcTDU1vdW50YWluIFZpZXcx
EzARBgNVBAgTCkNhbGlmb3JuaWExCzAJBgNVBAYTAlVTggkAgn9SgVYqg5QwDQYJ
KoZIhvcNAQEEBQADgYEAEbpJOOlpKCh5omwfAwAfFg1ml4h/FJiCH3PETmOCc+3l
CtWTBd4MG8AoH7A3PU2JKAGVQ5XWo6+ihpW1RgfQpCnloI6vIeGcws+rSLnlzULt
IvfCJpRg7iQdR3jZGt3295behtP1GsCqipJEulOkOaEIs8iLlXgSOG94Mkwlb4Q=
-----END CERTIFICATE-----
"""
    return rootca


def generate_x509_cert(user_id, project_id, bits=1024):
    pk = """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQC4h2d63ijt9l0fIBRY37D3Yj2FYajCMUlftSoHNA4lEw0uTXnH
Jjbd0j7HNlSADWeAMuaoSDNp7CIsXMt6iA/ASN5nFFTZlLRqIzYoI0RHiiSJjvSG
d1n4Yrar1eC8tK3Rld1Zo6rj6tOuIxfFVJajJVZykCAHjGNNvulgfhBXFwIDAQAB
AoGBAIjfxx4YU/vO1lwUC4OwyS92q3OYcPk6XdakJryZHDTb4NcLmNzjt6bqIK7b
2enyB2fMWdNRWvGiueZ2HmiRLDyOGsAVdEsHvL4qbr9EZGTqC8Qxx+zTevWWf6pB
F1zxzbXNQDFZDf9kVsSLCkbMHITnW1k4MrM++9gfCO3WrfehAkEA4nd8TyCCZazq
KMOQwFLTNaiVLeTXCtvGopl4ZNiKYZ1qI3KDXb2wbAyArFuERlotxFlylXpwtlMo
SlI/C/sYqwJBANCX1sdfRJq8DpdP44ThWqOkWFLB9rBiwyyBt8746fX8amwr8eyz
H44/z5GT/Vyp8qFsjkuDzeP93eeDnr2qE0UCP1zipRnPO6x4P5J4o+Y+EmLvwkAQ
nCLYAaCvUbILHrbq2Z2wWjEYnEO03RHUd2xjkGH4TgcBMTmW4e+ZzEIduwJACnIw
LVfWBbG5QVac3EC021EVoz9XbUnk4Eu2usS4Yrs7USN6QBJQWD1V1cKFg6h3ICJh
leKJ4wsJm9h5kKH9yQJBAN8CaX223MlTSuBOVuIOwNA+09iLfx4UCLiH1fGMKDpe
xVcmkM3qCnTqNxrAPSFdT9IyB3IXiaLWbvzl7MfiOwQ=
-----END RSA PRIVATE KEY-----
"""
    csr = """Certificate:
    Data:
        Version: 1 (0x0)
        Serial Number: 23 (0x17)
        Signature Algorithm: md5WithRSAEncryption
        Issuer: O=NOVA ROOT, L=Mountain View, ST=California, C=US
        Validity
            Not Before: Oct  2 19:31:45 2012 GMT
            Not After : Oct  2 19:31:45 2013 GMT
        Subject: C=US, ST=California, O=OpenStack, OU=NovaDev, """
    """CN=openstack-fake-2012-10-02T19:31:45Z
        Subject Public Key Info:
            Public Key Algorithm: rsaEncryption
            RSA Public Key: (1024 bit)
                Modulus (1024 bit):
                    00:b8:87:67:7a:de:28:ed:f6:5d:1f:20:14:58:df:
                    b0:f7:62:3d:85:61:a8:c2:31:49:5f:b5:2a:07:34:
                    0e:25:13:0d:2e:4d:79:c7:26:36:dd:d2:3e:c7:36:
                    54:80:0d:67:80:32:e6:a8:48:33:69:ec:22:2c:5c:
                    cb:7a:88:0f:c0:48:de:67:14:54:d9:94:b4:6a:23:
                    36:28:23:44:47:8a:24:89:8e:f4:86:77:59:f8:62:
                    b6:ab:d5:e0:bc:b4:ad:d1:95:dd:59:a3:aa:e3:ea:
                    d3:ae:23:17:c5:54:96:a3:25:56:72:90:20:07:8c:
                    63:4d:be:e9:60:7e:10:57:17
                Exponent: 65537 (0x10001)
    Signature Algorithm: md5WithRSAEncryption
        32:82:ff:8b:92:0e:8d:9c:6b:ce:7e:fe:34:16:2a:4c:47:4f:
        c7:28:a2:33:1e:48:56:2e:4b:e8:e8:e3:48:b1:3d:a3:43:21:
        ef:83:e7:df:e2:10:91:7e:9a:c0:4d:1e:96:68:2b:b9:f7:84:
        7f:ec:84:8a:bf:bc:5e:50:05:d9:ce:4a:1a:bf:d2:bf:0c:d1:
        7e:ec:64:c3:a5:37:78:a3:a6:2b:a1:b7:1c:cc:c8:b9:78:61:
        98:50:3c:e6:28:34:f1:0e:62:bb:b5:d7:a1:dd:1f:38:c6:0d:
        58:9f:81:67:ff:9c:32:fc:52:7e:6d:8c:91:43:49:fe:e3:48:
        bb:40
-----BEGIN CERTIFICATE-----
MIICMzCCAZwCARcwDQYJKoZIhvcNAQEEBQAwTjESMBAGA1UEChMJTk9WQSBST09U
MRYwFAYDVQQHEw1Nb3VudGFpbiBWaWV3MRMwEQYDVQQIEwpDYWxpZm9ybmlhMQsw
CQYDVQQGEwJVUzAeFw0xMjEwMDIxOTMxNDVaFw0xMzEwMDIxOTMxNDVaMHYxCzAJ
BgNVBAYTAlVTMRMwEQYDVQQIEwpDYWxpZm9ybmlhMRIwEAYDVQQKEwlPcGVuU3Rh
Y2sxEDAOBgNVBAsTB05vdmFEZXYxLDAqBgNVBAMTI29wZW5zdGFjay1mYWtlLTIw
MTItMTAtMDJUMTk6MzE6NDVaMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC4
h2d63ijt9l0fIBRY37D3Yj2FYajCMUlftSoHNA4lEw0uTXnHJjbd0j7HNlSADWeA
MuaoSDNp7CIsXMt6iA/ASN5nFFTZlLRqIzYoI0RHiiSJjvSGd1n4Yrar1eC8tK3R
ld1Zo6rj6tOuIxfFVJajJVZykCAHjGNNvulgfhBXFwIDAQABMA0GCSqGSIb3DQEB
BAUAA4GBADKC/4uSDo2ca85+/jQWKkxHT8coojMeSFYuS+jo40ixPaNDIe+D59/i
EJF+msBNHpZoK7n3hH/shIq/vF5QBdnOShq/0r8M0X7sZMOlN3ijpiuhtxzMyLl4
YZhQPOYoNPEOYru116HdHzjGDVifgWf/nDL8Un5tjJFDSf7jSLtA
-----END CERTIFICATE-----
"""
    return pk, csr


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
