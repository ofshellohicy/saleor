"""WSGI config for Saleor project.

This module contains the WSGI application used by Django's development server
and any production WSGI deployments. It should expose a module-level variable
named ``application``. Django's ``runserver`` and ``runfcgi`` commands discover
this application via the ``WSGI_APPLICATION`` setting.

Usually you will have the standard Django WSGI application here, but it also
might make sense to replace the whole Django WSGI application with a custom one
that later delegates to the Django one. For example, you could introduce WSGI
middleware here, or combine a Django application with an application of another
framework.
"""

import os
from io import BytesIO
from django.core.wsgi import get_wsgi_application
from django.conf import settings
from django.utils.functional import SimpleLazyObject

from saleor.wsgi.health_check import health_check

# 1. 基础配置
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saleor.settings")

# 2. wsgi.input中间件保持不变
def wsgi_input_middleware(application):
    """处理wsgi.input的中间件"""
    def middleware(environ, start_response):
        if 'wsgi.input' in environ:
            input_stream = environ['wsgi.input']
            if hasattr(input_stream, 'read'):
                body = input_stream.read()
                environ['wsgi.input'] = BytesIO(body)

        if 'CONTENT_LENGTH' in environ:
            try:
                environ['CONTENT_LENGTH'] = int(environ['CONTENT_LENGTH'])
            except (ValueError, TypeError):
                environ['CONTENT_LENGTH'] = 0

        return application(environ, start_response)
    return middleware

# 3. 预热功能
def get_allowed_host_lazy():
    return settings.ALLOWED_HOSTS[0]

def warmup_application(app):
    """预热应用，确保首次请求响应迅速"""
    environ = {
        "wsgi.errors": BytesIO(),
        "wsgi.url_scheme": "http",
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
        "REQUEST_METHOD": "POST",
        "SERVER_NAME": SimpleLazyObject(get_allowed_host_lazy),
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "PATH_INFO": "/graphql/",
        "CONTENT_TYPE": "application/json",
        "HTTP_ACCEPT": "application/json",
        "CONTENT_LENGTH": "2",
        "wsgi.input": BytesIO(b"{}")
    }

    def start_response(status, headers):
        pass

    try:
        list(app(environ, start_response))
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Warmup request failed: {str(e)}", exc_info=True)

def cors_middleware(application):
    """
    处理CORS预检请求的中间件
    """
    def middleware(environ, start_response):
        # 1. 获取请求源
        origin = environ.get('HTTP_ORIGIN')

        def cors_response(status, response_headers):
            # 2. 设置CORS响应头
            if origin:
                cors_headers = [
                    ('Access-Control-Allow-Origin', origin),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization, authorization-bearer'),
                    ('Access-Control-Max-Age', '3600'),
                    ('Access-Control-Expose-Headers', 'Content-Type, Authorization'),
                ]
                response_headers.extend(cors_headers)
            return start_response(status, response_headers)

        # 3. 处理OPTIONS预检请求
        if environ.get('REQUEST_METHOD') == 'OPTIONS':
            response_headers = []
            if origin:
                cors_response('200 OK', response_headers)
                return [b'']
            return [b'']

        return application(environ, cors_response)
    return middleware

# 4. 应用初始化和中间件配置
django_application = get_wsgi_application()
application = wsgi_input_middleware(django_application)
application = cors_middleware(application)  # 添加CORS中间件
application = health_check(application, "/health/")

# 5. 执行预热
try:
    warmup_application(application)
except Exception as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Application warmup failed: {str(e)}")

