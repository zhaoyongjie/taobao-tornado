#!/usr/bin/env python
# coding=utf-8

import sys
import logging
import urllib
import time
import hmac
import mimetypes
import itertools
import os.path

import tornado.httpclient
import tornado.gen
from tornado.escape import json_decode
from tornado.httputil import url_concat

logger = logging.getLogger()
http = tornado.httpclient.AsyncHTTPClient()

class Top(object):
    def __init__(self, key, secret, session):
        self.key = key
        self.secret = secret
        self.session = session

    @tornado.gen.coroutine
    def fetch(self, **kwargs):
        """Tornado Async HTTP request for TOP(taobao open platform)

        usage:

        class Test(tornado.web.RequestHandler):
            @tornado.gen.coroutine
            def get(self):
                response = yield top(method="taobao.items.onsale.get",
                                     return_parameters="items.item",
                                     fields="iid,title")
        """
        return_parameters = kwargs.get('return_parameters')
        method = kwargs.get('method')
        kwargs.pop(return_parameters, None)
        kwargs.pop(method, None)
        app_parameters = kwargs

        rest_url = "https://eco.taobao.com/router/rest"
        sys_parameters = {
            "method": method,
            "timestamp": str(long(time.time() * 1000)),
            "format": "json",
            "app_key": self.key,
            "v": "2.0",
            "session": self.session,
            "sign_method": "hmac",
        }

        sign_parameter = sys_parameters.copy()
        sign_parameter.update(app_parameters)
        #file field不用签名
        sign_parameter = dict(filter(lambda x: not isinstance(x[1], file), sign_parameter.iteritems()))
        #传入的参数如果是数字(包括浮点数), 转换成字符串，用于拼接字符串
        sign_string = "".join(map(str, reduce(lambda x,y: x+y, sorted(sign_parameter.iteritems()))))
        sys_parameters['sign'] = hmac.new(str(self.secret), str(sign_string)).hexdigest().upper()

        url = url_concat(rest_url, sys_parameters)
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
            "Connection": "Keep-Alive",
        }

        #如果找到任何一个参数是file object 用表单编码
        if any(isinstance(e, file) for e in app_parameters.values()):
            form = EncodeFormData()
            for k, v in app_parameters.items():
                form.add_field(k, v)
            body = str(form)
            headers['Content-type'] = form.get_content_type()
        else:
            body = urllib.urlencode(app_parameters)

        #如果发生错误直接raise except，不会再后续执行
        try:
            response = yield http.fetch(url, method="POST",
                                        headers=headers, body=body)
        except:
            logger.error(sys.exc_info())
            raise tornado.gen.Return(None)

        json_obj = json_decode(response.body)
        if "error_response" in json_obj:
            #如果rest请求抛出错误，则返回None，并且logging出error
            # logger.error(json_obj)
            raise tornado.gen.Return(json_obj)
        else:
            #根据传入的return_parameters返回，如果给出的return_parameters找不到，返回None
            response_key = "{}_response".format(method.replace("taobao.","").replace(".","_"))
            if return_parameters:
                try:
                    return_obj = reduce(dict.get,
                                        return_parameters.split("."), json_obj[response_key])
                except:
                    logger.error(sys.exc_info())
                    raise tornado.gen.Return(None)
                raise tornado.gen.Return(return_obj)
            else:
                raise tornado.gen.Return(json_obj[response_key])


class EncodeFormData(object):
    def __init__(self):
        self.form_fields = []
        self.files = []
        self.boundary = "---------THIS_IS_THE_BOUNDARY"
        return

    def get_content_type(self):
        return 'multipart/form-data; boundary=%s' % self.boundary

    def add_field(self, field_name, value):
        if isinstance(value, file):
            body = value.read()
            mimetype = mimetypes.guess_type(value.name)[0] or 'application/octet-stream'
            file_name = os.path.basename(value.name)
            self.files.append((field_name, file_name, mimetype, body))
        else:
            self.form_fields.append((field_name, value))
        return

    def __str__(self):
        """Return a string representing the form data, including attached files."""
        parts = []
        part_boundary = '--' + self.boundary

        # Add the form fields
        parts.extend(
            [ part_boundary,
              'Content-Disposition: form-data; name="%s"' % field_name,
              'Content-Type: text/plain; charset=UTF-8',
              '',
              value,
            ]
            for field_name, value in self.form_fields
            )

        # Add the files to upload
        parts.extend(
            [ part_boundary,
              'Content-Disposition: file; name="%s"; filename="%s"' % \
                 (field_name, file_name),
              'Content-Type: %s' % content_type,
              'Content-Transfer-Encoding: binary',
              '',
              body,
            ]
            for field_name, file_name, content_type, body in self.files
            )

        # Flatten the list and add closing boundary marker,
        # then return CR+LF separated data
        flattened = list(itertools.chain(*parts))
        flattened.append('--' + self.boundary + '--')
        flattened.append('')
        return '\r\n'.join(flattened)