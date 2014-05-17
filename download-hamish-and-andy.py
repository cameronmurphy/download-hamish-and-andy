#!/usr/bin/env python

import cookielib
import mechanize
import os
import subprocess
import sys
import re
import urllib2
from bs4 import BeautifulSoup
from datetime import datetime
from mutagen.easyid3 import EasyID3
from optparse import OptionParser


class HamishAndAndyLibSynParser():
    URL_REGEX = 'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    URL = 'http://handa.libsyn.com/page/'

    def __init__(self, page_number, offset=0, limit=sys.maxint, dry_run=False):
        self.episodes = []
        self._page_number = page_number
        self._offset = offset
        self._limit = limit
        self._dry_run = dry_run

    @staticmethod
    def web_request(url):
        request = urllib2.Request(url)
        response = urllib2.urlopen(request)

        return dict(content=response.read(), code=response.getcode())

    @staticmethod
    def parse_episode(soup):
        episode_data = {}

        id_match = re.search('\d{1,10}', soup['id'])

        if id_match is None:
            raise RuntimeError('div.libsyn-item id attribute does not contain integer')

        episode_data['id'] = int(id_match.group(0))

        release_date_container = soup.find('div', {'class': 'libsyn-item-release-date'})

        if release_date_container is None:
            raise RuntimeError('div.libsyn-item-release-date is missing')

        episode_data['release_date'] = \
            datetime.strptime(release_date_container.find(text=True).strip('\n'), '%b %d, %Y')

        body_container = soup.find('div', {'class': 'libsyn-item-body'})

        if body_container is not None:
            body = ''

            for string in body_container.stripped_strings:
                body += string + '\n'

            episode_data['body'] = body

        title_container = soup.find('div', {'class': 'libsyn-item-title'})

        if title_container is None or title_container.a is None:
            raise RuntimeError('div.libsyn-item-title or child \'a\' child element is missing')

        episode_data['title'] = title_container.a.string.strip()

        player_container = soup.find('div', {'class': 'libsyn-item-player'})

        if player_container is None or player_container.iframe is None:
            raise RuntimeError('div.libsyn-item-player or \'iframe\' child element is missing')

        episode_data['player_url'] = 'http:' + player_container.iframe['src']

        return episode_data

    def resolve_file_url(self, player_url):
        response = self.web_request(player_url)

        if response['code'] != 200:
            raise RuntimeError('Web server returned ' + str(response['code']))

        soup = BeautifulSoup(response['content'])
        script_content = soup.body.find('script', {'src': None}).string.strip()

        media_url_search = re.search('mediaURL = "(%s)";' % self.URL_REGEX, script_content)
        return media_url_search.group(1)

    def next(self):
        self.reset()

        if self._limit <= 0:
            return False

        response = self.web_request(self.URL + str(self._page_number))

        if response['code'] != 200:
            raise RuntimeError('Web server returned ' + str(response['code']))

        soup = BeautifulSoup(response['content'])
        episodes_soup = soup.findAll('div', {'class': 'libsyn-item'})

        if episodes_soup.count == 0:
            return False

        for soup in episodes_soup:
            if self._offset > 0:
                self._offset -= 1
                continue

            episode_data = self.parse_episode(soup)

            # Only bother resolving if there's no thumbnail, if there's a thumbnail it's a video
            if re.search('thumbnail/no', episode_data['player_url']):
                if not self._dry_run:
                    episode_data['file_url'] = self.resolve_file_url(episode_data['player_url'])
                else:
                    episode_data['file_url'] = '%s.mp3' % episode_data['release_date'].strftime('%Y-%m-%d')

                self.episodes.append(episode_data)
                self._limit -= 1
            else:
                continue

            if self._limit <= 0:
                break

        self._page_number += 1
        return True

    def reset(self):
        self.episodes = []


