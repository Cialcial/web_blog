#! /usr/bin/env python3
# encoding = utf-8

#导入异步工具包
import asyncio, os, inspect, logging, functools
#导入网页处理工具包
from urllib import parse
#导入底层web框架
from aiohttp import web

from apis import APIError

#将函数映射为url处理函数，使得get函数附带url信息
def get(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

#将函数映射为URL处理函数，使得post函数附带URL信息
def post(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'POST' #保存方法信息
        wrapper.__route__ = path #保存路径信息
        return wrapper
    return decorator

#运用inspect模块，创建几个函数用以获取URL处理函数与request参数之间的关系
#收集没有默认值的命名关键字参数
def get_required_kw_args(fn): 
    args = []
    params = inspect.signature(fn).parameters 
    for name,param in params.items():
        if str(param.kind) == 'KEKWORD_ONLY' and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

#获取命名关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name,param in params.items():
        if str(param.kind) == 'KEYWORD_ONLY':
            args.append(name)
    return tuple(args)

#判断是都有命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

#判断是否有可变关键字参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

#判断是否含有名为'request'的参数，且该参数为最后一个参数
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name,param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function:%s%s'%(fn.__name__,str(sig)))
    return found   

#封装一个URL处理函数
#RequestHandler本来是一个类，但因为定义了__call__方法，因此将这个类的实例视为函数
#该函数从request中获取必要的参数，之后调用URL函数，最后将结果转换为web.Response对象
class RequestHandler(object):

    def __init__(self,app,fn):
        self._app = app
        self._func = fn
        self._has_request_arg =has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    async def __call__(self,request):
        kw = None
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            #判断客户端发来的方法是否为post
            if request.method == 'POST': 
                if not request.content_type:
                    return web.HTTPBadRequest(text='Missing Content-Type.')
                ct = request.content_type.lower()
                print('this is ct',ct)
                if ct.startswith('application/json'):
                    params = await request.json()
                    if not isinstance(params,dict):
                        return web.HTTPBadRequest(text='JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type:%s'%request.content-type)
            if request.method == 'GET':
                qs = request.query_string
                print('this is qs',qs)
                if qs:
                    kw = dict()
                    for k,v in parse.parse_qs(qs,True).items():
                        kw[k] = v[0]
                    print('this is kw',kw)
        if kw is None:
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_arg and self._named_kw_args:
                copy = dict()
                for name in self._named_kw_args:
                    if name in self._named_kw_args:
                        if name in kw:
                            copy[name] = kw[name]
                kw = copy
            for k,v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s'%k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s'% name)
        logging.info('call with args: %s'%str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error = e.error,data= e.data,message = e.message)
#添加静态文件夹的路径
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),'static')
    app.router.add_static('/static/',path)
    logging.info('add static %s => %s' % ('/static/',path))

#用于注册一个URL处理函数
def add_route(app,fn):
    method = getattr(fn,'__method__',None)
    path = getattr(fn,'__route__',None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.'%str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)'%(method,path,fn.__name__,','.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method,path,RequestHandler(app,fn))

#由于add_route函数会用很多次，所以这里再定义一个函数用于批量注册URL处理函数
def add_routes(app,module_name):
    n = module_name.rfind('.')
    if n == (-1):
        mod = __import__(module_name,globals(),locals())
    else:
        name = module_name[n+1:]
        mod = getattr(__import__(module_name[:n],globals(),locals(),[name]),name)
    for attr in dir(mod):
        if attr.startswith('_'):
            continue
        fn = getattr(mod,attr)
        if callable(fn):
            method = getattr(fn,'__method__',None)
            path = getattr(fn,'__route__',None)
            if method and path:
                add_route(app,fn)