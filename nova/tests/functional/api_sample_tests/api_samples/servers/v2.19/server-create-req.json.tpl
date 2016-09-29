{
    "server" : {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "name" : "new-server-test",
        "description" : "new-server-description",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "%(host)s/flavors/1",
        "metadata" : {
            "My Server Name" : "Apache1"
        }
    }
}
