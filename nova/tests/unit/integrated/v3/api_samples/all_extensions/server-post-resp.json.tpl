{
    "server": {
        "OS-DCF:diskConfig": "AUTO",
        "adminPass": "%(password)s",
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
        "security_groups": [
            {
                "name": "default"
            }
        ],
        "accessIPv4": "",
        "accessIPv6": ""
    }
}
