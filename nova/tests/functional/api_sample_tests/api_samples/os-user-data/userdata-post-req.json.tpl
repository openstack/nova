{
    "server" : {
        "name" : "new-server-test",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "1",
        "metadata" : {
            "My Server Name" : "Apache1"
        },
        "user_data" : "%(user_data)s"
    }
}
