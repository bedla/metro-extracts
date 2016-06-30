#!/usr/bin/env python
import unittest
import os, tempfile
from uuid import uuid4
from shutil import rmtree
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
from re import compile

from App.web import make_app
from App.util import get_mapzen_navbar, get_mapzen_footer
from bs4 import BeautifulSoup
from httmock import HTTMock, response
from flask import Flask
import requests

app = Flask(__name__)

class TestUtil (unittest.TestCase):

    def setUp(self):
        tempfile.tempdir, self._old_tempdir = tempfile.mkdtemp(prefix='util-'), tempfile.gettempdir()
        print('Made', tempfile.tempdir)
    
    def tearDown(self):
        print('Killing', tempfile.tempdir)
        rmtree(tempfile.tempdir)
        tempfile.tempdir = self._old_tempdir
    
    def test_navbar(self):
        def response_content1(url, request):
            '''
            '''
            MHP = request.method, url.hostname, url.path

            if MHP == ('GET', 'mapzen.com', '/site-fragments/navbar.html'):
                return response(200, 'Hello I am the navbar', headers={'Content-Type': 'text/html; charset=utf-8'})

            raise Exception(request.method, url, request.headers, request.body)
        
        def response_content2(url, request):
            '''
            '''
            raise Exception(request.method, url, request.headers, request.body)
        
        with HTTMock(response_content1):
            # Request it once to get into cache.
            self.assertIn('Hello I am the navbar', get_mapzen_navbar())

        with HTTMock(response_content2):
            # Request it again and expect to get it from cache.
            self.assertIn('Hello I am the navbar', get_mapzen_navbar())

