# -*- coding: utf-8 -*-

"""
httpbin.core
~~~~~~~~~~~~

This module provides the core HttpBin experience.
"""

import base64
import json
import os
import random
import time
import uuid
import argparse

import werkzeug
from werkzeug import Response, Request
from six.moves import range as xrange
from werkzeug.datastructures import WWWAuthenticate, MultiDict
from werkzeug.http import http_date
from werkzeug.wrappers import BaseResponse
from werkzeug.http import parse_authorization_header
from werkzeug.exceptions import HTTPException, MethodNotAllowed
import jinja2
from raven.contrib.flask import Sentry

from . import filters
from .helpers import get_dict, check_basic_auth, status_code, get_headers
# from .helpers import status_code, get_dict, get_request_range, check_digest_auth, \
    # secure_cookie, H, ROBOT_TXT, ANGRY_ASCII, parse_multi_value_header, next_stale_after_value, \
    # digest_challenge_response
from .utils import weighted_choice
from .structures import CaseInsensitiveDict

ENV_COOKIES = (
    '_gauges_unique',
    '_gauges_unique_year',
    '_gauges_unique_month',
    '_gauges_unique_day',
    '_gauges_unique_hour',
    '__utmz',
    '__utma',
    '__utmb'
)

def jsonify(*args, **kwargs):
    if args and kwargs:
        raise TypeError(
            'jsonify() behavior undefined when passed both args and kwargs')
    elif len(args) == 1:  # single args are passed directly to dumps()
        data = args[0]
    else:
        data = args or kwargs

    response = Response(
        (json.dumps(data), '\n'),
        mimetype="application/json")

    if not response.data.endswith(b'\n'):
        response.data += b'\n'
    return response

# Prevent WSGI from correcting the casing of the Location header
BaseResponse.autocorrect_location_header = False

# Find the correct template folder when running from a different location
tmpl_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'templates')


class UrlMap(werkzeug.routing.Map):
    def expose(self, rule, methods=['GET'], **kwargs):
        def _inner(func):
            self.add(
                werkzeug.routing.Rule(rule, methods=methods, endpoint=func))
            return func
        return _inner


jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader([tmpl_dir]))
url_map = UrlMap([])


# -----------
# Middlewares
# -----------


def set_cors_headers(request, response):
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    response.headers['Access-Control-Allow-Credentials'] = 'true'

    if request.method == 'OPTIONS':
        # Both of these headers are only used for the "preflight request"
        # http://www.w3.org/TR/cors/#access-control-allow-methods-response-header
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, PATCH, OPTIONS'
        response.headers['Access-Control-Max-Age'] = '3600'  # 1 hour cache
        if request.headers.get('Access-Control-Request-Headers') is not None:
            response.headers['Access-Control-Allow-Headers'] = request.headers['Access-Control-Request-Headers']
    return response


def cors_middleware(func):
    def _inner(request):
        response = func(request)
        response = set_cors_headers(request, response)
        return response
    return _inner


@Request.application
@cors_middleware
def app(request):
    adapter = url_map.bind_to_environ(request.environ)
    map_adapter = url_map.bind_to_environ(request.environ)
    request.url_for = map_adapter.build

    try:
        endpoint, values = adapter.match()
        return endpoint(request, **values)
    except MethodNotAllowed as e:
        if request.method == "OPTIONS":
            methods = adapter.allowed_methods()
            response = Response()
            response.allow.update(methods)
            return response
        else:
            return e.get_response()
    except HTTPException as e:
        return e.get_response()


def render(request, template_name, **kwargs):
    template = jinja_env.get_template(template_name)
    body = template.render(
        request=request,
        url_for=request.url_for,
        **kwargs)
    response = Response(body, content_type="text/html; charset=utf-8")
    return response


# Send app errors to Sentry.
if 'SENTRY_DSN' in os.environ:
    sentry = Sentry(app, dsn=os.environ['SENTRY_DSN'])

# Set up Bugsnag exception tracking, if desired. To use Bugsnag, install the
# Bugsnag Python client with the command "pip install bugsnag", and set the
# environment variable BUGSNAG_API_KEY. You can also optionally set
# BUGSNAG_RELEASE_STAGE.
if os.environ.get("BUGSNAG_API_KEY") is not None:
    try:
        import bugsnag
        import bugsnag.flask
        release_stage = os.environ.get("BUGSNAG_RELEASE_STAGE") or "production"
        bugsnag.configure(api_key=os.environ.get("BUGSNAG_API_KEY"),
                          project_root=os.path.dirname(os.path.abspath(__file__)),
                          use_ssl=True, release_stage=release_stage,
                          ignore_classes=['werkzeug.exceptions.NotFound'])
        bugsnag.flask.handle_exceptions(app)
    except:
        app.logger.warning("Unable to initialize Bugsnag exception handling.")

# ------
# Routes
# ------


@url_map.expose('/user-agent')
def view_user_agent(request):
    """Returns User-Agent."""
    headers = get_headers(request)
    return jsonify({'user-agent': headers['user-agent']})


@url_map.expose('/get', methods=('GET',))
def view_get(request):
    """Returns GET Data."""
    return jsonify(get_dict(request, 'url', 'args', 'headers', 'origin'))


@url_map.expose('/anything', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'TRACE'])
@url_map.expose('/anything/<path:anything>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'TRACE'])
def view_anything(request, anything=None):
    """Returns request data."""

    return jsonify(get_dict(request, 'url', 'args', 'headers', 'origin', 'method', 'form', 'data', 'files', 'json'))


@url_map.expose('/post', methods=('POST',))
def view_post(request):
    """Returns POST Data."""
    return jsonify(get_dict(
        request,
        'url', 'args', 'form', 'data', 'origin', 'headers', 'files', 'json'))


@url_map.expose('/response-headers', methods=['GET', 'POST'])
def response_headers(request):
    """Returns a set of response headers from the query string """
    headers = MultiDict(request.args.items(multi=True))
    response = jsonify(list(headers.lists()))

    while True:
        original_data = response.data
        d = {}
        for key in response.headers.keys():
            value = response.headers.get_all(key)
            if len(value) == 1:
                value = value[0]
            d[key] = value
        response = jsonify(d)
        for key, value in headers.items(multi=True):
            response.headers.add(key, value)
        response_has_changed = response.data != original_data
        if not response_has_changed:
            break
    return response


@url_map.expose('/base64/<value>')
def decode_base64(request, value):
    """Decodes base64url-encoded string"""
    encoded = value.encode('utf-8')  # base64 expects binary string as input
    response = Response(base64.urlsafe_b64decode(encoded).decode('utf-8'))
    return response


@url_map.expose('/basic-auth/<user>/<passwd>')
def basic_auth(request, user='user', passwd='passwd'):
    """Prompts the user for authorization using HTTP Basic Auth."""

    if not check_basic_auth(request, user, passwd):
        return status_code(401)

    return jsonify(authenticated=True, user=user)


@url_map.expose('/gzip')
@filters.gzip
def view_gzip_encoded_content(request):
    """Returns GZip-Encoded Data."""
    return jsonify(
        get_dict(
            request, 'origin', 'headers', method=request.method, gzipped=True))


@url_map.expose('/brotli')
@filters.brotli
def view_brotli_encoded_content(request):
    """Returns Brotli-Encoded Data."""
    return jsonify(
        get_dict(
            request, 'origin', 'headers', method=request.method, brotli=True))