class HamishAndAndyPodcastScrubber():
    RED_TEXT_ESCAPE_SEQUENCE = '\033[1;31m%s\033[1;m'
    GREEN_TEXT_ESCAPE_SEQUENCE = '\033[1;32m%s\033[1;m'

    DATE_REGEX = '(?:Monday|Mon|Tuesday|Tues|Wednesday|Wedensday|Wed|Thursday|Thurs|Friday|Fri)? ?' + \
                 '((?:\d{1,2}(?:st|nd|rd|th)?)? ?' + \
                 '(?:January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July' + \
                 '|Jul|August|Aug|September|Sept|October|Oct|November|Nov|December|Dec) ?' + \
                 '(?:(?:\d{1,2}){1,2}(?:st|nd|rd|th)?)? ?' + \
                 '(?:\d{4})?)'

    NAME_WITH_DATE_REGEX = '(?:Best [Oo]f )? ?%s(.*)' % DATE_REGEX
    PODCAST_RETURNS_REGEX = 'Podcast Returns'

    EPISODES_WITH_CORRECT_DATES = [2652979, 2461292, 2231202]
    EPISODE_DATE_OVERRIDES = {2744131: '2014-03-21', 1865221: '2007-03-26', 1865227: '2007-03-16'}

    def __init__(self):
        self._first_day_of_year = datetime.now().replace(
            day=1, month=1, hour=0, minute=0, second=0, microsecond=0
        )

    @staticmethod
    def search_and_parse_date(string):
        date_match = re.search(HamishAndAndyPodcastScrubber.DATE_REGEX, string)
        date = None

        if date_match is not None:
            # Remove suffix from day of month
            parsed_date = re.sub('(\d{1,2})(?:st|nd|rd|th)', '\\1', date_match.group(1))
            # Zero pad the day of the month (if the day number is at the beginning)
            parsed_date = re.sub('^(\d) ', '0\\1 ', parsed_date)
            # Zero pad the day of the month (if the day number is elsewhere in the string)
            parsed_date = re.sub(' (\d) ', ' 0\\1 ', parsed_date)

            parsed_date = parsed_date.strip()

            # Try some known date formats
            try:
                date = datetime.strptime(parsed_date, '%B %d %Y')
            except ValueError:
                try:
                    date = datetime.strptime(parsed_date, '%b %d %Y')
                except ValueError:
                    try:
                        # Add year 2000 cause it's a leap year, means we can parse 29th Feb
                        date = datetime.strptime(parsed_date + ' 2000', '%d %b %Y')
                    except ValueError:
                        try:
                            # Add year 2000 cause it's a leap year, means we can parse 29th Feb
                            date = datetime.strptime(parsed_date + ' 2000', '%d %B %Y')
                        except ValueError:
                            pass

        return date

    @staticmethod
    def cleanup_title(podcast):
        podcast['title'] = podcast['title'].partition('-')[2].strip()
        podcast['title'] = re.sub(HamishAndAndyPodcastScrubber.NAME_WITH_DATE_REGEX, '\\2', podcast['title'])
        podcast['title'] = podcast['title'].lstrip(' -(,').rstrip(')')

    def fix_podcast_date(self, podcast):
        title_date = self.search_and_parse_date(podcast['title'])

        if title_date is not None and (title_date.day != podcast['release_date'].day or
                                       title_date.month != podcast['release_date'].month):

            warning_message = 'Warning: overriding date %s of episode \'%s\' (%d) with parsed date from title: %s' % \
                              (podcast['release_date'].strftime('%Y-%m-%d'),
                               podcast['title'],
                               podcast['id'],
                               title_date.strftime('%d/%m'))

            print self.RED_TEXT_ESCAPE_SEQUENCE % warning_message

            podcast['release_date'] = podcast['release_date'].replace(day=title_date.day, month=title_date.month)

        if 'body' in podcast:
            body_date = self.search_and_parse_date(podcast['body'])

            if body_date and (body_date.day != podcast['release_date'].day or
                              body_date.month != podcast['release_date'].month):
                warning_message = 'Warning: overriding date %s of episode \'%s\' (%d) with date from body: %s' % \
                                  (podcast['release_date'].strftime('%Y-%m-%d'),
                                   podcast['title'],
                                   podcast['id'],
                                   body_date.strftime('%d/%m'))

                print self.RED_TEXT_ESCAPE_SEQUENCE % warning_message

                podcast['release_date'] = podcast['release_date'].replace(day=body_date.day, month=body_date.month)

        # If after all this, the podcast falls on a Saturday or Sunday... be suspicous
        if podcast['release_date'].weekday() >= 5:
            warning_message = 'Warning: episode \'%s\' (%d) with date: %s falls on a weekend' % \
                              (podcast['title'],
                               podcast['id'],
                               podcast['release_date'].strftime('%Y-%m-%d'))

            print self.RED_TEXT_ESCAPE_SEQUENCE % warning_message

    def override_date(self, podcast, date_string):
        message = 'Manual date override (%s) of episode \'%s\' (%d)' % (date_string, podcast['title'], podcast['id'])
        print self.GREEN_TEXT_ESCAPE_SEQUENCE % message

        date = datetime.strptime(self.EPISODE_DATE_OVERRIDES[podcast['id']], '%Y-%m-%d')
        podcast['release_date'] = podcast['release_date'].replace(day=date.day, month=date.month)

    def scrub(self, podcasts):
        podcasts_to_remove = []

        for index, podcast in enumerate(podcasts):
            extension = os.path.splitext(podcast['file_url'])[1]

            if extension.lower() != '.mp3':
                podcasts_to_remove.append(index)

            if podcast['id'] in self.EPISODE_DATE_OVERRIDES:
                self.override_date(podcast, self.EPISODE_DATE_OVERRIDES[podcast['id']])
            else:
                podcast_returns_match = re.search(self.PODCAST_RETURNS_REGEX, podcast['title'])

                if podcast_returns_match is None and podcast['id'] not in self.EPISODES_WITH_CORRECT_DATES:
                    self.fix_podcast_date(podcast)

            self.cleanup_title(podcast)

            podcast['track_number'] = \
                (podcast['release_date'] - self._first_day_of_year.replace(year=podcast['release_date'].year)).days + 1

            podcast_date_string = '{0}, {1} {2}'.format(
                podcast['release_date'].strftime('%a'),
                str(podcast['release_date'].day),
                podcast['release_date'].strftime('%b')
            )

            podcast_filename_date_string = podcast['release_date'].strftime('%Y-%m-%d')

            if podcast['title'] is not None and len(podcast['title']) > 0:
                podcast_title = '{0} - {1}'.format(podcast_date_string, podcast['title'])
                podcast_filename_title = '{0} - {1}'.format(podcast_filename_date_string, podcast['title'])
            else:
                podcast_title = podcast_date_string
                podcast_filename_title = podcast_filename_date_string

            filename = 'Hamish & Andy - ' + podcast_filename_title + extension

            podcast['title'] = podcast_title
            podcast['filename'] = filename

        podcasts_to_remove.reverse()

        for index in podcasts_to_remove:
            podcasts.pop(index)

        return podcasts