class TestApp (unittest.TestCase):

    _url_prefix = None
    
    def prefixed(self, path):
        return ''.join((self._url_prefix or '', path))
    
    def setUp(self):
        app = make_app(self._url_prefix)
        app.config['MAPZEN_APP_ID'] = '123'
        app.config['MAPZEN_APP_SECRET'] = '456'
        app.secret_key = '789'

        self.client = app.test_client()

    def test_index(self):
        resp1 = self.client.get(self.prefixed('/'))
        soup1 = BeautifulSoup(resp1.data, 'html.parser')
        head1 = soup1.find('h1').text

        self.assertEqual(resp1.status_code, 200)
        self.assertIn('metro extracts', head1)
        
        link1 = soup1.find_all(text='San Francisco')[0].find_parent('a')
        resp2 = self.client.get(link1['href'])
        soup2 = BeautifulSoup(resp2.data, 'html.parser')
        head2 = soup2.find('h1').text

        self.assertEqual(resp2.status_code, 200)
        self.assertIn('San Francisco', head2)
        
    def test_oauth_index(self):
        resp = self.client.get(self.prefixed('/oauth/hello'))
        soup = BeautifulSoup(resp.data, 'html.parser')
        head = soup.find('h2').text

        self.assertEqual(resp.status_code, 401)
        self.assertIn('Authenticate With Mapzen', head)
    
    def _do_login(self, codes):
        '''
        '''
        starting_path = self.prefixed('/oauth/hello')
        
        def response_content1(url, request):
            '''
            '''
            raise Exception(request.method, url, request.headers, request.body)
        
        with HTTMock(response_content1):
            # Request the fake front OAuth page.
            resp1 = self.client.get(starting_path)
            soup1 = BeautifulSoup(resp1.data, 'html.parser')
            form1 = soup1.find('form')
            query1 = dict([(i['name'], i['value']) for i in form1.find_all('input')])
            action_url = urlparse(form1['action'])
            redirect_url = urlparse(query1['redirect_uri'])
            
            self.assertEqual(resp1.status_code, 401)
            self.assertEqual(form1['method'], 'get')
            self.assertEqual(redirect_url.path, self.prefixed('/oauth/callback'))
            self.assertEqual(action_url.netloc, 'mapzen.com')
            self.assertEqual(action_url.path, '/oauth/authorize')
            
        def response_content2(url, request):
            '''
            '''
            MHP = request.method, url.hostname, url.path
            response_headers = {'Content-Type': 'application/json; charset=utf-8'}

            if MHP == ('POST', 'mapzen.com', '/oauth/token'):
                form = dict(parse_qsl(request.body))
                if form['code'] == codes.pop(0):
                    data = u'''{"access_token":"working-access-token", "expires_in":7200, "token_type":"bearer"}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            if MHP == ('GET', 'mapzen.com', '/developers/oauth_api/current_developer'):
                if request.headers['Authorization'] == 'Bearer working-access-token':
                    data = u'''{\r  "id": 631,\r  "email": "email@company.com",\r  "nickname": "user_github_handle",\r  "admin": false,\r  "keys": "https://mapzen.com/developers/oauth_api/current_developer/keys"\r}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            raise Exception(request.method, url, request.headers, request.body)
        
        with HTTMock(response_content2):
            # Go back to redirect_uri, pretending that Mapzen.com has let us in.
            query2 = dict(code=codes[0], state=query1['state'])
            resp2 = self.client.get('?'.join((redirect_url.path, urlencode(query2))))
            redirect2 = urlparse(resp2.headers.get('Location'))

            self.assertEqual(resp2.status_code, 302)
            self.assertEqual(redirect2.hostname, 'localhost')
            self.assertEqual(redirect2.path, starting_path)
            
            # Verify that we are logged in.
            resp3 = self.client.get(redirect2.path)
            soup3 = BeautifulSoup(resp3.data, 'html.parser')

            self.assertEqual(resp3.status_code, 200)
            self.assertIsNotNone(soup3.find(text=compile(r'\buser_github_handle\b')))
    
    def _do_logout(self, codes):
        '''
        '''
        starting_path = self.prefixed('/oauth/hello')
        
        def response_content2(url, request):
            '''
            '''
            MHP = request.method, url.hostname, url.path
            response_headers = {'Content-Type': 'application/json; charset=utf-8'}

            if MHP == ('POST', 'mapzen.com', '/oauth/token'):
                form = dict(parse_qsl(request.body))
                if form['code'] == codes.pop(0):
                    data = u'''{"access_token":"working-access-token", "expires_in":7200, "token_type":"bearer"}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            if MHP == ('GET', 'mapzen.com', '/developers/oauth_api/current_developer'):
                if request.headers['Authorization'] == 'Bearer working-access-token':
                    data = u'''{\r  "id": 631,\r  "email": "email@company.com",\r  "nickname": "user_github_handle",\r  "admin": false,\r  "keys": "https://mapzen.com/developers/oauth_api/current_developer/keys"\r}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            raise Exception(request.method, url, request.headers, request.body)
        
        with HTTMock(response_content2):
            # Verify that we are logged in.
            resp3 = self.client.get(starting_path)
            soup3 = BeautifulSoup(resp3.data, 'html.parser')

            self.assertEqual(resp3.status_code, 200)
            self.assertIsNotNone(soup3.find(text=compile(r'\buser_github_handle\b')))

            # Log out.
            resp4 = self.client.post(self.prefixed('/oauth/logout'))
            
            # Verify that we are logged out.
            resp5 = self.client.get(starting_path)
            soup5 = BeautifulSoup(resp5.data, 'html.parser')

            self.assertEqual(resp5.status_code, 401)
    
    def test_login(self):
        '''
        '''
        codes = ['let-me-in']
        
        self._do_login(codes)
        self._do_logout(codes)

    def test_odes_index(self):
        resp = self.client.get(self.prefixed('/odes/'))
        self.assertEqual(resp.status_code, 200)
    
    def test_odes_request(self):
        codes = ['let-me-in']
        
        self._do_login(codes)
        
        def response_content1(url, request):
            '''
            '''
            MHP = request.method, url.hostname, url.path
            response_headers = {'Content-Type': 'application/json; charset=utf-8'}

            if MHP == ('GET', 'mapzen.com', '/developers/oauth_api/current_developer'):
                if request.headers['Authorization'] == 'Bearer working-access-token':
                    data = u'''{\r  "id": 631,\r  "email": "email@company.com",\r  "nickname": "user_github_handle",\r  "admin": false,\r  "keys": "https://mapzen.com/developers/oauth_api/current_developer/keys"\r}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            if MHP == ('GET', 'mapzen.com', '/developers/oauth_api/current_developer/keys'):
                if request.headers['Authorization'] == 'Bearer working-access-token':
                    data = u'''[\r  {\r    "service": "odes",\r    "key": "odes-xxxxxxx",\r    "created_at": "2015-12-15T15:24:57.236Z",\r    "nickname": "Untitled",\r    "status": "created"\r  },\r  {\r    "service": "odes",\r    "key": "odes-yyyyyyy",\r    "created_at": "2015-12-15T15:24:59.320Z",\r    "nickname": "Untitled",\r    "status": "disabled"\r  }\r]'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            if MHP == ('POST', 'odes.mapzen.com', '/extracts'):
                if url.query == 'api_key=odes-xxxxxxx':
                    bbox = dict(parse_qsl(request.body))
                    data = u'''{\r  "id": 999,\r  "status": "created",\r  "created_at": "2016-06-02T03:29:25.233Z",\r  "processed_at": "2016-06-02T04:20:11.000Z",\r  "bbox": {\r    "e": -122.24825,\r    "n": 37.81230,\r    "s": 37.79724,\r    "w": -122.26447\r  }\r}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            if MHP == ('GET', 'odes.mapzen.com', '/extracts/999'):
                if url.query == 'api_key=odes-xxxxxxx':
                    bbox = dict(parse_qsl(request.body))
                    data = u'''{\r  "id": 999,\r  "status": "created",\r  "created_at": "2016-06-02T03:29:25.233Z",\r  "processed_at": "2016-06-02T04:20:11.000Z",\r  "bbox": {\r    "e": -122.24825,\r    "n": 37.81230,\r    "s": 37.79724,\r    "w": -122.26447\r  }\r}'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            if MHP == ('GET', 'odes.mapzen.com', '/extracts'):
                if url.query == 'api_key=odes-xxxxxxx':
                    bbox = dict(parse_qsl(request.body))
                    data = u'''[\r{\r  "id": 999,\r  "status": "created",\r  "created_at": "2016-06-02T03:29:25.233Z",\r  "processed_at": "2016-06-02T04:20:11.000Z",\r  "bbox": {\r    "e": -122.24825,\r    "n": 37.81230,\r    "s": 37.79724,\r    "w": -122.26447\r  }\r}\r]'''
                    return response(200, data.encode('utf8'), headers=response_headers)

            raise Exception(request.method, url, request.headers, request.body)
        
        with HTTMock(response_content1):
            data1 = dict(bbox_n=37.81230, bbox_w=-122.26447, bbox_s=37.79724, bbox_e=-122.24825)
            resp1 = self.client.post(self.prefixed('/odes/envelopes/'), data=data1)
            redirect1 = urlparse(resp1.headers.get('Location'))
            
            self.assertEqual(resp1.status_code, 303)
            self.assertTrue(redirect1.path.startswith(self.prefixed('/odes/envelopes/')))
            
            resp2 = self.client.get(redirect1.path)
            redirect2 = urlparse(resp2.headers.get('Location'))
            
            self.assertEqual(resp2.status_code, 301)
            self.assertTrue(redirect2.path.startswith(self.prefixed('/odes/extracts/')))
            
            resp3 = self.client.get(redirect2.path)
            soup3 = BeautifulSoup(resp3.data, 'html.parser')
            
            self.assertEqual(resp3.status_code, 200)
            self.assertIsNotNone(soup3.find(text=compile(r'\b999\b')))
            
            resp4 = self.client.get(self.prefixed('/odes/extracts/'))
            soup4 = BeautifulSoup(resp4.data, 'html.parser')
            
            self.assertEqual(resp4.status_code, 200)
            self.assertIsNotNone(soup4.find(text=compile(r'\b999\b')))

class TestAppPrefix (TestApp):
    _url_prefix = '/{}'.format(uuid4())

class TestAppDoublePrefix (TestApp):
    _url_prefix = '/{}/{}'.format(uuid4(), uuid4())

if __name__ == '__main__':
    unittest.main()
