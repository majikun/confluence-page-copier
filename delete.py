#!/usr/bin/env python
# coding=utf-8
import os
import re
import urllib
import shutil
import logging
import tempfile
import argparse
import sys

import requests
from PythonConfluenceAPI import ConfluenceAPI
from boltons.cacheutils import LRU, cachedmethod

defaultencoding = 'utf-8'
if sys.getdefaultencoding() != defaultencoding:
    reload(sys)
    sys.setdefaultencoding(defaultencoding)

__author__ = 'Grigory Chernyshev <systray@yandex.ru>'


class ConfluenceAPIDryRunProxy(ConfluenceAPI):
    MOD_METH_RE = re.compile(r'^(create|update|convert|delete)_.*$')

    def __init__(self, username, password, uri_base, user_agent=ConfluenceAPI.DEFAULT_USER_AGENT, dry_run=False):
        super(ConfluenceAPIDryRunProxy, self).__init__(username, password, uri_base, user_agent)
        self._dry_run = dry_run
        self.log = logging.getLogger('api-proxy')

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        is_dry = object.__getattribute__(self, '_dry_run')
        if is_dry and hasattr(attr, '__call__') and self.MOD_METH_RE.match(name):
            def dry_run(*args, **kwargs):
                func_args = list()
                if args:
                    func_args.extend(str(a) for a in args)
                if kwargs:
                    func_args.extend('%s=%s' % (k, v) for k, v in kwargs.items())

                # self.log.info("[DRY-RUN] {name}({func_args})".format(name=name, func_args=', '.join(func_args)))

            return dry_run
        else:
            return attr


class ConfluencePageCopier(object):
    EXPAND_FIELDS = 'body.storage,space,ancestors,version'
    TITLE_FIELD = '{title}'
    COUNTER_FIELD = '{counter}'
    DEFAULT_TEMPLATE = '{t} ({c})'.format(t=TITLE_FIELD, c=COUNTER_FIELD)

    def __init__(self, username, password, uri_base, dry_run=False):
        self.log = logging.getLogger('confl-copier')
        self._dry_run = dry_run
        self._client = ConfluenceAPIDryRunProxy(
            username=username,
            password=password,
            uri_base=uri_base,
            dry_run=dry_run
        )

        self._cache = LRU()

    def delete(
            self,
            src,
            depth=None
    ):

        source = self._find_page(depth=depth, **src)

        # recursively delete children
        children = self._client.get_content_children_by_type(content_id=source['id'], child_type='page')

        if children and children.get('results'):
            depth += 1

            for child in children['results']:
                self.delete(
                    src={'content_id': child['id'], 'title':child['title']},
                    depth=depth
                )

        self.log.debug("delete page id '{}' depth {} title {}".format(src['content_id'], depth, src['title']))
        self._client.delete_content_by_id(src['content_id'])

    @cachedmethod('_cache')
    def _find_page(self, depth=None, content_id=None, space_key=None, title=None):

        if content_id:
            content = self._client.get_content_by_id(
                content_id=content_id,
                expand=self.EXPAND_FIELDS
            )
            return content


def init_args():
    parser = argparse.ArgumentParser(description='Script for smart copying Confluence pages.')
    parser.add_argument('--log-level',
                        choices=filter(lambda item: type(item) is not int, logging._levelNames.values()),
                        default='DEBUG', help='Log level')

    parser.add_argument(
        '--username',
        default='admin',
        help='Username for Confluence.'
    )

    parser.add_argument(
        '--password',
        default='admin',
        help='Password for Confluence.'
    )

    parser.add_argument(
        '--endpoint',
        default='http://localhost:1990/confluence',
        help='Confluence endpoine.'
    )

    parser.add_argument(
        '--src-id',
        help=(
            'Source page id. Using this parameter precisely determines the page (if it exists). '
            'In case this parameter is set, `--src-space` and `--src-title` parameters are ignored.'
        )
    )

    return parser.parse_args()


if __name__ == '__main__':
    args = init_args()
    logging.basicConfig(level=logging._levelNames.get(args.log_level))
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("PythonConfluenceAPI.api").setLevel(logging.WARNING)

    copier = ConfluencePageCopier(
        username=args.username,
        password=args.password,
        uri_base=args.endpoint,
        dry_run=args.dry_run
    )

    copier.delete(
        src={
            'title': args.src_title,
            'space_key': args.src_space,
            'content_id': args.src_id,
        },
        depth=1
    )
