#! /usr/bin/env pyhton3
# encoding = utf-8

import asyncio, logging

import aiomysql

def log(sql,args=()):
    logging.info('SQL: %s'%sql)

#创建连接池，每个http请求都可以直接从连接池中直接获取数据连接，好处是不必频繁地打开和关闭数据库连接
async def create_pool(loop,**kw):
    logging.info('create database connection pool')
    #连接池由全局变量__pool存储
    global __pool 
    #读取传入参数**kw中的值区创建一个连接池
    __pool = await aiomysql.create_pool(
        #设置默认值
        #host：连接db server的主机名，默认为本地主机localhost
        #port：指定db server的连接端口，默认3306
        #user：连接数据库的用户名，默认当前用户
        #password：数据库连接密码，没有默认值
        #db：连接的数据库名，没有默认值
        #charset：连接编码
        host = kw.get('host','localhost'),
        port = kw.get('port',3306),
        user = kw['user'],
        password=kw['password'],
        db = kw['db'],
        charset = kw.get('charset','utf8'),
        autocommit = kw.get('autocommit',True), #默认自动提交事物
        maxsize = kw.get('maxsize',10),
        minsize = kw.get('minisize',1),
        loop = loop
    )

#sql: sql语句
#args: sql语句中的参数
#size: 要查询的数量
async def select(sql,args,size = None):
    log(sql)
    global __pool
    #异步打开__pool并赋值给conn
    with (await __pool) as conn:
        cur = await conn.cursor(aiomysql.DictCursor)
        #sql语句的占位符是？而MySQL的占位符是%s,所以在这里进行替换
        await cur.execute(sql.replace('?','%s'),args or ())
        #如果传入size参数，就返回该数量的记录，否则返回全部记录
        if size:
            rs = await cur.fetchmany(size)
        else:
            rs = await cur.fetchall()
        await cur.close()
        logging.info('rows returned:%s'% len(rs))
        print(rs)
        return rs #返回结果集

#delete、insert、update操作都只需要返回影响的行数，而上面的select需要返回结果
async def execute(sql,args):
    log(sql)
    with (await __pool) as conn:
        try:
            cur = await conn.cursor()
            await cur.execute(sql.replace('?','%s'),args)
            affected = cur.rowcount
            await cur.close()
        except BaseException as e:
            raise
        return affected

#用来计算需要拼接多少个占位符
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)

class Field(object):

    def __init__(self,name,column_type,primary_key,default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s,%s:%s>'%(self.__class__.__name__,self.column_type,self.name)

#定义数据库中五个存储类型：string、boolean、intager、float、text
class StringField(Field):
    def __init__(self,name = None,primary_key=False,default = None,ddl='varchar(100)'):
        super().__init__(name,ddl,primary_key,default)

class BooleanField(Field):
    #布尔类型不可以作为主键
    def __init__(self,name=None,default = False):
        super().__init__(name,'boolean',False,default)

class IntegerField(Field):
    def __init__(self,name=None,primary_key=False,default = 0):
        super().__init__(name,'bigint',primary_key,default)

class FloatField(Field):
    def __init__(self,name=None,primary_key=False,default=0.0):
        super().__init__(name,'real',primary_key,default)

class TextField(Field):
    def __init__(self,name=None,default=None):
        super().__init__(name,'text',False,default)

class ModelMetabase(type):
    #创建模型与表映射的基类
    #name类名、bases父类、attrs类的属性列表
    def __new__(cls,name,bases,attrs):
        if name=='Model':
            return type.__new__(cls,name,bases,attrs)
        #获取表名，没有表名将类名作为表名
        tableName =attrs.get('__table__',None) or name
        logging.info('found model:%s(table:%s'%(name,tableName))
        #获取所有的类属性和主键名
        mappings = dict() #存储属性名和字段的映射关系
        fields = [] #存储所有非主键的属性
        primaryKey = None #存储主键的属性
        #遍历attrs（类的所有属性）
        for k,v in attrs.items():
            #如果v是已定义的字段类型
            if isinstance(v,Field):
                logging.info(' found mapping: %s ==> %s'% (k,v))
                #存储映射关系
                mappings[k]=v
                #如果该属性是主键
                if v.primary_key:
                    #如果主键已存在
                    if primaryKey:
                        raise StandardError('Duplicate primary key for field: %s'% k)
                    primaryKey = k
                else:
                    fields.append(k) #不是主键就存到fields里
        #遍历完成没有找到主键
        if not primaryKey:
            raise StandardError('Primary key not found')
        #情况attrs
        for k in mappings.keys():
            attrs.pop(k)
        #将fields中的属性名以‘属性名’的方式装饰起来
        escaped_fields = list(map(lambda f: '`%s`'%f,fields))
        attrs['__mappings__']=mappings #保存属性和字段的映射关系
        attrs['__table__']=tableName #保存表名
        attrs['__primary_key__']=primaryKey #保存主键属性名
        attrs['__fields__']=fields #除主键以外的属性名
        #构造默认的select，insert，update，delete语句
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)

#定义model：所有ORM映射的基类
#Model从dict继承，具备dict所以属性，同时实现了__getattr__()和__setattr__()
class Model(dict,metaclass = ModelMetabase):
    def __init__(self,**kw):
        super(Model,self).__init__(**kw)

    def __getattr__(self,key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'"%key)
        
    def __setattr__(self,key,value):
        self[key]=value

    def getValue(self, key):
        return getattr(self, key, None)
    
    def getValueOrDefault(self,key):
        value = getattr(self,key,None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s:%s'%(key,str(value)))
                setattr(self,key,value)
        return value 

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        #通过where查找多条记录，kw：查询条件列表
        ' find objects by where clause. '
        sql = [cls.__select__]
        #如果where存在
        if where:
            sql.append('where') #添加where关键字
            sql.append(where) #拼接where查询条件
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select count(%s) _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    async def save(self):
        #将__field__保存的除主键外的所有属性一次性传递到getValueOrDefault中获取值
        args = list(map(self.getValueOrDefault, self.__fields__))
        #获取主键值
        args.append(self.getValueOrDefault(self.__primary_key__))
        #执行insertsql
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)
