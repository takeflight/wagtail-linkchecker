from http import client

import requests
from bs4 import BeautifulSoup

from django.shortcuts import render
from django.utils.lru_cache import lru_cache
from wagtail.wagtailadmin.edit_handlers import (ObjectList,
                                                extract_panel_definitions_from_model_class)
from wagtail.wagtailcore.models import Site

from .forms import SitePreferencesForm
from .models import SitePreferences


class Link(object):

    def __init__(self, url, status_code=None, error=None, site=None):
        self.url = url
        self.status_code = status_code
        self.error = error
        self.site = site

    @property
    def message(self):
        if self.error:
            return self.error
        elif self.status_code in range(100, 300):
            message = "Success"
        elif self.status_code in range(500, 600) and self.url.startswith(self.site.root_url):
            message = 'Internal Server error, please notify the site administrator.'
        else:
            message = str(self.status_code) + ': ' + client.responses[self.status_code] + '.'
        return message

    def __str__(self):
        return self.url

    def __eq__(self, other):
        if not isinstance(other, Link):
            return NotImplemented
        return self.url == other.url

    def __hash__(self):
        return hash(self.url)


def status_error_messages(status_code):
    if status_code in range(100, 300):
        message = "Success"
    elif status_code in range(500, 600):
        message = 'Server error'
    else:
        message = client.responses[status_code]
    return message


@lru_cache()
def get_edit_handler(model):
    panels = extract_panel_definitions_from_model_class(model, ['site'])
    return ObjectList(panels).bind_to_model(model)


def index(request):
    instance = SitePreferences.objects.filter(site=Site.find_for_request(request))
    if instance.exists():
        form = SitePreferencesForm(instance=instance.first())
    else:
        form = SitePreferencesForm()
    EditHandler = get_edit_handler(SitePreferences)

    if request.method == "POST":
        instance = SitePreferences.objects.filter(site=Site.find_for_request(request))
        if instance.exists():
            form = SitePreferencesForm(request.POST, instance=instance.first())
        else:
            instance = SitePreferences(site=Site.find_for_request(request))
            form = SitePreferencesForm(request.POST, instance=instance)
        if form.is_valid():
            edit_handler = EditHandler(instance=SitePreferences, form=form)
            form.save()
    else:
        form = SitePreferencesForm(instance=instance.first())
        edit_handler = EditHandler(instance=SitePreferences, form=form)

    return render(request, 'wagtaillinkchecker/index.html', {
        'form': form,
        'edit_handler': edit_handler,
    })


def scan(request):
    site = Site.find_for_request(request)
    pages = site.root_page.get_descendants(inclusive=True).live().public()
    to_crawl = set()
    have_crawled = set()
    broken_links = set()

    for page in pages:
        url = page.full_url
        if not url:
            continue
        r1 = requests.get(url, verify=True)
        if r1.status_code not in range(100, 300):
            print('yep!!!!')
            broken_links.add(Link(url, site=site, status_code=r1.status_code))
        have_crawled.add(url)
        soup = BeautifulSoup(r1.content)
        links = soup.find_all('a')
        images = soup.find_all('img')

        for link in links:
            link_href = link.get('href')
            if link_href and link_href != '#':
                if link_href.startswith('/'):
                    link_href = site.root_url + link_href
                to_crawl.add(link_href)

        for image in images:
            image_src = link.get('src')
            if image_src and image_src != '#':
                if image_src.startswith('/'):
                    image_src = site.root_url + link_href
                to_crawl.add(image_src)

        for link in to_crawl - have_crawled:
            try:
                r2 = requests.get(link, verify=True)
            except requests.exceptions.ConnectionError as e:
                broken_links.add(Link(link, error='There was an error connecting to this site.'))
                continue
            except requests.exceptions.RequestException as e:
                broken_links.add(Link(link, site=site, error=type(e).__name__ + ': ' + str(e)))
                continue
            print('I scanned ' + str(link))
            if r2.status_code not in range(100, 300):
                print('yep!!!!')
                broken_links.add(Link(link, site=site, status_code=r2.status_code))
            have_crawled.add(link)

    return render(request, 'wagtaillinkchecker/results.html', {
        'broken_links': broken_links,
    })
