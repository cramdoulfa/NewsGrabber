import threading
import os
import shutil
import sys
import json
import time
if os.path.isdir('services'):
    shutil.rmtree('services')
if not os.path.isdir('services'):
    os.makedirs('services')
if not os.path.isfile('services/__init__.py'):
    open('services/__init__.py', 'w').close()
import file
import services
import settings
import tools

reload(sys)
sys.setdefaultencoding("utf-8")


class RunServices(threading.Thread):

    """Services are here started and stopped."""

    def __init__(self):
        threading.Thread.__init__(self)
        self.services = []
        self.new_services = 0
        self.discovery_targets = file.File(settings.targets_discovery).read_lines()
        self.discovery_files = {}

    def run(self):
        self.refresh_services()

    def start_services(self):
        for file in [file for file in os.listdir('services') if file.startswith(
                'web__') and file.endswith('.py')]:
            service_name = file.replace('.py', '')
            if not service_name in self.services:
                self.new_services += 1
                self.services.append(service_name)
                settings.services[service_name] = Service(service_name)
                settings.services[service_name].daemon = True
                settings.services[service_name].start()
                settings.services[service_name].read_urls()
            settings.services[service_name].get_data()
        settings.irc_bot.send('PRIVMSG', 'Found {new_services} new services'.format(
                new_services=self.new_services), settings.irc_channel_main)
        self.new_services = 0
        self.distribute_services()

    def refresh_services(self):
        if os.path.isdir('services'):
            shutil.rmtree('services')
        os.system('git clone https://github.com/ArchiveTeam/NewsGrabber.git')
        shutil.copytree(os.path.join('NewsGrabber', 'services'), 'services')
        shutil.rmtree('NewsGrabber')
        reload(services)
        self.start_services()

    def distribute_services(self):
        service_lists = tools.splitlist(self.services, len(self.discovery_targets))
        for i, target in enumerate(self.discovery_targets):
            self.discovery_files[i] = file.File('services_list_{i}'.format(i=i))
            self.discovery_files[i].append_lines(service_lists[i])
        for i, target in enumerate(self.discovery_targets):
            exit = os.system('rsync -avz --no-o --no-g --progress --remove-source-files services_list_{i} {target}'.format(
                    i=i, target=target))
            if exit != 0:
                settings.irc_bot.send('PRIVMSG', 'Serviceslist services_list_{i} failed to sync'.format(
                        i=i), settings.irc_channel_main)


class Urls(threading.Thread):

    """In this class the new and old URLs are sorted and distributed."""

    def __init__(self):
        threading.Thread.__init__(self)
        self.url_lists = []
        self.url_count_new = 0
        self.url_count = 0
        self.urls_video = []
        self.urls_normal = []
        self.grab_targets = file.File(settings.targets_grab).read_lines()
        self.grab_files = {}

    def run(self):
        self.get_urls_new()

    def get_urls_new(self):
        runs = 0
        while True:
            for file_ in os.listdir(settings.dir_new_urllists):
                urls_new_count = 0
                urls_new = json.load(open(os.path.join(settings.dir_new_urllists,
                        file_)))
                for url in urls_new:
                    if url['service'] and not url['url'] in settings.services[url['service']].service_log_urls:
                        settings.services[url['service']].service_log_urls.append(url['url'])
                        self.add_url(url)
                        urls_new_count += 1
                    elif not url['url'] in self.urls_video + self.urls_normal:
                        self.add_url(url)
                        urls_new_count += 1
                self.count(urls_new_count)
                settings.logger.log('Loaded {urls} from file {file}'.format(
                        urls=urls_new_count, file=file_))
                os.rename(os.path.join(settings.dir_new_urllists, file_),
                        os.path.join(settings.dir_old_urllists, file_))
            runs += 1
            if runs%15 == 0 and not runs == 0:
                self.report_urls()
            if runs == 60:
                self.distribute_urls()
                runs = 0
            time.sleep(60)

    def report_urls(self):
        settings.irc_bot.send('PRIVMSG', '{urls} URLs added in the last 60 minutes.'.format(
                urls=self.url_count_new), settings.irc_channel_bot)

    def distribute_urls(self):
        urls_video = list(self.urls_video)
        urls_normal = list(self.urls_normal)
        self.urls_video = list(self.urls_video[len(urls_video)+1:])
        self.urls_normal = list(self.urls_normal[len(urls_normal)+1:])
        lists = [{'sort': '-videos', 'list': urls_video}, {'sort': '', 'list': urls_normal}]
        for list_ in lists:
            urls_lists = tools.splitlist(list_['list'], len(self.grab_targets))
            for i, target in enumerate(self.grab_targets):
                self.grab_files[i] = file.File('list{sort}_temp_{i}'.format(sort=list_['sort'], i=i))
                self.grab_files[i].append_lines(urls_lists[i])
            for i, target in enumerate(self.grab_targets):
                exit = os.system('rsync -avz --no-o --no-g --progress --remove-source-files list{sort}_temp_{i}'.format(
                        sort=list_['sort'], i=i))
                if exit != 0:
                    settings.irc_bot.send('PRIVMSG', 'URLslist list{sort}_temp_{i} failed to sync.'.format(
                            sort=list_['sort'], i=i), settings.irc_channel_main)

    def count(self, i):
        self.url_count += i
        self.url_count_new += i

    def add_url(self, url):
        if url['sort'] == 'video':
            self.urls_video.append(url['url'])
        elif url['sort'] == 'normal':
            self.urls_normal.append(url['url'])

class Service(threading.Thread):

    """This class is used to manage and run a service."""

    def __init__(self, service_name):
        threading.Thread.__init__(self)
        self.service_name = service_name
        self.service_refresh = None
        self.service_urls = None
        self.service_regex = None
        self.service_regex_video = None
        self.service_regex_live = None
        self.service_version = None
        self.service_wikidata = None
        self.service_log_urls = []
        self.service_file_log_urls = file.File(self.service_name)

    def write_urls(self):
        self.service_file_log_urls.write_lines(self.service_log_urls)

    def read_urls(self):
        self.service_log_urls = self.service_file_log_urls.read_lines()

    def get_data(self):
        self.service_refresh = eval('services.{service_name}.refresh'.format(
                service_name=self.service_name))
        self.service_urls = eval('services.{service_name}.urls'.format(
                service_name=self.service_name))
        self.service_regex = eval('services.{service_name}.regex'.format(
                service_name=self.service_name))
        self.service_regex_video = eval('services.{service_name}.videoregex'.format(
                service_name=self.service_name))
        self.service_regex_live = eval('services.{service_name}.liveregex'.format(
                service_name=self.service_name))
        self.service_version = eval('services.{service_name}.version'.format(
                service_name=self.service_name))
        try:
            self.service_wikidata = val('services.{service_name}.wikidata'.format(
                service_name=self.service_name))
        except:
            self.service_wikidata = None

    def get_new_url(self, url):
        if not url in self.service_log_urls:
            self.service_log_urls.append(url)
