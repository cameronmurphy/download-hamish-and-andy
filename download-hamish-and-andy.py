#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
from bs4 import BeautifulSoup
from datetime import datetime
from eyed3 import id3


class AnsiEscapeSequences:
    RED_TEXT = '\033[1;31m%s\033[1;m'
    GREEN_TEXT = '\033[1;32m%s\033[1;m'

    def __init__(self):
        pass


class HamishAndAndyiTunesArtworkDownloader:
    API_URL = 'https://itunes.apple.com/search?country=AU&entity=podcast&attribute=allArtistTerm&term=Hamish+and+Andy'

    def __init__(self):
        pass

    def resolve_and_download(self):
        request = urllib2.Request(self.API_URL)
        response = urllib2.urlopen(request)

        # TODO - Validate response
        parsed_response = json.loads(response.read())
        image_url = parsed_response['results'][0]['artworkUrl600']

        request = urllib2.Request(image_url)
        response = urllib2.urlopen(request)

        return response.read()


class HamishAndAndyLibSynParser:
    URL_REGEX = 'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    URL = 'http://handa.libsyn.com/page/'

    def __init__(self, page_number, offset=0, limit=sys.maxsize, dry_run=False):
        self.episodes = []
        self._page_number = page_number
        self._page_count = 0
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

        # Clean up some broken markup
        content = response['content'].replace('</div></div></div></div></div>', '</div></div></div></div>')

        soup = BeautifulSoup(content, 'html.parser')
        script_content = soup.body.find('script', {'src': None}).string.strip()

        media_url_search = re.search('mediaURL = "(%s)";' % self.URL_REGEX, script_content)
        return media_url_search.group(1)

    def next(self):
        self.reset()

        if self._limit <= 0:
            return False

        if self._page_number > self._page_count > 0:
            return False

        response = self.web_request(self.URL + str(self._page_number))

        if response['code'] != 200:
            raise RuntimeError('Web server returned ' + str(response['code']))

        soup = BeautifulSoup(response['content'], 'html.parser')

        if self._page_count == 0:
            pager_element = soup.find('div', {'class': 'pager'})

            if pager_element is None:
                raise RuntimeError('d.pager element is missing')

            page_elements = pager_element.findAll('a')
            last_page_element = page_elements[len(page_elements) - 1]
            self._page_count = int(last_page_element.text)

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


class HamishAndAndyPodcastScrubber:
    DATE_REGEX = '(?:Monday|Mon|Tuesday|Tues|Tue|Wednesday|Wedensday|Wed|Thursday|Thurs|Thur|Thu|Friday|Fri)? ?' + \
                 '((?:\d{1,2}(?:st|nd|rd|th)?)? ?' + \
                 '(?:January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July' + \
                 '|Jul|August|Aug|September|Sept|October|Oct|November|Nov|December|Dec) ?' + \
                 '(?:(?:\d{1,2}){1,2}(?:st|nd|rd|th)?)? ?' + \
                 '(?:\d{4})?)'

    NAME_WITH_DATE_REGEX = '(?:Best [Oo]f )? ?%s(.*)' % DATE_REGEX
    PODCAST_RETURNS_REGEX = 'Podcast Returns'

    EPISODES_WITH_CORRECT_DATES = [2652979, 2461292, 2231202]
    EPISODE_DATE_OVERRIDES = {
        2873978: '2014-06-05',
        2744131: '2014-03-21',
        1865200: '2007-04-27',
        1865221: '2007-03-26',
        1865227: '2007-03-16'
    }

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
            # Fixes a poorly named podcast from 10/09/2015
            parsed_date = re.sub('Sept10', 'Sept 10', parsed_date)
            # Replace Sept with Sep (Python abbreviates month names to 3 characters)
            parsed_date = re.sub('Sept ', 'Sep ', parsed_date)

            parsed_date = parsed_date.strip()

            # Try some known date formats (a loop might be neater here)
            try:
                date = datetime.strptime(parsed_date, '%B %d %Y')  # March 30 2012
            except ValueError:
                try:
                    date = datetime.strptime(parsed_date, '%b %d %Y')  # Mar 30 2012
                except ValueError:
                    try:
                        date = datetime.strptime(parsed_date, '%d %B %Y')  # 30 March 2012
                    except ValueError:
                        try:
                            date = datetime.strptime(parsed_date, '%d %b %Y')  # 30 Mar 2012
                        except ValueError:
                            try:
                                # If date has no year, add year 2000 cause it's a leap year, means we can parse 29th Feb
                                date = datetime.strptime(parsed_date + ' 2000', '%d %B %Y')
                            except ValueError:
                                try:
                                    # If date has no year, add year 2000 cause it's a leap year, means we can parse
                                    # 29th Feb
                                    date = datetime.strptime(parsed_date + ' 2000', '%d %b %Y')
                                except ValueError:
                                    try:
                                        # If date has no year, add year 2000 cause it's a leap year, means we can parse
                                        # 29th Feb
                                        date = datetime.strptime(parsed_date + ' 2000', '%B %d %Y')
                                    except ValueError:
                                        try:
                                            # If date has no year, add year 2000 cause it's a leap year, means we can
                                            # parse 29th Feb
                                            date = datetime.strptime(parsed_date + ' 2000', '%b %d %Y')
                                        except ValueError:
                                            pass

        return date

    @staticmethod
    def cleanup_title(podcast):
        if podcast['title'].startswith('Hamish & Andy - '):
            podcast['title'] = podcast['title'][len('Hamish & Andy - '):]

        if HamishAndAndyPodcastScrubber.search_and_parse_date(podcast['title']):
            podcast['title'] = re.sub(HamishAndAndyPodcastScrubber.NAME_WITH_DATE_REGEX, '\\2', podcast['title'])

        podcast['title'] = podcast['title'].lstrip(' -(,')

        if podcast['title'].find('(') == -1:
            podcast['title'] = podcast['title'].rstrip(')')

    @staticmethod
    def sanitise_filename(string):
        if isinstance(string, unicode):
            string = unicodedata.normalize('NFKD', string)

        # Handle unicode RIGHT SINGLE QUOTATION MARK
        string = string.replace(u'\u2019', u'\'')
        string = string.encode('ASCII', 'ignore')
        # Support all file systems, no slashes
        string = string.replace('/', ' + ')
        # Support Windows filesystem (no ? or :)
        string = string.replace(': ', ' - ').replace(':', '.').replace('?', '')
        string = string.strip()
        return string

    def fix_podcast_date(self, podcast):
        title_date = self.search_and_parse_date(podcast['title'])

        if title_date is not None:
            if title_date.day != podcast['release_date'].day or title_date.month != podcast['release_date'].month:
                warning_message = 'Warning: overriding date %s of episode \'%s\' (%d) with date from title: %s' % \
                                  (podcast['release_date'].strftime('%Y-%m-%d'),
                                   podcast['title'],
                                   podcast['id'],
                                   title_date.strftime('%d/%m'))

                print(AnsiEscapeSequences.RED_TEXT % warning_message)

                podcast['release_date'] = podcast['release_date'].replace(day=title_date.day, month=title_date.month)

        elif 'body' in podcast:
            body_date = self.search_and_parse_date(podcast['body'])

            if body_date and (body_date.day != podcast['release_date'].day or
                              body_date.month != podcast['release_date'].month):
                warning_message = 'Warning: overriding date %s of episode \'%s\' (%d) with date from body: %s' % \
                                  (podcast['release_date'].strftime('%Y-%m-%d'),
                                   podcast['title'],
                                   podcast['id'],
                                   body_date.strftime('%d/%m'))

                print(AnsiEscapeSequences.RED_TEXT % warning_message)

                podcast['release_date'] = podcast['release_date'].replace(day=body_date.day, month=body_date.month)

        # If after all this, the podcast falls on a Saturday or Sunday... be suspicous
        if podcast['release_date'].weekday() >= 5:
            warning_message = 'Warning: episode \'%s\' (%d) with date: %s falls on a weekend' % \
                              (podcast['title'],
                               podcast['id'],
                               podcast['release_date'].strftime('%Y-%m-%d'))

            print(AnsiEscapeSequences.RED_TEXT % warning_message)

    def override_date(self, podcast, date_string):
        message = 'Manual date override (%s) of episode \'%s\' (%d)' % (date_string, podcast['title'], podcast['id'])
        print(AnsiEscapeSequences.GREEN_TEXT % message)

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
            podcast['filename'] = HamishAndAndyPodcastScrubber.sanitise_filename(filename)

        podcasts_to_remove.reverse()

        for index in podcasts_to_remove:
            podcasts.pop(index)

        return podcasts