class LibSynDownloader():
    LOGIN_URL = 'https://my.libsyn.com/auth/login'

    def __init__(self):
        self._cookie_jar = cookielib.CookieJar()

    def login(self, username, password):
        browser = mechanize.Browser()
        browser.set_cookiejar(self._cookie_jar)

        response = browser.open(self.LOGIN_URL)

        if response.code != 200:
            raise RuntimeError('Login page returned %d' % response.code)

        login_form_index = -1

        for ((form_index, form)) in enumerate(browser.forms()):
            if form.name == 'login_form':
                login_form_index = form_index

        browser.select_form(nr=login_form_index)
        browser.form['email'] = username
        browser.form['password'] = password

        account_page_response = browser.submit()

        if account_page_response.code != 200:
            raise RuntimeError('Logging in returned %d' % response.code)

    def download_file(self, url, save_to):
        cookie_string = ''

        for cookie in self._cookie_jar:
            cookie_string += '%s=%s; ' % (cookie.name, cookie.value)

        headers = {'Cookie': cookie_string}

        request = urllib2.Request(url, None, headers)
        response = urllib2.urlopen(request)

        output = open(save_to, 'wb')
        output.write(response.read())
        output.close()


option_parser = OptionParser()
option_parser.add_option('--page', type='int', help='page number to begin downloading from')
option_parser.add_option('--limit', type='int', help='maximum number of episodes to download')
option_parser.add_option('--offset', type='int', help='number of episodes to skip')
option_parser.add_option('--page-limit', type='int', help='maximum number of pages to download')
option_parser.add_option('--username', type='string', help='username for my.libsyn.com (only required for premium eps')
option_parser.add_option('--password', type='string', help='password for my.libsyn.com (only required for premium eps')
option_parser.add_option('--dry-run', action='store_true')

(options, args) = option_parser.parse_args()

page_limit_option = options.page_limit if (options.page_limit is not None) else sys.maxint
page_number_option = options.page if (options.page is not None and options.page > 0) else 1
offset_option = options.offset if (options.offset is not None and options.offset > 0) else 0
limit_option = options.limit if (options.limit is not None) else sys.maxint
dry_run_option = options.dry_run if (options.dry_run is not None) else False

downloader = LibSynDownloader()
scrubber = HamishAndAndyPodcastScrubber()

if not dry_run_option and options.username is not None and options.password is not None:
    print 'Logging into my.libsyn.com'
    downloader.login(options.username, options.password)

parser = HamishAndAndyLibSynParser(page_number_option, offset_option, limit_option, dry_run_option)

while page_limit_option > 0 and parser.next():
    episodes = scrubber.scrub(parser.episodes)

    for episode in episodes:
        if dry_run_option:
            print '"%s", "%s"' % (episode['title'], episode['filename'])
        else:
            print 'Downloading ' + episode['filename'] + '...'

        if os.path.isfile(episode['filename']):
            raise RuntimeError('Two episodes exist with filename: %s' % episode['filename'])

        if dry_run_option:
            # Pretend to download
            subprocess.call(['touch', episode['filename']])
            continue

        downloader.download_file(episode['file_url'], episode['filename'])

        mp3_file = EasyID3(episode['filename'])

        mp3_file['title'] = episode['title']
        mp3_file['date'] = str(episode['release_date'].year)
        mp3_file['artist'] = 'Hamish & Andy'
        mp3_file['albumartistsort'] = 'Hamish & Andy'
        mp3_file['album'] = 'Podcasts ' + episode['release_date'].strftime('%Y')
        mp3_file['albumsort'] = 'Podcasts ' + episode['release_date'].strftime('%Y')
        mp3_file['tracknumber'] = str(episode['track_number'])

        mp3_file.save()

    page_limit_option -= 1