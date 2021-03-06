# -*- coding: utf-8 -*-
###############################################################################
#
# Copyright (C) 2014 Tom Kralidis (tomkralidis@gmail.com)
#
# This source is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This code is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# A copy of the GNU General Public License is available on the World Wide Web
# at <http://www.gnu.org/copyleft/gpl.html>. You can also obtain it by writing
# to the Free Software Foundation, Inc., 59 Temple Place - Suite 330, Boston,
# MA 02111-1307, USA.
#
###############################################################################

import getpass
import os
import shutil
from urllib import urlencode
from urllib2 import urlopen
import xml.etree.ElementTree as etree
import xmlrpclib
import zipfile

from paver.easy import (call_task, cmdopts, error, info, needs, options, path,
                        pushd, sh, task, Bunch)

PLUGIN_NAME = 'MetaSearch'
BASEDIR = os.path.abspath(os.path.dirname(__file__))
USERDIR = os.path.expanduser('~')

options(
    base=Bunch(
        home=BASEDIR,
        docs=path(BASEDIR) / 'docs',
        plugin=path('%s/plugin/MetaSearch' % BASEDIR),
        ui=path(BASEDIR) / 'plugin' / PLUGIN_NAME / 'ui',
        install=path('%s/.qgis2/python/plugins/MetaSearch' % USERDIR),
        ext_libs=path('plugin/MetaSearch/ext-libs'),
        tmp=path(path('%s/MetaSearch-dist' % USERDIR)),
        version=open('VERSION.txt').read().strip()
    ),
    upload=Bunch(
        host='plugins.qgis.org',
        port=80,
        endpoint='plugins/RPC2/'
    )
)


@task
def setup():
    """setup plugin dependencies"""

    if not os.path.exists(options.base.ext_libs):
        sh('pip install -r requirements.txt --target=%s' %
           options.base.ext_libs)


@task
def clean():
    """clean environment"""

    if os.path.exists(options.base.install):
        if os.path.islink(options.base.install):
            os.unlink(options.base.install)
        else:
            shutil.rmtree(options.base.install)
    if os.path.exists(options.base.tmp):
        shutil.rmtree(options.base.tmp)
    if os.path.exists(options.base.ext_libs):
        shutil.rmtree(options.base.ext_libs)
    with pushd(options.base.docs):
        sh('%s clean' % sphinx_make())
    for ui_file in os.listdir(options.base.ui):
        if ui_file.endswith('.py') and ui_file != '__init__.py':
            os.remove(options.base.plugin / 'ui' / ui_file)
    sh('git clean -dxf')


@task
def build_qt_files():
    """build ui files"""

    pyfiles = []
    uifiles = []
    trfiles = []

    # compile .ui files into Python
    for ui_file in os.listdir(options.base.ui):
        if ui_file.endswith('.ui'):
            ui_file_basename = os.path.splitext(ui_file)[0]
            sh('pyuic4 -o %s/ui/%s.py %s/ui/%s.ui' % (options.base.plugin,
               ui_file_basename, options.base.plugin, ui_file_basename))

    # create .pro file
    for root, dirs, files in os.walk(options.base.plugin / 'dialogs'):
        for pfile in files:
            if pfile.endswith('.py'):
                filepath = os.path.join(root, pfile)
                relpath = os.path.relpath(filepath, BASEDIR)
                pyfiles.append(relpath)
    for root, dirs, files in os.walk(options.base.plugin / 'ui'):
        for pfile in files:
            if pfile.endswith('.ui'):
                filepath = os.path.join(root, pfile)
                relpath = os.path.relpath(filepath, BASEDIR)
                uifiles.append(relpath)

    locale_dir = options.base.plugin / 'locale'
    for loc_dir in os.listdir(locale_dir):
        filepath = os.path.join(locale_dir, loc_dir, 'LC_MESSAGES', 'ui.qm')
        relpath = os.path.relpath(filepath, BASEDIR)
        trfiles.append(relpath)

    with open('%s.pro' % PLUGIN_NAME, 'w') as pro_file:
        pro_file.write('SOURCES=%s\n' % ' '.join(pyfiles))
        pro_file.write('FORMS=%s\n' % ' '.join(uifiles))
        pro_file.write('TRANSLATIONS=%s\n' % ' '.join(trfiles))


