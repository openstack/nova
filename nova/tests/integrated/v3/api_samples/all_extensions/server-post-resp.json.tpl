{
    "server": {
        "admin_password": "%(password)s",
        "id": "%(id)s",
        "links": [
            {
                "href": "%(host)s/v3/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "os-security-groups:security_groups": [
            {
                "name": "default"
            }
        ],
        "os-access-ips:access_ip_v4": "",
        "os-access-ips:access_ip_v6": ""
    }
}
