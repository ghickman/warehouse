# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pyramid.httpexceptions import (HTTPFound, HTTPMovedPermanently,
                                    HTTPSeeOther)
from pyramid.security import remember, forget
from pyramid.view import forbidden_view_config, view_config

from warehouse.accounts.forms import LoginForm
from warehouse.accounts.interfaces import ILoginService
from warehouse.cache.origin import origin_cache
from warehouse.cache.http import cache_control
from warehouse.csrf import csrf_protect
from warehouse.sessions import uses_session


@view_config(
    route_name="accounts.profile",
    renderer="accounts/profile.html",
    decorator=[
        cache_control(
            1 * 24 * 60 * 60,                         # 1 day
            stale_while_revalidate=1 * 24 * 60 * 60,  # 1 day
            stale_if_error=1 * 24 * 60 * 60,          # 1 day
        ),
        origin_cache(30 * 24 * 60 * 60),  # 30 days
    ],
)
def profile(user, request):
    if user.username != request.matchdict.get("username", user.username):
        return HTTPMovedPermanently(
            request.current_route_path(username=user.username),
        )

    return {"user": user}


@view_config(
    route_name="accounts.login",
    renderer="accounts/login.html",
    decorator=[csrf_protect("accounts.login"), uses_session],
)
def login(request, _form_class=LoginForm):
    # TODO: If already logged in just redirect to ?next=
    # TODO: Logging in should reset request.user
    # TODO: Configure the login view as the default view for not having
    #       permission to view something.

    login_service = request.find_service(ILoginService, context=None)

    form = _form_class(request.POST, login_service=login_service)

    if request.method == "POST" and form.validate():
        # Get the user id for the given username.
        userid = login_service.find_userid(form.username.data)

        # We have a session factory associated with this request, so in order
        # to protect against session fixation attacks we're going to make sure
        # that we create a new session (which for sessions with an identifier
        # will cause it to get a new session identifier).

        # We need to protect against session fixation attacks, so make sure
        # that we create a new session (which will cause it to get a new
        # session identifier).
        # TODO: This should be removed once/if Pylons/pyramid#1570 gets merged
        #       to handle this for us.
        if (request.unauthenticated_userid is not None and
                request.unauthenticated_userid != userid):
            # There is already a userid associated with this request and it is
            # a different userid than the one we're trying to remember now. In
            # this case we want to drop the existing session completely because
            # we don't want to leak any data between authenticated userids.
            request.session.invalidate()
        else:
            # We either do not have an associated userid with this request
            # already, or the userid is the same one we're trying to remember
            # now. In either case we want to keep all of the data but we want
            # to make sure that we create a new session since we're crossing
            # a privilege boundary.
            data = dict(request.session.items())
            request.session.invalidate()
            request.session.update(data)

        # Remember the userid using the authentication policy.
        headers = remember(request, userid)

        # Cycle the CSRF token since we've crossed an authentication boundary
        # and we don't want to continue using the old one.
        request.session.new_csrf_token()

        # Now that we're logged in we'll want to redirect the user to either
        # where they were trying to go originally, or to the default view.
        # TODO: Implement ?next= support.
        # TODO: Figure out a better way to handle the "default view".
        return HTTPSeeOther("/", headers=dict(headers))

    return {"form": form}


@view_config(
    route_name="accounts.logout",
    renderer="accounts/logout.html",
    decorator=[csrf_protect("accounts.logout"), uses_session],
)
def logout(request):
    # TODO: If already logged out just redirect to ?next=
    # TODO: Logging out should reset request.user

    if request.method == "POST":
        # A POST to the logout view tells us to logout. There's no form to
        # validate here becuse there's no data. We should be protected against
        # CSRF attacks still because of the CSRF framework, so users will still
        # need a post body that contains the CSRF token.
        headers = forget(request)

        # When crossing an authentication boundry we want to create a new
        # session identifier. We don't want to keep any information in the
        # session when going from authenticated to unauthenticated because
        # user's generally expect that logging out is a desctructive action
        # that erases all of their private data. However if we don't clear the
        # session then another user can use the computer after them, log in to
        # their account, and then gain access to anything sensitive stored in
        # the session for the original user.
        # TODO: This should be removed once/if Pylons/pyramid#1570 gets merged
        #       to handle this for us.
        request.session.invalidate()

        # Now that we're logged out we'll want to redirect the user to either
        # where they were originally, or to the default view.
        # TODO: Implement ?next= support.
        # TODO: Figure out a better way to handle the "default view".
        return HTTPSeeOther("/", headers=dict(headers))

    return {}


@forbidden_view_config()
def forbidden(request):
    next_url = '?next={}'.format(request.current_route_path())
    return HTTPFound(request.route_url('accounts.login') + next_url)
