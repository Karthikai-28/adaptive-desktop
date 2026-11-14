"""Where a navigation inside one of Home's site tabs belongs. Pure (no GTK): scripts/verify-mario.py tests it.

A tab is a site signed in to inside Home, in Home's own profile. So everything that is part of
signing in has to stay in the tab's view: a sign-in page opened in the browser signs the browser
in, not Home, and the tab stays signed out for good. Only what really leaves the site (a link in a
mail) goes to the browser.
"""
from urllib.parse import quote, urlsplit

# first label of a host that signs you in to its site: accounts.google.com, login.microsoftonline.com
SIGN_IN_LABELS = ("accounts", "login", "signin", "auth", "sso", "id")
STAY, HERE, BROWSER = "stay", "here", "browser"


def host(uri):
    try:
        return (urlsplit(uri or "").hostname or "").lower()
    except ValueError:
        return ""


def base_domain(uri):
    return ".".join(host(uri).split(".")[-2:])


def is_sign_in(uri, tab_url):
    """A sign-in page of the tab's own site."""
    name = host(uri)
    return bool(name) and name != host(tab_url) and base_domain(uri) == base_domain(tab_url) \
        and name.split(".")[0] in SIGN_IN_LABELS


def route(uri, tab_url, new_window=False, clicked=False):
    """STAY: the view goes there as it would. HERE: a new window was asked for, load it in this
    view instead. BROWSER: it belongs in the browser."""
    if not (uri or "").startswith(("http://", "https://")):
        return STAY
    if new_window:
        # "Sign in" and "Add another account" ask for a new window; that one is ours
        return HERE if is_sign_in(uri, tab_url) else BROWSER
    if clicked and base_domain(uri) != base_domain(tab_url):
        return BROWSER
    return STAY


def signed_out_landing(uri, tab_url):
    """Signed out, Google sends Calendar and Gmail to an advert for the product, whose only way on
    is a "Sign in" link. Returns the sign-in page that comes back to the tab, or None."""
    if base_domain(tab_url) != "google.com" or host(uri) == host(tab_url):
        return None
    name, path = host(uri), urlsplit(uri).path
    if name == "workspace.google.com" or (name == "www.google.com" and "/about" in path):
        return "https://accounts.google.com/ServiceLogin?continue=" + quote(tab_url, safe="")
    return None