@task
@needs('build_qt_files')
def install():
    """install plugin into user QGIS environment"""

    plugins_dir = path(USERDIR) / '.qgis2/python/plugins'

    if os.path.exists(options.base.install):
        if os.path.islink(options.base.install):
            os.unlink(options.base.install)
        else:
            shutil.rmtree(options.base.install)

    if not os.path.exists(plugins_dir):
        raise OSError('The directory %s does not exist.' % plugins_dir)
    if not hasattr(os, 'symlink'):
        shutil.copytree(options.base.plugin, options.base.install)
    elif not os.path.exists(options.base.install):
        os.symlink(options.base.plugin, options.base.install)


@task
def refresh_docs():
    """Build sphinx docs from scratch"""

    make = sphinx_make()
    with pushd(options.base.docs):
        sh('%s clean' % make)
        sh('%s html' % make)


@task
@needs('refresh_docs')
def publish_docs():
    """this script publish Sphinx outputs to github pages"""

    tempdir = options.base.tmp / 'tempdocs'

    sh('git clone git@github.com:geopython/MetaSearch.git %s' %
       tempdir)
    with pushd(tempdir):
        sh('git checkout gh-pages')
        sh('cp -rp %s/docs/_build/html/* .' % options.base.home)
        sh('git add .')
        sh('git commit -am "update live docs [ci skip]"')
        sh('git push origin gh-pages')

    tempdir.rmtree()


@task
@needs('build_qt_files', 'setup')
def package():
    """create zip file of plugin"""

    package_file = get_package_filename()

    if not os.path.exists(options.base.tmp):
        options.base.tmp.mkdir()
    if os.path.exists(package_file):
        os.unlink(package_file)
    with zipfile.ZipFile(package_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(options.base.plugin):
            for file_add in files:
                if file_add.endswith('.pyc'):
                    continue
                filepath = os.path.join(root, file_add)
                relpath = os.path.relpath(filepath,
                                          os.path.join(BASEDIR, 'plugin'))
                zipf.write(filepath, relpath)
    return package_file  # return name of created zipfile


@task
@cmdopts([
    ('user=', 'u', 'OSGeo userid'),
])
def upload():
    """upload package zipfile to server"""

    user = options.get('user', False)
    if not user:
        raise ValueError('OSGeo userid required')

    password = getpass.getpass('Enter your password: ')
    if password.strip() == '':
        raise ValueError('password required')

    call_task('package')

    zipf = get_package_filename()

    url = 'http://%s:%s@%s:%d/%s' % (user, password, options.upload.host,
                                     options.upload.port,
                                     options.upload.endpoint)

    info('Uploading to http://%s/%s' % (options.upload.host,
                                        options.upload.endpoint))

    server = xmlrpclib.ServerProxy(url, verbose=False)

    try:
        with open(zipf) as zfile:
            plugin_id, version_id = \
                server.plugin.upload(xmlrpclib.Binary(zfile.read()))
            info('Plugin ID: %s', plugin_id)
            info('Version ID: %s', version_id)
    except xmlrpclib.Fault, err:
        error('ERROR: fault error')
        error('Fault code: %d', err.faultCode)
        error('Fault string: %s', err.faultString)
    except xmlrpclib.ProtocolError, err:
        error('Error: Protocol error')
        error("%s : %s", err.errcode, err.errmsg)
        if err.errcode == 403:
            error('Invalid name and password')


@task
def test_default_csw_connections():
    """test that the default CSW connections work"""

    relpath = 'resources/connections-default.xml'
    csw_connections_xml = options.base.plugin / relpath

    csws = etree.parse(csw_connections_xml)

    for csw in csws.findall('csw'):
        name = csw.attrib.get('name')
        data = {
            'service': 'CSW',
            'version': '2.0.2',
            'request': 'GetCapabilities'
        }
        values = urlencode(data)
        url = '%s?%s' % (csw.attrib.get('url'), values)
        content = urlopen(url)
        if content.getcode() != 200:
            raise ValueError('Bad HTTP status code')
        csw_xml = etree.fromstring(content.read())
        tag = '{http://www.opengis.net/cat/csw/2.0.2}Capabilities'
        if csw_xml.tag != tag:
            raise ValueError('root element should be csw:Capabilities')


def sphinx_make():
    """return what command Sphinx is using for make"""

    if os.name == 'nt':
        return 'make.bat'
    return 'make'


def get_package_filename():
    """return filepath of plugin zipfile"""

    filename = '%s-%s.zip' % (PLUGIN_NAME, options.base.version)
    package_file = '%s/%s' % (options.base.tmp, filename)
    return package_file