class LibSynDownloader:
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

        for (form_index, form) in enumerate(browser.forms()):
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


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--page', type=int, help='page number to begin downloading from', default=1)
    arg_parser.add_argument('--limit', type=int, help='maximum number of episodes to download', default=sys.maxsize)
    arg_parser.add_argument('--offset', type=int, help='number of episodes to skip', default=0)
    arg_parser.add_argument('--page-limit', type=int, help='maximum number of pages to download', default=sys.maxsize)
    arg_parser.add_argument('--username', help='username for my.libsyn.com')
    arg_parser.add_argument('--password', help='password for my.libsyn.com')
    arg_parser.add_argument('--dry-run', action='store_true')

    args = arg_parser.parse_args()

    artwork_downloader = HamishAndAndyiTunesArtworkDownloader()
    downloader = LibSynDownloader()
    scrubber = HamishAndAndyPodcastScrubber()
    image_data = None

    if not dry_run_option:
        image_data = artwork_downloader.resolve_and_download()

        if args.username is not None and args.password is not None:
            print('Logging into my.libsyn.com')
            downloader.login(args.username, args.password)

    parser = HamishAndAndyLibSynParser(args.page, args.offset, args.limit, args.dry_run)

    while args.page_limit > 0 and parser.next():
        episodes = scrubber.scrub(parser.episodes)

        for episode in episodes:
            if args.dry_run:
                print('"%s", "%s"' % (episode['title'], episode['filename']))
            else:
                if os.path.isfile(episode['filename']):
                    print(AnsiEscapeSequences.GREEN_TEXT % '%s already exists, skipping' % episode['filename'])
                    continue

                print('Downloading ' + episode['filename'] + '...')

            if args.dry_run:
                # Pretend to download
                subprocess.call(['touch', episode['filename']])
                continue

            try:
                downloader.download_file(episode['file_url'], episode['filename'])
            except urllib2.HTTPError as http_error:
                if http_error.code == 404:
                    print(AnsiEscapeSequences.RED_TEXT % 'HTTP 404 when trying to download %s' % episode['filename'])
                    continue
                else:
                    raise http_error

            mp3_file = eyed3.load(episode['filename'])
            mp3_file.initTag()

            mp3_file.tag.title = unicode(episode['title'])
            mp3_file.tag.date = str(episode['release_date'].year)
            mp3_file.tag.artist = u'Hamish & Andy'
            mp3_file.tag.album = unicode('Podcasts ' + episode['release_date'].strftime('%Y'))
            mp3_file.tag.track_num = episode['track_number']
            mp3_file.tag.images.set(id3.frames.ImageFrame.MEDIA, image_data, 'image/jpeg')

            mp3_file.tag.save()

        args.page_limit -= 1


if __name__ == '__main__':
    main()
