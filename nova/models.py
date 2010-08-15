from sqlalchemy.orm import relationship, backref, validates
from sqlalchemy import Table, Column, Integer, String, MetaData, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from nova import auth

Base = declarative_base()

class Image(Base):
    __tablename__ = 'images'
    user_id = Column(String)#, ForeignKey('users.id'), nullable=False)
    project_id = Column(String)#, ForeignKey('projects.id'), nullable=False)

    id = Column(String, primary_key=True)
    image_type = Column(String)
    public = Column(Boolean, default=False)
    state = Column(String)
    location = Column(String)
    arch = Column(String)
    default_kernel_id = Column(String)
    default_ramdisk_id = Column(String)

    created_at = Column(DateTime)
    updated_at = Column(DateTime) # auto update on change FIXME

    @validates('image_type')
    def validate_image_type(self, key, image_type):
        assert(image_type in ['machine', 'kernel', 'ramdisk', 'raw'])

    @validates('state')
    def validate_state(self, key, state):
        assert(state in ['available', 'pending', 'disabled'])

    @validates('default_kernel_id')
    def validate_kernel_id(self, key, val):
        if val != 'machine':
            assert(val is None)

    @validates('default_ramdisk_id')
    def validate_ramdisk_id(self, key, val):
        if val != 'machine':
            assert(val is None)

class Network(Base):
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True)
    bridge = Column(String)
    vlan = Column(String)
    kind = Column(String)
    #vpn_port = Column(Integer)
    project_id = Column(String) #, ForeignKey('projects.id'), nullable=False)

class PhysicalNode(Base):
    __tablename__ = 'physical_nodes'
    id = Column(Integer, primary_key=True)

class Instance(Base):
    __tablename__ = 'instances'
    id = Column(Integer, primary_key=True)

    user_id = Column(String) #, ForeignKey('users.id'), nullable=False)
    project_id = Column(String) #, ForeignKey('projects.id'))

    @property
    def user(self):
        return auth.manager.AuthManager().get_user(self.user_id)

    @property
    def project(self):
        return auth.manager.AuthManager().get_project(self.project_id)

    image_id = Column(Integer, ForeignKey('images.id'), nullable=False)
    kernel_id = Column(String, ForeignKey('images.id'), nullable=True)
    ramdisk_id = Column(String, ForeignKey('images.id'), nullable=True)

    launch_index = Column(Integer)
    key_name = Column(String)
    key_data = Column(Text)
    security_group = Column(String)

    state = Column(Integer)
    state_description = Column(String)

    hostname = Column(String)
    physical_node_id = Column(Integer)

    instance_type = Column(Integer)

    user_data = Column(Text)

    def set_state(self, state_code, state_description=None):
        from nova.compute import power_state
        self.state = state_code
        if not state_description:
            state_description = power_state.name(state_code)
        self.state_description = state_description

#    ramdisk = relationship(Ramdisk, backref=backref('instances', order_by=id))
#    kernel = relationship(Kernel, backref=backref('instances', order_by=id))
#    project = relationship(Project, backref=backref('instances', order_by=id))

#TODO - see Ewan's email about state improvements
    # vmstate_state = running, halted, suspended, paused
    # power_state = what we have
    # task_state = transitory and may trigger power state transition

    #@validates('state')
    #def validate_state(self, key, state):
    #    assert(state in ['nostate', 'running', 'blocked', 'paused', 'shutdown', 'shutoff', 'crashed'])

class Volume(Base):
    __tablename__ = 'volumes'
    id = Column(Integer, primary_key=True)
    shelf_id = Column(Integer)
    blade_id = Column(Integer)


engine = None
def create_engine():
    global engine
    if engine is not None:
       return engine
    from sqlalchemy import create_engine
    engine = create_engine('sqlite:///:memory:', echo=True)
    Base.metadata.create_all(engine)
    return engine

def create_session(engine=None):
    if engine is None:
        engine = create_engine()
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    return Session()

if __name__ == '__main__':
    engine = create_engine()
    session = create_session(engine)

    instance = Instance(image_id='as', ramdisk_id='AS', user_id='anthony')
    user = User(id='anthony')
    session.add(instance)
    session.commit()

