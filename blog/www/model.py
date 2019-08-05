#! /usr/bin/env python3
# encoding = utf-8

#uuid: universally unique indentifier通用唯一标识符
#uuid模块提供uuid类和函数uuid1(),uuid3(),uuid(4),uuid5()来生成各个版本的uuid
import time,uuid

import asyncio

import orm

from orm import Model,StringField,BooleanField,FloatField,TextField

def next_id():
    return '%015d%s000'%(int(time.time()*1000),uuid.uuid4().hex)

class User(Model):
    __table__='users'

    id = StringField(primary_key = True,default=next_id,ddl='varchar(50)')
    email = StringField(ddl='varchar(50)')
    password = StringField(ddl='varchar(50)')
    admin = BooleanField()
    name = StringField(ddl='varchar(50)')
    image = StringField(ddl='varchar(500)')
    created_at = FloatField(default=time.time)

class Blog(Model):
    __table__='blogs'

    id = StringField(primary_key=True,default=next_id,ddl='varchar(50)')
    user_id = StringField(ddl='varchar(50)')
    user_name = StringField(ddl='varcahr(50)')
    user_image = StringField(ddl='varchar(500)')
    name = StringField(ddl='varchar(50)')
    summary = StringField(ddl='varchar(200)')
    content = TextField()
    created_at = FloatField(default=time.time)

class Comment(Model):
    __table__='comments'

    id = StringField(primary_key=True,default=next_id,ddl='varchar(50)')
    blog_id = StringField(ddl='varchar(50)')
    user_id = StringField(ddl='varchar(50)')
    user_name = StringField(ddl='varchar(50)')
    user_image = StringField(ddl='varchar(500)')
    content = TextField()
    created_at = FloatField(default=time.time)

async def test(loop):
    await orm.create_pool(loop=loop,user='www-data', password='www-data', db='awesome')

    u = User(name='Test', email='xyz@example.combs', password='1234567890', image='about:blank')

    await u.save()

    
    # await orm.close_pool()

# def runEventLoop():
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     loop.run_until_complete(test(loop))
#     loop.close()

if __name__ == "__main__":
    # oldloop = asyncio.get_event_loop()
    # runEventLoop()
    # asyncio.set_event_loop(oldloop)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(test(loop))
    loop.close()


