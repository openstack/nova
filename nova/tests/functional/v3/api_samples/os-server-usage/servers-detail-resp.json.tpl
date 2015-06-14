{
    "servers": [
    {
            "accessIPv4": "%(access_ip_v4)s",
            "accessIPv6": "%(access_ip_v6)s",
            "status": "ACTIVE",
            "created": "%(isotime)s",
            "OS-SRV-USG:launched_at": "%(strtime)s",
            "user_id": "fake",
            "addresses": {
                "private": [
                    {
                        "addr": "%(ip)s",
                        "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
                        "OS-EXT-IPS:type": "fixed",
                        "version": 4
                    }
                ]
            },
            "key_name": null,
            "links": [
                {
                    "href": "%(host)s/v2/openstack/servers/%(uuid)s",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/openstack/servers/%(id)s",
                    "rel": "bookmark"
                }
            ],
            "updated": "%(isotime)s",
            "name": "new-server-test",
            "image": {
                "id": "%(uuid)s",
                "links": [
                    {
                        "href": "%(host)s/openstack/images/%(uuid)s",
                        "rel": "bookmark"
                    }
                ]
            },
            "id": "%(uuid)s",
            "OS-SRV-USG:terminated_at": null,
            "tenant_id": "openstack",
            "progress": 0,
            "flavor": {
                "id": "1",
                "links": [
                    {
                        "href": "%(host)s/openstack/flavors/1",
                        "rel": "bookmark"
                    }
                ]
            },
            "hostId": "%(hostid)s",
            "metadata": {
                "My Server Name": "Apache1"
            }
    }]
}
