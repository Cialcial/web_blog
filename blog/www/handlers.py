#! /usr/bin/env python3
# encoding = utf-8

' url handlers '

import re, time, json, logging, hashlib, base64, asyncio

import markdown2

from aiohttp import web

from coroweb import get, post
from apis import APIValueError,APIResourceNotFoundError,Page

from model import User, Comment, Blog, next_id
from config import configs

#用于在set_cookie中命名
COOKIE_NAME = 'awesession'
#导入默认设置
_COOKIE_KEY = configs.session.secret

def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()

#选择当前页面
def get_page_index(page_str):
    p=1 #初始化页面数取整
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p<1:
        p=1
    return p

def user2cookie(user, max_age):
    '''
    Generate cookie str by user
    '''
    #build cookies string by: id-expires-sha1
    expires = str(int(time.time()+max_age))
    s = '%s-%s-%s-%s' % (user.id, user.password, expires,_COOKIE_KEY)
    L = [user.id,expires,hashlib.sha1(s.encode('utf-8')).hexdigest()]
    return '-'.join(L)

def text2html(text):
    lines = map(lambda s: '<p>%s</p>' % s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), filter(lambda s: s.strip() != '', text.split('\n')))
    return ''.join(lines)

#解析cookie
async def cookie2user(cookie_str):
    if not cookie_str:
        return None
    try:
        L = cookie_str.split('-') #拆分字符串
        if len(L) != 3:
            return None
        uid, expires, sha1 = L
        if int(expires) < time.time(): #排查是否过期
            return None
        user = await User.find(uid)
        if user is None:
            return None
        #用数据库数据生成字符串与cookie比较
        s = '%s-%s-%s-%s' % (uid, user.password, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.password = '******'
        return user
    except Exception as e:
        logging.exception(e)
        return None

@get('/')
async def index(*,page='1'):
    page_index = get_page_index(page)
    num = await Blog.findNumber('id')
    page = Page(num)
    if num == 0:
        blogs = []
    else:
        blogs = await Blog.findAll(orderBy='created_at desc', limit=(page.offset, page.limit))
    return {
        '__template__': 'blogs.html',
        'page': page,
        'blogs': blogs
    }


@get('/blog/{id}')
async def get_blog(id):
    blog = await Blog.find(id)
    comments = await Comment.findAll('blog_id=?', [id], orderBy='created_at desc')
    for c in comments:
        c.html_content = text2html(c.content)
    blog.html_content = markdown2.markdown(blog.content)
    return {
        '__template__': 'blog.html',
        'blog': blog,
        'comments': comments
    } 

@get('/register')
def register():
    return{
        '__template__':'register.html'
    }

@get('/signin')
def signin():
    return{
        '__template__':'signin.html'
    }

@get('/signout')
def signout(request):
    referer = request.headers.get('Referer')
    r = web.HTTPFound(referer or '/')
    r.set_cookie(COOKIE_NAME, '-deleted-', max_age=0, httponly=True)
    logging.info('user signed out.')
    return r

@get('/manage/')
def manage():
    return 'redirect:/manage/comments'

@get('/manage/comments')
def manage_comments(*,page='1'):
    return{
        '__template__':'manage_comments.html',
        'page_index':get_page_index(page)
    }

@get('/manage/blogs')
def manage_blogs(*,page='1'):
    return {
        '__template__':'manage_blogs.html',
        'page_index':get_page_index(page)
    }

@get('/manage/blogs/create')
def manage_create_blog():
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs'
    }

@get('/manage/blogs/edit')
def manage_blogs_edit(*,id):
    print('this is id',id)
    return {
        '__template__':'manage_blog_edit.html',
        'id': id ,
        'action':'/api/blogs/%s' % id
    }

@get('/manage/users')
def manage_users(*,page='1'):
    return {
        '__template__' : 'manage_users.html',
        'page_index':get_page_index(page)
    }

_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')

#验证登录信息的api
@post('/api/authenticate')
async def authenticate(*, email,password):
    if not email: #如果邮箱为空
        raise APIValueError('email','Invalid email')
    if not password: #如果密码为空
        raise APIValueError('password','Invalid password')
    #判断该邮箱是否已注册
    users = await User.findAll('email=?',[email])
    if len(users)==0:
        raise APIValueError('email','Email not exsit')
    user = users[0]
    #把登录信息转化格式并进行摘要算法
    sha1 = hashlib.sha1()
    sha1.update(user.id.encode('utf-8'))
    sha1.update(b':')
    sha1.update(password.encode('utf-8'))
    #与数据库的口令进行比对
    if user.password != sha1.hexdigest():
        raise APIValueError('password','Invalide password')
    #制作cookie发送给浏览器
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user,86400),max_age=86400,httponly=True)
    user.password = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r

