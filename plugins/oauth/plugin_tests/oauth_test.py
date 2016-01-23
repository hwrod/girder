#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright 2014 Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import datetime
import json
import re
from six.moves import urllib

import httmock
import requests
import six

from girder.constants import SettingKey
from tests import base


def setUpModule():
    base.enabledPlugins.append('oauth')
    base.startServer()


def tearDownModule():
    base.stopServer()


class OauthTest(base.TestCase):

    def setUp(self):
        base.TestCase.setUp(self)

        # girder.plugins is not available until setUp is running
        global PluginSettings
        from girder.plugins.oauth.constants import PluginSettings

        self.adminUser = self.model('user').createUser(
            email='admin@mail.com',
            login='admin',
            firstName='first',
            lastName='last',
            password='password',
            admin=True
        )

        # Specifies which test account (typically "new" or "existing") a
        # redirect to a provider will simulate authentication for
        self.accountType = None


    def testDeriveLogin(self):
        """
        Unit tests the _deriveLogin method of the provider classes.
        """
        from girder.plugins.oauth.providers.base import ProviderBase

        login = ProviderBase._deriveLogin('1234@mail.com', 'John', 'Doe')
        self.assertEqual(login, 'johndoe')

        login = ProviderBase._deriveLogin('hello.world.foo@mail.com', 'A', 'B')
        self.assertEqual(login, 'helloworldfoo')

        login = ProviderBase._deriveLogin('hello.world@mail.com', 'A', 'B', 'user2')
        self.assertEqual(login, 'user2')

        login = ProviderBase._deriveLogin('admin@admin.com', 'A', 'B', 'admin')
        self.assertEqual(login, 'admin1')


    def _testOauth(self, providerInfo):
        # Close registration to start off, and simulate a new user
        self.model('setting').set(SettingKey.REGISTRATION_POLICY, 'closed')
        self.accountType = 'new'

        # We should get an empty listing when no providers are set up
        params = {
            'key': PluginSettings.PROVIDERS_ENABLED,
            'value': []
        }
        resp = self.request(
            '/system/setting', user=self.adminUser, method='PUT', params=params)
        self.assertStatusOk(resp)

        resp = self.request('/oauth/provider', exception=True, params={
            'redirect': 'http://localhost/#foo/bar',
            'list': True
        })
        self.assertStatusOk(resp)
        self.assertFalse(resp.json)

        # Turn on provider, but don't set other settings
        params = {
            'list': json.dumps([{
                'key': PluginSettings.PROVIDERS_ENABLED,
                'value': [providerInfo['id']]
            }])
        }
        resp = self.request(
            '/system/setting', user=self.adminUser, method='PUT', params=params)
        self.assertStatusOk(resp)

        resp = self.request('/oauth/provider', exception=True, params={
            'redirect': 'http://localhost/#foo/bar'})
        self.assertStatus(resp, 500)

        # Set up provider normally
        params = {
            'list': json.dumps([
                {
                    'key': PluginSettings.PROVIDERS_ENABLED,
                    'value': [providerInfo['id']]
                }, {
                    'key': providerInfo['client_id']['key'],
                    'value': providerInfo['client_id']['value']
                }, {
                    'key': providerInfo['client_secret']['key'],
                    'value': providerInfo['client_secret']['value']
                }
            ])
        }
        resp = self.request(
            '/system/setting', user=self.adminUser, method='PUT',
            params=params)
        self.assertStatusOk(resp)
        # No need to re-fetch and test all of these settings values; they will
        # be implicitly tested later

        # Make sure that if no list param is passed, we receive the old format
        resp = self.request('/oauth/provider', params={
            'redirect': 'http://localhost/#foo/bar'
        })
        self.assertStatusOk(resp)
        self.assertIsInstance(resp.json, dict)
        self.assertEqual(len(resp.json), 1)
        self.assertIn(providerInfo['name'], resp.json)
        self.assertRegexpMatches(
            resp.json[providerInfo['name']],
            providerInfo['url_re'])

        # This will need to be called several times, to get fresh tokens
        def getProviderResp():
            resp = self.request('/oauth/provider', params={
                'redirect': 'http://localhost/#foo/bar',
                'list': True
            })
            self.assertStatusOk(resp)
            self.assertIsInstance(resp.json, list)
            self.assertEqual(len(resp.json), 1)
            providerResp = resp.json[0]
            self.assertSetEqual(
                set(six.viewkeys(providerResp)),
                {'id', 'name', 'url'})
            self.assertEqual(providerResp['id'], providerInfo['id'])
            self.assertEqual(providerResp['name'], providerInfo['name'])
            self.assertRegexpMatches(
                providerResp['url'],
                providerInfo['url_re'])
            redirectParams = urllib.parse.parse_qs(
                urllib.parse.urlparse(providerResp['url']).query)
            csrfTokenParts = redirectParams['state'][0].partition('.')
            token = self.model('token').load(
                csrfTokenParts[0], force=True, objectId=False)
            self.assertLess(
                token['expires'],
                datetime.datetime.utcnow() + datetime.timedelta(days=0.30))
            self.assertEqual(
                csrfTokenParts[2],
                'http://localhost/#foo/bar')
            return providerResp

        # Try the new format listing
        getProviderResp()

        # Try callback, for a non-existant provider
        resp = self.request('/oauth/foobar/callback')
        self.assertStatus(resp, 400)

        # Try callback, without providing any params
        resp = self.request('/oauth/%s/callback' % providerInfo['id'])
        self.assertStatus(resp, 400)

        # Try callback, providing params as though the provider failed
        resp = self.request(
            '/oauth/%s/callback' % providerInfo['id'],
            params={
                'code': None,
                'error': 'some_custom_error',
            }, exception=True)
        self.assertStatus(resp, 502)
        self.assertEqual(
            resp.json['message'],
            "Provider returned error: 'some_custom_error'.")

        # This will need to be called several times, to use fresh tokens
        def getCallbackParams(providerResp):
            resp = requests.get(providerResp['url'], allow_redirects=False)
            self.assertEqual(resp.status_code, 302)
            callbackLoc = urllib.parse.urlparse(resp.headers['location'])
            self.assertEqual(
                callbackLoc.path,
                r'/api/v1/oauth/%s/callback' % providerInfo['id'])
            callbackLocQuery = urllib.parse.parse_qs(callbackLoc.query)
            self.assertNotHasKeys(callbackLocQuery, ('error',))
            callbackParams = {
                key: val[0] for key, val in six.viewitems(callbackLocQuery)
            }
            return callbackParams

        # Call (simulated) external provider
        getCallbackParams(getProviderResp())

        # Try callback, with incorrect CSRF token
        params = getCallbackParams(getProviderResp())
        params['state'] = 'something_wrong'
        resp = self.request('/oauth/%s/callback' % providerInfo['id'],
                            params=params)
        self.assertStatus(resp, 403)
        self.assertTrue(
            resp.json['message'].startswith('Invalid CSRF token'))

        # Try callback, with expired CSRF token
        params = getCallbackParams(getProviderResp())
        token = self.model('token').load(
            params['state'].partition('.')[0], force=True, objectId=False)
        token['expires'] -= datetime.timedelta(days=1)
        self.model('token').save(token)
        resp = self.request('/oauth/%s/callback' % providerInfo['id'],
                            params=params)
        self.assertStatus(resp, 403)
        self.assertTrue(
            resp.json['message'].startswith('Expired CSRF token'))

        # Try callback, with a valid CSRF token but no redirect
        params = getCallbackParams(getProviderResp())
        params['state'] = params['state'].partition('.')[0]
        resp = self.request('/oauth/%s/callback' % providerInfo['id'],
                            params=params)
        self.assertStatus(resp, 400)
        self.assertTrue(
            resp.json['message'].startswith('No redirect location'))

        # Try callback, with incorrect code
        params = getCallbackParams(getProviderResp())
        params['code'] = 'something_wrong'
        resp = self.request('/oauth/%s/callback' % providerInfo['id'],
                            params=params)
        self.assertStatus(resp, 502)

        # Try callback, with real parameters from provider, but still for the
        # 'new' account
        params = getCallbackParams(getProviderResp())
        resp = self.request('/oauth/%s/callback' % providerInfo['id'],
                     params=params)
        self.assertStatus(resp, 400)
        self.assertTrue(
            resp.json['message'].startswith(
                'Registration on this instance is closed.'))

        # This will need to be called several times, and will do a normal login
        def doOauthLogin(accountType):
            self.accountType = accountType
            params = getCallbackParams(getProviderResp())
            resp = self.request('/oauth/%s/callback' % providerInfo['id'],
                         params=params, isJson=False)
            self.assertStatus(resp, 303)
            self.assertEqual(resp.headers['Location'],
                             'http://localhost/#foo/bar')
            self.assertTrue('girderToken' in resp.cookie)

            resp = self.request('/user/me',
                                token=resp.cookie['girderToken'].value)
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['email'],
                providerInfo['accounts'][accountType]['user']['email'])
            self.assertEqual(resp.json['login'],
                providerInfo['accounts'][accountType]['user']['login'])
            self.assertEqual(resp.json['firstName'],
                providerInfo['accounts'][accountType]['user']['firstName'])
            self.assertEqual(resp.json['lastName'],
                providerInfo['accounts'][accountType]['user']['lastName'])

        # Try callback for the 'existing' account, which should succeed
        doOauthLogin('existing')

        # Try callback for the 'new' account, with open registration
        self.model('setting').set(SettingKey.REGISTRATION_POLICY, 'open')
        doOauthLogin('new')

        # Password login for 'new' OAuth-only user should fail gracefully
        newUser = providerInfo['accounts']['new']['user']
        resp = self.request('/user/authentication',
                            basicAuth='%s:mypasswd' % newUser['login'])
        self.assertStatus(resp, 400)
        self.assertTrue(
            resp.json['message'].startswith('You don\'t have a password.'))

        # Reset password for 'new' OAuth-only user should work
        self.assertTrue(base.mockSmtp.isMailQueueEmpty())
        resp = self.request('/user/password/temporary',
            method='PUT', params={
                'email': providerInfo['accounts']['new']['user']['email']})
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['message'], 'Sent temporary access email.')
        self.assertTrue(base.mockSmtp.waitForMail())
        msg = base.mockSmtp.getMail()
        # Pull out the auto-generated token from the email
        search = re.search('<a href="(.*)">', msg)
        link = search.group(1)
        linkParts = link.split('/')
        userId = linkParts[-3]
        tokenId = linkParts[-1]
        tempToken = self.model('token').load(
            tokenId, force=True, objectId=False)
        resp = self.request('/user/password/temporary/' + userId,
            method='GET', params={
                'token': tokenId})
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['user']['login'], newUser['login'])
        # We should now be able to change the password
        resp = self.request('/user/password',
            method='PUT', user=resp.json['user'], params={
                'old': tokenId,
                'new': 'mypasswd'})
        self.assertStatusOk(resp)
        # The temp token should get deleted on password change
        token = self.model('token').load(tempToken, force=True, objectId=False)
        self.assertEqual(token, None)

        # Password login for 'new' OAuth-only user should now succeed
        resp = self.request('/user/authentication',
                            basicAuth='%s:mypasswd' % newUser['login'])
        self.assertStatusOk(resp)


    @httmock.all_requests
    def mockOtherRequest(self, url, request):
        raise Exception('Unexpected url %s' % str(request.url))


    def testGoogleOauth(self):
        providerInfo = {
            'id': 'google',
            'name': 'Google',
            'client_id': {
                'key': PluginSettings.GOOGLE_CLIENT_ID,
                'value': 'google_test_client_id'
            },
            'client_secret': {
                'key': PluginSettings.GOOGLE_CLIENT_SECRET,
                'value': 'google_test_client_secret'
            },
            'allowed_callback_re':
                r'^http://127\.0\.0\.1(?::\d+)?/api/v1/oauth/google/callback$',
            'url_re': r'^https://accounts\.google\.com/o/oauth2/auth',
            'accounts': {
                'existing': {
                    'auth_code': 'google_existing_auth_code',
                    'access_token': 'google_existing_test_token',
                    'user': {
                        'login': self.adminUser['login'],
                        'email': self.adminUser['email'],
                        'firstName': self.adminUser['firstName'],
                        'lastName': self.adminUser['lastName'],
                        'oauth': {
                            'provider': 'google',
                            'id': '5326'
                        }
                    }
                },
                'new': {
                    'auth_code': 'google_new_auth_code',
                    'access_token': 'google_new_test_token',
                    'user': {
                        # this login will be created internally by _deriveLogin
                        'login': 'googleuser',
                        'email': 'google_user@mail.com',
                        'firstName': 'John',
                        'lastName': 'Doe',
                        'oauth': {
                            'provider': 'google',
                            'id': '9876'
                        }
                    }
                }
            }
        }

        @httmock.urlmatch(scheme='https', netloc='^accounts.google.com$',
                          path='^/o/oauth2/auth$', method='GET')
        def mockGoogleRedirect(url, request):
            try:
                params = urllib.parse.parse_qs(url.query)
                self.assertEqual(
                    params['response_type'],
                    ['code'])
                self.assertEqual(
                    params['access_type'],
                    ['online'])
                self.assertEqual(
                    params['scope'],
                    ['profile email'])
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 400,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            try:
                self.assertEqual(
                    params['client_id'],
                    [providerInfo['client_id']['value']])
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 401,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            try:
                self.assertRegexpMatches(
                    params['redirect_uri'][0],
                    providerInfo['allowed_callback_re'])
                state = params['state'][0]
                # Nothing to test for state, since provider doesn't care
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 400,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            returnQuery = urllib.parse.urlencode({
                'state': state,
                'code': providerInfo['accounts'][self.accountType]['auth_code']
            })
            return {
                'status_code': 302,
                'headers': {
                    'Location': '%s?%s' % (params['redirect_uri'][0],
                                           returnQuery)
                }
            }

        @httmock.urlmatch(scheme='https', netloc='^accounts.google.com$',
                          path='^/o/oauth2/token$', method='POST')
        def mockGoogleToken(url, request):
            try:
                params = urllib.parse.parse_qs(request.body)
                self.assertEqual(
                    params['client_id'],
                    [providerInfo['client_id']['value']])
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 401,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            try:
                self.assertEqual(
                    params['grant_type'],
                    ['authorization_code'])
                self.assertEqual(
                    params['client_secret'],
                    [providerInfo['client_secret']['value']])
                self.assertRegexpMatches(
                    params['redirect_uri'][0],
                    providerInfo['allowed_callback_re'])
                for account in six.viewvalues(providerInfo['accounts']):
                    if account['auth_code'] == params['code'][0]:
                        break
                else:
                    self.fail()
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 400,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            return json.dumps({
                'token_type': 'Bearer',
                'access_token': account['access_token'],
                'expires_in': 3546,
                'id_token': 'google_id_token'
            })

        @httmock.urlmatch(scheme='https', netloc='^www.googleapis.com$',
                          path='^/plus/v1/people/me$', method='GET')
        def mockGoogleApi(url, request):
            try:
                for account in six.viewvalues(providerInfo['accounts']):
                    if 'Bearer %s' % account['access_token'] == \
                            request.headers['Authorization']:
                        break
                else:
                    self.fail()

                params = urllib.parse.parse_qs(url.query)
                self.assertSetEqual(
                    set(params['fields'][0].split(',')),
                    {'id', 'emails', 'name'})
            except AssertionError as e:
                return {
                    'status_code': 401,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            return json.dumps({
                'id': account['user']['oauth']['id'],
                'name': {
                    'givenName': account['user']['firstName'],
                    'familyName': account['user']['lastName']
                },
                'emails': [
                    {
                        'type': 'other',
                        'value': 'secondary@email.com'
                    }, {
                        'type': 'account',
                        'value': account['user']['email']
                    }
                ]
            })

        with httmock.HTTMock(
            mockGoogleRedirect,
            mockGoogleToken,
            mockGoogleApi,
            # Must keep "mockOtherRequest" last
            self.mockOtherRequest
        ):
            self._testOauth(providerInfo)


    def testGithubOauth(self):
        providerInfo = {
            'id': 'github',
            'name': 'GitHub',
            'client_id': {
                'key': PluginSettings.GITHUB_CLIENT_ID,
                'value': 'github_test_client_id'
            },
            'client_secret': {
                'key': PluginSettings.GITHUB_CLIENT_SECRET,
                'value': 'github_test_client_secret'
            },
            'allowed_callback_re':
                r'^http://127\.0\.0\.1(?::\d+)?/api/v1/oauth/github/callback$',
            'url_re': r'^https://github\.com/login/oauth/authorize',
            'accounts': {
                'existing': {
                    'auth_code': 'github_existing_auth_code',
                    'access_token': 'github_existing_test_token',
                    'user': {
                        'login': self.adminUser['login'],
                        'email': self.adminUser['email'],
                        'firstName': self.adminUser['firstName'],
                        'lastName': self.adminUser['lastName'],
                        'oauth': {
                            'provider': 'github',
                            'id': '2399'
                        }
                    }
                },
                'new': {
                    'auth_code': 'github_new_auth_code',
                    'access_token': 'github_new_test_token',
                    'user': {
                        # login may be provided externally by GitHub; for
                        # simplicity here, do not use a username with whitespace
                        # or underscores
                        'login': 'jane83',
                        'email': 'github_user@mail.com',
                        'firstName': 'Jane',
                        'lastName': 'Doe',
                        'oauth': {
                            'provider': 'github',
                            'id': 1234
                        }
                    }
                }
            }
        }

        @httmock.urlmatch(scheme='https', netloc='^github.com$',
                          path='^/login/oauth/authorize$', method='GET')
        def mockGithubRedirect(url, request):
            redirectUri = None
            try:
                params = urllib.parse.parse_qs(url.query)
                # Check redirect_uri first, so other errors can still redirect
                redirectUri = params['redirect_uri'][0]
                self.assertEqual(
                    params['client_id'],
                    [providerInfo['client_id']['value']])
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 404,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            try:
                self.assertRegexpMatches(
                    redirectUri,
                    providerInfo['allowed_callback_re'])
                state = params['state'][0]
                # Nothing to test for state, since provider doesn't care
                self.assertEqual(
                    params['scope'],
                    ['user:email'])
            except (KeyError, AssertionError) as e:
                returnQuery = urllib.parse.urlencode({
                    'error': repr(e),
                })
            else:
                returnQuery = urllib.parse.urlencode({
                    'state': state,
                    'code': providerInfo['accounts'][self.accountType]['auth_code']
                })
            return {
                'status_code': 302,
                'headers': {
                    'Location': '%s?%s' % (redirectUri, returnQuery)
                }
            }

        @httmock.urlmatch(scheme='https', netloc='^github.com$',
                          path='^/login/oauth/access_token$', method='POST')
        def mockGithubToken(url, request):
            try:
                self.assertEqual(request.headers['Accept'], 'application/json')
                params = urllib.parse.parse_qs(request.body)
                self.assertEqual(
                    params['client_id'],
                    [providerInfo['client_id']['value']])
            except (KeyError, AssertionError) as e:
                return {
                    'status_code': 404,
                    'content': json.dumps({
                        'error': repr(e)
                    })
                }
            try:
                for account in six.viewvalues(providerInfo['accounts']):
                    if account['auth_code'] == params['code'][0]:
                        break
                else:
                    self.fail()
                self.assertEqual(
                    params['client_secret'],
                    [providerInfo['client_secret']['value']])
                self.assertRegexpMatches(
                    params['redirect_uri'][0],
                    providerInfo['allowed_callback_re'])
            except (KeyError, AssertionError) as e:
                returnBody = json.dumps({
                    'error': repr(e),
                    'error_description': repr(e)
                })
            else:
                returnBody = json.dumps({
                    'token_type': 'bearer',
                    'access_token': account['access_token'],
                    'scope': 'user:email'
                })
            return {
                'status_code': 200,
                'headers': {
                    'Content-Type': 'application/json'
                },
                'content': returnBody
            }


        @httmock.urlmatch(scheme='https', netloc='^api.github.com$',
                          path='^/user$', method='GET')
        def mockGithubApiUser(url, request):
            try:
                for account in six.viewvalues(providerInfo['accounts']):
                    if 'token %s' % account['access_token'] == \
                            request.headers['Authorization']:
                        break
                else:
                    self.fail()
            except AssertionError as e:
                return {
                    'status_code': 401,
                    'content': json.dumps({
                        'message': repr(e)
                    })
                }
            return json.dumps({
                'id': account['user']['oauth']['id'],
                'login': account['user']['login'],
                'name': '%s %s' % (account['user']['firstName'],
                                   account['user']['lastName'])
            })

        @httmock.urlmatch(scheme='https', netloc='^api.github.com$',
                          path='^/user/emails$', method='GET')
        def mockGithubApiEmail(url, request):
            try:
                for account in six.viewvalues(providerInfo['accounts']):
                    if 'token %s' % account['access_token'] == \
                            request.headers['Authorization']:
                        break
                else:
                    self.fail()
            except AssertionError as e:
                return {
                    'status_code': 401,
                    'content': json.dumps({
                        'message': repr(e)
                    })
                }
            return json.dumps([
                {
                    'primary': False,
                    'email': 'secondary@email.com',
                    'verified': True
                }, {
                    'primary': True,
                    'email': account['user']['email'],
                    'verified': True
                }
            ])

        with httmock.HTTMock(
            mockGithubRedirect,
            mockGithubToken,
            mockGithubApiUser,
            mockGithubApiEmail,
            # Must keep "mockOtherRequest" last
            self.mockOtherRequest
        ):
            self._testOauth(providerInfo)