#用户注册api
@post('/api/users')
async def api_register_user(*, email, name, password):
    if not name or not name.strip(): #如果名字为空或者为空格
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email): #如果email格式不对
        raise APIValueError('email')
    if not password or not _RE_SHA1.match(password): #如果密码格式不对
        raise APIValueError('password')
    users = await User.findAll('email=?', [email])
    if len(users) > 0: #如果邮箱已注册
        raise APIError('register:failed', 'email', 'Email is already in use.')
    #下面注册到数据库，具体过程看orm源码
    uid = next_id()
    sha1_password = '%s:%s' % (uid, password)
    user = User(id=uid, name=name.strip(), email=email, password=hashlib.sha1(sha1_password.encode('utf-8')).hexdigest(), image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    await user.save()
    #制作cookie返回浏览器
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.password = '******' #掩盖password
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r

#创建日志API
@post('/api/blogs')
async def api_create_blog(request,*,name,summary,content):
    check_admin(request)
    if not name or not name.strip():
        raise APIValueError('name','Name cannot be empty!')
    if not summary or not summary.strip():
        raise APIValueError('summary','Summary cannot be empty!')
    if not content or not content.strip():
        raise APIValueError('content','Content cannot be empty!')
    blog = Blog(user_id=request.__user__.id,user_name=request.__user__.name,user_image=request.__user__.image,name=name.strip(),summary=summary.strip(),content=content.strip())
    await blog.save()
    return blog

#重新编辑blog的API
@post('/api/blogs/{id}')
async def api_update_blog(id, request, *, name, summary, content):
    check_admin(request)
    blog = await Blog.find(id)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog.name = name.strip()
    blog.summary = summary.strip()
    blog.content = content.strip()
    await blog.update()
    return blog

#blog列表API
@get('/api/blogs')
async def api_blogs(*,page='1'):
    page_index = get_page_index(page)
    num = await Blog.findNumber('id')
    p = Page(num, page_index)
    if num ==0:
        return dict(page=p, blogs=())
    blogs = await Blog.findAll(orderBy='created_at desc',limit = (p.offset,p.limit))
    return dict(page=p,blogs=blogs)

#查看blog的API
@get('/api/blogs/{id}')
async def api_get_blog(*,id):
    blog = await Blog.find(id)
    return blog

#用户API
@get('/api/users')
async def api_get_users(*,page='1'):
    page_index = get_page_index(page)
    num = await User.findNumber('id')
    p = Page(num,page_index)
    if num == 0:
        return dict(page=p,users=())
    users = await User.findAll(orderBy='created_at desc',limit=(p.offset, p.limit))
    for u in users:
        u.password = '******'
    return dict(page=p,users=users)

#发布blog的API
@post('/api/blogs')
async def api_create_blog(request, *, name, summary, content):
    check_admin(request)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog = Blog(user_id=request.__user__.id, user_name=request.__user__.name, user_image=request.__user__.image, name=name.strip(), summary=summary.strip(), content=content.strip())
    await blog.save()
    return blog

#删除blog的API
@post('/api/blogs/{id}/delete')
async def api_delete_blog(request, *, id):
    check_admin(request)
    blog = await Blog.find(id)
    await blog.remove()
    return dict(id=id)

@get('/api/comments')
async def manage_user(*,page='1'):
    page_index = get_page_index(page)
    num = await Comment.findNumber('id')
    p = Page(num,page_index)
    if num == 0:
        return dict(page=p, comments=())
    comments = await Comment.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, comments=comments)

@post('/api/blogs/{id}/comments')
async def api_create_comment(id, request, *, content):
    user = request.__user__
    if user is None:
        raise APIPermissionError('Please signin first.')
    if not content or not content.strip():
        raise APIValueError('content')
    blog = await Blog.find(id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    comment = Comment(blog_id=blog.id, user_id=user.id, user_name=user.name, user_image=user.image, content=content.strip())
    await comment.save()
    return comment

@post('/api/comments/{id}/delete')
async def api_delete_comments(id, request):
    check_admin(request)
    c = await Comment.find(id)
    if c is None:
        raise APIResourceNotFoundError('Comment')
    await c.remove()
    return dict(id=id)